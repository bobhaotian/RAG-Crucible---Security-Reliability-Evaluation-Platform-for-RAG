"""Fully-local provider: runs with zero keys (DESIGN.md §4.2).

- embed:    sentence-transformers (default: all-MiniLM-L6-v2)
- rerank:   sentence-transformers CrossEncoder (default: ms-marco-MiniLM-L-6-v2)
- generate: a small open chat model via transformers (default: Qwen2.5-0.5B-Instruct)

Models load lazily on first call (guarded by an asyncio lock) and run on CPU
for determinism; all compute is pushed off the event loop with
``asyncio.to_thread``. ``input_type`` is accepted and ignored — MiniLM embeds
symmetrically. Requires the ``local`` extra (``uv sync --extra local``);
the registry checks that before handing out these classes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from crucible.providers.base import (
    EmbedInputType,
    EmbedResult,
    GenerateResult,
    GenParams,
    Message,
    RerankItem,
    RerankResult,
    Usage,
    estimate_tokens,
)


class LocalEmbedder:
    def __init__(self, model: str) -> None:
        self.model = model
        self._st_model: Any = None
        self._lock = asyncio.Lock()

    async def _ensure_model(self) -> Any:
        async with self._lock:
            if self._st_model is None:
                from sentence_transformers import SentenceTransformer

                self._st_model = await asyncio.to_thread(SentenceTransformer, self.model)
        return self._st_model

    async def embed(self, texts: Sequence[str], *, input_type: EmbedInputType) -> EmbedResult:
        model = await self._ensure_model()
        arr = await asyncio.to_thread(
            lambda: model.encode(list(texts), convert_to_numpy=True, show_progress_bar=False)
        )
        vectors: list[list[float]] = arr.tolist()
        dim = len(vectors[0]) if vectors else int(model.get_sentence_embedding_dimension())
        usage = Usage(input_tokens=sum(estimate_tokens(t) for t in texts))
        return EmbedResult(vectors=vectors, model=self.model, dim=dim, usage=usage)


class LocalReranker:
    def __init__(self, model: str) -> None:
        self.model = model
        self._ce_model: Any = None
        self._lock = asyncio.Lock()

    async def _ensure_model(self) -> Any:
        async with self._lock:
            if self._ce_model is None:
                from sentence_transformers import CrossEncoder

                self._ce_model = await asyncio.to_thread(CrossEncoder, self.model)
        return self._ce_model

    async def rerank(self, query: str, documents: Sequence[str], *, top_n: int) -> RerankResult:
        model = await self._ensure_model()
        pairs = [(query, doc) for doc in documents]
        raw = await asyncio.to_thread(lambda: model.predict(pairs, show_progress_bar=False))
        scores = [float(s) for s in raw]
        order = sorted(range(len(documents)), key=lambda i: (-scores[i], i))[:top_n]
        ranking = [RerankItem(index=i, score=scores[i]) for i in order]
        usage = Usage(
            input_tokens=sum(estimate_tokens(d) for d in documents) + estimate_tokens(query)
        )
        return RerankResult(ranking=ranking, model=self.model, usage=usage)


class LocalGenerator:
    def __init__(self, model: str) -> None:
        self.model = model
        self._tokenizer: Any = None
        self._lm: Any = None
        self._lock = asyncio.Lock()

    async def _ensure_model(self) -> tuple[Any, Any]:
        async with self._lock:
            if self._lm is None:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer

                def _load() -> tuple[Any, Any]:
                    tokenizer = AutoTokenizer.from_pretrained(self.model)
                    lm = AutoModelForCausalLM.from_pretrained(self.model, dtype=torch.float32)
                    lm.eval()
                    return tokenizer, lm

                self._tokenizer, self._lm = await asyncio.to_thread(_load)
        return self._tokenizer, self._lm

    async def generate(self, messages: Sequence[Message], *, params: GenParams) -> GenerateResult:
        tokenizer, lm = await self._ensure_model()

        def _run() -> tuple[str, int, int, str]:
            import torch

            chat = [{"role": m.role, "content": m.content} for m in messages]
            enc = tokenizer.apply_chat_template(
                chat, add_generation_prompt=True, return_tensors="pt", return_dict=True
            )
            do_sample = params.temperature > 0.0
            gen_kwargs: dict[str, Any] = {
                "max_new_tokens": params.max_tokens,
                "do_sample": do_sample,
                "pad_token_id": tokenizer.eos_token_id,
            }
            if do_sample:
                gen_kwargs["temperature"] = params.temperature
                torch.manual_seed(params.seed if params.seed is not None else 0)
            with torch.no_grad():
                out = lm.generate(**enc, **gen_kwargs)
            prompt_len = int(enc["input_ids"].shape[1])
            gen_ids = out[0][prompt_len:]
            text = tokenizer.decode(gen_ids, skip_special_tokens=True).strip()
            finish = "length" if len(gen_ids) >= params.max_tokens else "stop"
            return text, prompt_len, len(gen_ids), finish

        text, tokens_in, tokens_out, finish = await asyncio.to_thread(_run)
        for stop in params.stop:
            text = text.split(stop)[0]
        return GenerateResult(
            text=text,
            model=self.model,
            finish_reason=finish,
            usage=Usage(input_tokens=tokens_in, output_tokens=tokens_out),
        )
