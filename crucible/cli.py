"""crucible CLI: run the core spine end-to-end from a spec file.

    crucible ingest specs/demo.yaml          # corpus → filters → chunks → index
    crucible query  specs/demo.yaml "..."    # retrieve → rerank → generate
    crucible submit specs/demo.yaml          # queue → evaluate → DB + portable report

The API and runner (Phase 3) front the same core library; the CLI exists so
the spine works and is demoable before any service does.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from crucible import __version__
from crucible.config import RunSpec, SpecError, load_spec
from crucible.eval import JudgeCacheMissError, QADatasetError, run_eval
from crucible.eval.report import write_report
from crucible.index import IndexMeta, VectorIndex, open_saved_index
from crucible.ingest import build_index
from crucible.paths import default_db_path, index_dir_for, submitted_run_results_dir
from crucible.pipeline import Answer, build_pipeline
from crucible.providers import ProviderError
from crucible.runner import DuplicateRunError, ResultStore, execute_or_wait_for_run, worker_loop

app = typer.Typer(
    name="crucible",
    help="Security, faithfulness, and privacy evaluation for RAG pipelines.",
    no_args_is_help=True,
    add_completion=False,
)

SpecPathArg = Annotated[Path, typer.Argument(help="Path to a RunSpec YAML file")]
DbOption = Annotated[
    Path | None, typer.Option("--db", help="Result-store path (default: $CRUCIBLE_DB)")
]


def _store(db: Path | None) -> ResultStore:
    return ResultStore(db if db is not None else default_db_path())


def _load_spec_or_exit(spec_path: Path) -> RunSpec:
    try:
        return load_spec(spec_path)
    except SpecError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc


def _load_index_or_exit(spec: RunSpec) -> tuple[VectorIndex, IndexMeta]:
    directory = index_dir_for(spec.name)
    try:
        index, meta = open_saved_index(directory)
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    if meta.fingerprint != spec.ingest_fingerprint():
        typer.echo(
            f"error: index at {directory} was built from a different ingest "
            "configuration; re-run `crucible ingest` for this spec",
            err=True,
        )
        raise typer.Exit(code=2)
    return index, meta


@app.command()
def ingest(
    spec_path: SpecPathArg,
    force: Annotated[bool, typer.Option("--force", help="Rebuild even if up to date")] = False,
) -> None:
    """Build (or rebuild) the vector index for a spec."""
    spec = _load_spec_or_exit(spec_path)
    out_dir = index_dir_for(spec.name)

    if not force and (out_dir / "meta.json").is_file():
        meta = IndexMeta.model_validate_json((out_dir / "meta.json").read_text(encoding="utf-8"))
        if meta.fingerprint == spec.ingest_fingerprint():
            typer.echo(
                f"index at {out_dir} is up to date ({meta.chunk_count} chunks); "
                "use --force to rebuild"
            )
            return

    try:
        report = asyncio.run(build_index(spec, out_dir))
    except (ProviderError, NotImplementedError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"ingested corpus {spec.corpus.documents}")
    typer.echo(f"  documents loaded : {report.docs_loaded} ({report.files_skipped} skipped)")
    for stat in report.filter_stats:
        typer.echo(f"  filter {stat.name:<12}: dropped {stat.dropped}")
    typer.echo(f"  documents indexed: {report.docs_indexed}")
    typer.echo(f"  chunks           : {report.chunks} (dim {report.dim})")
    typer.echo(f"  duration         : {report.duration_s}s")
    typer.echo(f"  index            : {out_dir}")


@app.command()
def query(
    spec_path: SpecPathArg,
    question: Annotated[str, typer.Argument(help="The question to answer")],
) -> None:
    """Answer one question through the configured pipeline, with citations."""
    spec = _load_spec_or_exit(spec_path)
    index, _ = _load_index_or_exit(spec)

    try:
        pipeline = build_pipeline(spec, index)
        answer = asyncio.run(pipeline.answer(question))
    except ProviderError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    _print_answer(question, answer)


def _print_answer(question: str, answer: Answer) -> None:
    typer.echo(f"Q: {question}")
    typer.echo(f"A: {answer.text}")
    typer.echo("")
    typer.echo("Citations:")
    for citation in answer.citations:
        candidate = answer.context.candidates[citation.marker - 1]
        label = candidate.chunk.source + (
            f" › {candidate.chunk.section}" if candidate.chunk.section else ""
        )
        kind = "cited by model" if citation.parsed else "context fallback"
        typer.echo(f"  [{citation.marker}] {label} (chunk {citation.chunk_id}, {kind})")
    t = answer.timings
    rerank = f"{t.rerank_ms:.1f}" if t.rerank_ms is not None else "off"
    typer.echo(
        f"Timings (ms): embed {t.embed_query_ms:.1f} | retrieve {t.retrieve_ms:.1f} | "
        f"rerank {rerank} | generate {t.generate_ms:.1f} | total {t.total_ms:.1f}"
    )
    typer.echo(f"Tokens: in {answer.usage.input_tokens}, out {answer.usage.output_tokens}")


@app.command("eval")
def eval_command(
    spec_path: SpecPathArg,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Output directory (default: results/<spec name>)"),
    ] = None,
) -> None:
    """Run the spec's evaluation suites; write results.json, summary.md, plots."""
    spec = _load_spec_or_exit(spec_path)
    if spec.suites is None:
        typer.echo(f"error: spec {spec.name!r} configures no `suites:`", err=True)
        raise typer.Exit(code=2)
    index, _ = _load_index_or_exit(spec)
    out_dir = out if out is not None else Path("results") / spec.name

    try:
        result = asyncio.run(run_eval(spec, index))
    except (ProviderError, QADatasetError, JudgeCacheMissError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    written = write_report(result, out_dir)
    for suite in result.suites:
        if suite.status == "failed":
            typer.echo(f"{suite.suite}: FAILED ({suite.error})")
            continue
        shown = [m for m in suite.metrics if m.variant in ("", "rerank=on", "defense=none")][:4]
        rendered = " · ".join(f"{m.name}={m.value:.3f}" for m in shown)
        typer.echo(f"{suite.suite}: {rendered}")
    typer.echo("wrote: " + ", ".join(str(p) for p in written))


@app.command()
def submit(
    spec_path: SpecPathArg,
    force: Annotated[bool, typer.Option("--force", help="Re-run an identical spec")] = False,
    queue_only: Annotated[
        bool,
        typer.Option(
            "--queue-only",
            help="Enqueue and return immediately; requires a separate `crucible worker`",
        ),
    ] = False,
    db: DbOption = None,
) -> None:
    """Submit and complete an evaluation run; persist DB rows and reports.

    By default this command acts as an inline worker and returns only after the
    run reaches a terminal state. Use ``--queue-only`` when a long-running
    worker service should execute the job asynchronously.
    """
    spec = _load_spec_or_exit(spec_path)
    if spec.suites is None:
        typer.echo(f"error: spec {spec.name!r} configures no `suites:`", err=True)
        raise typer.Exit(code=2)
    store = _store(db)
    try:
        run_id = store.submit_run(spec, force=force)
    except DuplicateRunError as exc:
        existing = store.get_run(exc.existing_run_id)
        if queue_only or existing.status not in ("pending", "running"):
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        # A matching active job may be left from an earlier queue-only
        # submission or already owned by a background worker. Attach to it so
        # the default command still fulfills its submit-and-complete contract.
        run_id = existing.id
        typer.echo(f"attaching to existing {existing.status} run")
    typer.echo(run_id)
    if queue_only:
        typer.echo("queued; a `crucible worker` must process this run")
        return

    typer.echo("running evaluation…")
    row = asyncio.run(execute_or_wait_for_run(store, run_id))
    report_dir = submitted_run_results_dir(spec.name, run_id)
    if report_dir.is_dir():
        typer.echo(f"report: {report_dir}")
    if row.status != "succeeded":
        typer.echo(f"{row.status}: {row.error or 'run did not complete'}", err=True)
        raise typer.Exit(code=1)
    typer.echo("succeeded")


@app.command()
def worker(
    db: DbOption = None,
    once: Annotated[
        bool, typer.Option("--once", help="Drain the queue and exit instead of polling")
    ] = False,
) -> None:
    """Run the evaluation worker (claims queued runs and executes them)."""
    store = _store(db)
    typer.echo("worker started; polling for runs (ctrl-c to stop)" if not once else "draining…")
    processed = asyncio.run(worker_loop(store, drain=once))
    if once:
        typer.echo(f"processed {processed} run(s)")


@app.command()
def runs(db: DbOption = None) -> None:
    """List recent runs."""
    for row in _store(db).list_runs(limit=20):
        typer.echo(f"{row.id}  {row.status:<9}  {row.name}  ({row.created_at})")


@app.command()
def serve(
    spec_path: Annotated[Path | None, typer.Option("--spec", help="Spec served by /query")] = None,
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8000,
    db: DbOption = None,
) -> None:
    """Start the API server (submit/poll/fetch runs + live /query)."""
    import uvicorn

    from api.main import create_app

    uvicorn.run(create_app(db_path=db, serve_spec_path=spec_path), host=host, port=port)


@app.command()
def version() -> None:
    """Print the crucible version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
