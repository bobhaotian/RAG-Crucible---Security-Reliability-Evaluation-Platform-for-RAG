// Two-run comparison: pick a second run and diff shared metrics side by side
// (e.g. Cohere vs local provider, or rerank on vs off). Driven entirely by the
// flat metrics list, so it works across any pair of runs.

import { useEffect, useState } from "react";
import type { RunResults, RunRow } from "./api";
import { getResults } from "./api";
import { summaryMetric } from "./metrics";

export function DiffView({ runs, baseId }: { runs: RunRow[]; baseId: string | null }) {
  const [otherId, setOtherId] = useState<string | null>(null);
  const [base, setBase] = useState<RunResults | null>(null);
  const [other, setOther] = useState<RunResults | null>(null);

  useEffect(() => {
    if (baseId) getResults(baseId).then(setBase).catch(() => setBase(null));
  }, [baseId]);
  useEffect(() => {
    if (otherId) getResults(otherId).then(setOther).catch(() => setOther(null));
  }, [otherId]);

  if (!base) return <p className="placeholder">Select a base run on the left.</p>;

  return (
    <>
      <header className="run-header">
        <h2>Compare runs</h2>
        <select value={otherId ?? ""} onChange={(e) => setOtherId(e.target.value || null)}>
          <option value="">— pick a run to compare —</option>
          {runs
            .filter((r) => r.id !== baseId && r.status === "succeeded")
            .map((r) => (
              <option key={r.id} value={r.id}>
                {r.name} ({r.id.slice(0, 8)})
              </option>
            ))}
        </select>
      </header>
      {other ? <DiffTable base={base} other={other} /> : <p className="hint">Pick a second run.</p>}
    </>
  );
}

function DiffTable({ base, other }: { base: RunResults; other: RunResults }) {
  const keyOf = (suite: string, label: string) => `${suite} · ${label}`;
  const rows = new Map<string, { a?: number; b?: number }>();
  for (const m of base.metrics) rows.set(keyOf(m.suite, summaryMetric(m)), { a: m.value });
  for (const m of other.metrics) {
    const key = keyOf(m.suite, summaryMetric(m));
    rows.set(key, { ...(rows.get(key) ?? {}), b: m.value });
  }

  return (
    <table className="diff">
      <thead>
        <tr>
          <th>metric</th>
          <th>{base.run.name}</th>
          <th>{other.run.name}</th>
          <th>Δ</th>
        </tr>
      </thead>
      <tbody>
        {[...rows.entries()].map(([key, { a, b }]) => {
          const delta = a !== undefined && b !== undefined ? b - a : undefined;
          return (
            <tr key={key}>
              <td>{key}</td>
              <td>{fmt(a)}</td>
              <td>{fmt(b)}</td>
              <td className={delta === undefined ? "" : delta >= 0 ? "pos" : "neg"}>
                {delta === undefined ? "—" : (delta >= 0 ? "+" : "") + delta.toFixed(4)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function fmt(v: number | undefined): string {
  return v === undefined ? "—" : v.toFixed(4);
}
