import { useEffect, useState } from "react";
import type { RunResults, RunRow } from "./api";
import { getResults, listRuns } from "./api";
import {
  AttackSuccess,
  Latency,
  PrivacyLeakage,
  RerankLift,
  TradeoffRadar,
} from "./charts";
import { DiffView } from "./DiffView";

export default function App() {
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [results, setResults] = useState<RunResults | null>(null);
  const [compareMode, setCompareMode] = useState(false);

  useEffect(() => {
    listRuns()
      .then((rows) => {
        setRuns(rows);
        const done = rows.find((r) => r.status === "succeeded");
        if (done) setSelected(done.id);
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!selected) return;
    getResults(selected)
      .then(setResults)
      .catch((e) => setError(String(e)));
  }, [selected]);

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
                onClick={() => setSelected(r.id)}
              >
                <span className={`status ${r.status}`}>{r.status}</span>
                <span className="run-name">{r.name}</span>
                <span className="run-id">{r.id.slice(0, 10)}</span>
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
          <SingleRun results={results} />
        ) : (
          <p className="placeholder">Select a run.</p>
        )}
      </main>
    </div>
  );
}

function SingleRun({ results }: { results: RunResults }) {
  const { run, suites } = results;
  return (
    <>
      <header className="run-header">
        <h2>{run.name}</h2>
        <span className={`status ${run.status}`}>{run.status}</span>
        <code>{run.id}</code>
        <span className="suites">{suites.map((s) => s.suite).join(" · ") || "no suites"}</span>
      </header>
      <div className="grid">
        <TradeoffRadar results={results} />
        <RerankLift results={results} />
        <AttackSuccess results={results} />
        <PrivacyLeakage results={results} />
        <Latency results={results} />
      </div>
    </>
  );
}
