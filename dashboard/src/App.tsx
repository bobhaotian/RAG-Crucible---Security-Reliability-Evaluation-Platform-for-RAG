import { useCallback, useEffect, useState } from "react";
import type { RunResults, RunRow } from "./api";
import { getResults, getSpec, listRuns } from "./api";
import {
  AttackSuccess,
  Compromise,
  DefenseCost,
  Faithfulness,
  Latency,
  PrivacyLeakage,
  RerankLift,
  TradeoffRadar,
} from "./charts";
import { DiffView } from "./DiffView";
import type { Drill } from "./Evidence";
import { EvidenceDrawer } from "./Evidence";
import { duration, kpis, pipelineChips, summaryMarkdown } from "./metrics";

/** The selected run — and any open evidence view — live in the URL, so "the
 *  attacks that succeeded under prompt_isolation" is a link someone can paste
 *  into an issue rather than a click path they have to describe. */
function runFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get("run");
}

function drillFromUrl(): Drill | null {
  const params = new URLSearchParams(window.location.search);
  const suite = params.get("drill");
  if (!suite) return null;
  const raw = params.get("df");
  let filter: Record<string, string> | undefined;
  if (raw) {
    try {
      filter = JSON.parse(raw) as Record<string, string>;
    } catch {
      filter = undefined;
    }
  }
  return { suite, label: params.get("dl") ?? `${suite} evidence`, filter };
}

function syncUrl(run: string | null, drill: Drill | null): void {
  const url = new URL(window.location.href);
  const set = (key: string, value: string | null) =>
    value === null ? url.searchParams.delete(key) : url.searchParams.set(key, value);
  set("run", run);
  set("drill", drill?.suite ?? null);
  set("dl", drill?.label ?? null);
  set("df", drill?.filter ? JSON.stringify(drill.filter) : null);
  window.history.replaceState(null, "", url);
}

export default function App() {
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(runFromUrl());
  const [results, setResults] = useState<RunResults | null>(null);
  const [spec, setSpec] = useState<Record<string, unknown> | null>(null);
  const [compareMode, setCompareMode] = useState(false);
  const [drill, setDrill] = useState<Drill | null>(drillFromUrl());

  useEffect(() => {
    listRuns()
      .then((rows) => {
        setRuns(rows);
        setSelected((current) => {
          if (current && rows.some((r) => r.id === current)) return current;
          return rows.find((r) => r.status === "succeeded")?.id ?? null;
        });
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setResults(null);
    setSpec(null);
    getResults(selected)
      .then(setResults)
      .catch((e) => setError(String(e)));
    // The spec is a nice-to-have: an older API without /spec should not blank
    // out the run view.
    getSpec(selected)
      .then(setSpec)
      .catch(() => setSpec(null));
  }, [selected]);

  useEffect(() => syncUrl(selected, drill), [selected, drill]);

  const onDrill = useCallback((d: Drill) => setDrill(d), []);

  return (
    <div className="layout">
      <aside className="sidebar">
        <h1>rag-crucible</h1>
        <p className="subtitle">RAG evaluation runs</p>
        <label className="compare-toggle">
          <input
            type="checkbox"
            checked={compareMode}
            onChange={(e) => setCompareMode(e.target.checked)}
          />
          Compare two runs
        </label>
        <ul className="runs">
          {runs.map((r) => (
            <li key={r.id}>
              <button
                className={r.id === selected ? "run active" : "run"}
                onClick={() => {
                  setSelected(r.id);
                  setDrill(null);
                }}
              >
                <span className={`status ${r.status}`}>{r.status}</span>
                <span className="run-name">{r.name}</span>
                <span className="run-id">
                  {r.id.slice(0, 10)}
                  {duration(r) ? ` · ${duration(r)}` : ""}
                </span>
              </button>
            </li>
          ))}
          {runs.length === 0 && !error && <li className="empty">No runs yet.</li>}
        </ul>
        {error && <p className="error">{error}</p>}
      </aside>

      <main className="content">
        {compareMode ? (
          <DiffView runs={runs} baseId={selected} />
        ) : results ? (
          <SingleRun results={results} spec={spec} onDrill={onDrill} />
        ) : (
          <p className="placeholder">Select a run.</p>
        )}
      </main>

      {drill && results && selected && (
        <EvidenceDrawer
          runId={selected}
          results={results}
          drill={drill}
          onClose={() => setDrill(null)}
        />
      )}
    </div>
  );
}

function SingleRun({
  results,
  spec,
  onDrill,
}: {
  results: RunResults;
  spec: Record<string, unknown> | null;
  onDrill: (d: Drill) => void;
}) {
  const { run, suites } = results;
  const chips = pipelineChips(spec);
  const cards = kpis(results);

  return (
    <>
      <header className="run-header">
        <h2>{run.name}</h2>
        <span className={`status ${run.status}`}>{run.status}</span>
        {duration(run) && <span className="suites">{duration(run)}</span>}
        <code>{run.id}</code>
        <code title="spec hash">#{run.spec_hash.slice(0, 12)}</code>
        <span className="suites">{suites.map((s) => s.suite).join(" · ") || "no suites"}</span>
        <CopySummary results={results} />
      </header>

      {chips.length > 0 && (
        <ul className="chips">
          {chips.map(([k, v]) => (
            <li key={k}>
              <span>{k}</span>
              <b>{v}</b>
            </li>
          ))}
        </ul>
      )}

      {cards.length > 0 && (
        <ul className="kpis">
          {cards.map((k) => (
            <li key={k.key}>
              <button onClick={() => onDrill({ suite: k.suite, label: k.label })}>
                <span className="kpi-label">{k.label}</span>
                <span className="kpi-value">{(k.value as number).toFixed(3)}</span>
                <span className="kpi-detail">
                  {k.detail} · {k.direction === "up" ? "higher is better" : "lower is better"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="grid">
        <TradeoffRadar results={results} onDrill={onDrill} />
        <RerankLift results={results} onDrill={onDrill} />
        <Faithfulness results={results} onDrill={onDrill} />
        <AttackSuccess results={results} onDrill={onDrill} />
        <Compromise results={results} onDrill={onDrill} />
        <DefenseCost results={results} onDrill={onDrill} />
        <PrivacyLeakage results={results} onDrill={onDrill} />
        <Latency results={results} />
      </div>
    </>
  );
}

function CopySummary({ results }: { results: RunResults }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="drill"
      onClick={() => {
        void navigator.clipboard.writeText(summaryMarkdown(results)).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        });
      }}
    >
      {copied ? "copied ✓" : "copy summary"}
    </button>
  );
}
