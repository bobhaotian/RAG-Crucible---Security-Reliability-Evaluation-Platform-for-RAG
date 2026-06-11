"""Fetch BEIR SciFact and convert it to crucible's corpus + qa.jsonl format.

SciFact (Wadden et al., 2020; BEIR packaging by Thakur et al., 2021) is a
small scientific claim-verification benchmark: ~5.2k abstracts, 300 test
queries with document-level qrels — ideal as a public retrieval benchmark that
downloads in seconds and is never committed.

Conversion:
- each abstract becomes ``corpus/<doc_id>.txt`` (title + abstract);
- each test query becomes a qa.jsonl row with ``gold_docs`` (document-id gold
  kind — see crucible.eval.qa); SciFact has no short answer strings, so
  answer-accuracy metrics don't apply.

Usage: python scripts/fetch_scifact.py --out datasets/scifact
Then:  crucible ingest specs/scifact-local.yaml && crucible eval specs/scifact-local.yaml
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import urllib.request
import zipfile
from pathlib import Path

SCIFACT_URL = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip"


def fetch(url: str) -> bytes:
    print(f"downloading {url} ...")
    with urllib.request.urlopen(url) as response:
        data: bytes = response.read()
    print(f"  {len(data) / 1e6:.1f} MB")
    return data


def convert(zip_bytes: bytes, out_dir: Path) -> None:
    archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    corpus_dir = out_dir / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)

    n_docs = 0
    with archive.open("scifact/corpus.jsonl") as fh:
        for raw in io.TextIOWrapper(fh, encoding="utf-8"):
            doc = json.loads(raw)
            doc_id = str(doc["_id"])
            text = f"{doc.get('title', '').strip()}\n\n{doc.get('text', '').strip()}\n"
            (corpus_dir / f"{doc_id}.txt").write_text(text, encoding="utf-8")
            n_docs += 1

    queries: dict[str, str] = {}
    with archive.open("scifact/queries.jsonl") as fh:
        for raw in io.TextIOWrapper(fh, encoding="utf-8"):
            query = json.loads(raw)
            queries[str(query["_id"])] = str(query["text"])

    gold: dict[str, list[str]] = {}
    with archive.open("scifact/qrels/test.tsv") as fh:
        reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8"), delimiter="\t")
        for row in reader:
            if int(row["score"]) > 0:
                gold.setdefault(row["query-id"], []).append(f"{row['corpus-id']}.txt")

    qa_path = out_dir / "qa.jsonl"
    with qa_path.open("w", encoding="utf-8") as fh:
        for query_id in sorted(gold, key=int):
            fh.write(
                json.dumps(
                    {
                        "qid": f"scifact-{query_id}",
                        "question": queries[query_id],
                        "gold_docs": sorted(gold[query_id]),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"wrote {n_docs} docs to {corpus_dir} and {len(gold)} queries to {qa_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("datasets/scifact"))
    args = parser.parse_args()
    convert(fetch(SCIFACT_URL), args.out)


if __name__ == "__main__":
    main()
