// Two-run comparison: pick a second run and diff shared metrics side by side
// (e.g. Cohere vs local provider, or rerank on vs off). Driven entirely by the
// flat metrics list, so it works across any pair of runs.

import { useEffect, useState } from "react";
import type { RunResults, RunRow } from "./api";
import { getResults } from "./api";
import { PanelBoundary } from "./Boundary";
import type { DiffRow, Reading } from "./metrics";
import { diffRows, formatReading, subsetShort } from "./metrics";

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
      {other ? (
        <PanelBoundary key={`${base.run.id}-${other.run.id}`} title="Comparison">
          <DiffTable base={base} other={other} />
        </PanelBoundary>
      ) : (
        <p className="hint">Pick a second run.</p>
      )}
    </>
  );
}

function DiffTable({ base, other }: { base: RunResults; other: RunResults }) {
  const rows = diffRows(base, other);
  const unlike = rows.filter((r) => r.nDiffers).length;
  return (
    <>
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
          {rows.map((row) => (
            <tr key={row.key}>
              <td>{row.key}</td>
              <Cell r={row.a} count={row.count} />
              <Cell r={row.b} count={row.count} />
              <Delta row={row} />
            </tr>
          ))}
        </tbody>
      </table>
      {unlike > 0 && (
        <p className="hint">
          <b>≠n</b> marks {unlike} {unlike === 1 ? "metric" : "metrics"} scored over a different
          number of units in each run, so the delta compares unlike samples.
        </p>
      )}
    </>
  );
}

/** The change, only when both runs measured the metric. A count's change is
 *  neither good nor bad, and a delta over unlike denominators is flagged. */
function Delta({ row }: { row: DiffRow }) {
  const { delta, count, nDiffers, n } = row;
  if (delta === undefined) return <td>—</td>;
  const tone = count || delta === 0 ? "" : delta > 0 ? "pos" : "neg";
  const text = (delta > 0 ? "+" : "") + delta.toFixed(count ? 0 : 4);
  return (
    <td
      className={`${tone}${nDiffers ? " ndiff" : ""}`.trim() || undefined}
      title={nDiffers ? `n differs: ${n[0]} vs ${n[1]}, so this is not like-for-like` : undefined}
    >
      {text}
      {nDiffers && <i className="ndiff-mark"> ≠n</i>}
    </td>
  );
}

/** A measured value (an integer for a count, with "53 of 56" when scored over
 *  a subset), `— (<state>)` with the reason on hover, or `—` when the run did
 *  not emit the metric. */
function Cell({ r, count }: { r: Reading | undefined; count: boolean }) {
  const text = r?.measured
    ? `${r.value.toFixed(count ? 0 : 4)}${r.subset ? ` (${subsetShort(r.subset)})` : ""}`
    : formatReading(r, 4);
  return (
    <td className={r && !r.measured ? "na" : undefined} title={r && !r.measured ? r.reason : undefined}>
      {text}
    </td>
  );
}
