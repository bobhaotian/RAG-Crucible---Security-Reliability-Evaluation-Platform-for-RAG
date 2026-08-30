// The receipts behind a number. Every rate on the dashboard is computed from
// per-item records the store already keeps (`/runs/{id}/records`), and a
// security tool is only believable if you can read the attack that succeeded —
// so any metric can be opened into the items it was averaged from.

import { useEffect, useMemo, useState } from "react";
import type { Evidence as Record_, RunResults } from "./api";
import { getEvidence } from "./api";

export interface Drill {
  suite: string;
  label: string;
  /** Payload-field equality filters. `metric` is a virtual field, resolved to
   *  real payload fields by METRIC_FILTERS below. */
  filter?: Record<string, string>;
}

/** Which records a suite metric was computed over. */
const METRIC_FILTERS: Record<string, Record<string, string>> = {
  knowledge_corruption_rate: { attack_type: "poison" },
  poison_retrieval_rate: { attack_type: "poison" },
  injection_compliance_rate: { attack_type: "injection" },
  injection_retrieval_rate: { attack_type: "injection" },
};

function expand(filter: Record<string, string> | undefined): Record<string, string> {
  if (!filter) return {};
  const { metric, ...fields } = filter;
  return { ...fields, ...(metric ? (METRIC_FILTERS[metric] ?? {}) : {}) };
}

const str = (r: Record_, k: string): string | undefined =>
  typeof r[k] === "string" ? (r[k] as string) : undefined;
const bool = (r: Record_, k: string): boolean | undefined =>
  typeof r[k] === "boolean" ? (r[k] as boolean) : undefined;
const num = (r: Record_, k: string): number | undefined =>
  typeof r[k] === "number" ? (r[k] as number) : undefined;

/** True when a record is the interesting kind — a successful attack, a leaked
 *  canary, an unsupported claim. These sort to the top. */
function flagged(r: Record_): boolean {
  return (
    bool(r, "succeeded") === true ||
    bool(r, "leaked") === true ||
    bool(r, "answer_match") === false ||
    (num(r, "first_hit_rank_reranked") ?? 1) > 1
  );
}

export function EvidenceDrawer({
  runId,
  results,
  drill,
  onClose,
}: {
  runId: string;
  results: RunResults;
  drill: Drill;
  onClose: () => void;
}) {
  const [records, setRecords] = useState<Record_[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    setRecords(null);
    setError(null);
    getEvidence(runId, drill.suite)
      .then(setRecords)
      .catch((e) => setError(String(e)));
  }, [runId, drill.suite]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const fields = useMemo(() => expand(drill.filter), [drill.filter]);

  const shown = useMemo(() => {
    if (!records) return [];
    const needle = q.trim().toLowerCase();
    return records
      .filter((r) => Object.entries(fields).every(([k, v]) => String(r[k]) === v))
      .filter((r) => !needle || JSON.stringify(r).toLowerCase().includes(needle))
      .sort((a, b) => Number(flagged(b)) - Number(flagged(a)));
  }, [records, fields, q]);

  const suiteSummary = results.suites.find((s) => s.suite === drill.suite);

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer">
        <header>
          <div>
            <h3>{drill.label}</h3>
            <p className="hint">
              {drill.suite} evidence
              {suiteSummary ? ` · ${suiteSummary.record_count} records in this run` : ""}
            </p>
          </div>
          <button className="drill" onClick={onClose}>
            close ✕
          </button>
        </header>

        <div className="drawer-tools">
          <input
            placeholder="filter text…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <span className="hint">
            {records ? `${shown.length} shown` : "loading…"}
          </span>
        </div>

        {error && <p className="error">{error}</p>}
        {records && shown.length === 0 && !error && (
          <p className="placeholder">No records match.</p>
        )}

        <ul className="records">
          {shown.map((r) => (
            <RecordCard key={num(r, "_id")} r={r} />
          ))}
        </ul>
      </aside>
    </>
  );
}

function RecordCard({ r }: { r: Record_ }) {
  const kind = str(r, "kind");
  return (
    <li className={flagged(r) ? "record flagged" : "record"}>
      <div className="record-head">
        <Outcome r={r} />
        {["attack_type", "defense", "probe_style", "canary_kind", "qid"].map((k) => {
          const v = str(r, k);
          return v ? (
            <span className="tag" key={k}>
              {v}
            </span>
          ) : null;
        })}
      </div>

      {str(r, "question") && <p className="record-q">{str(r, "question")}</p>}
      {str(r, "answer") && <pre className="record-a">{str(r, "answer")}</pre>}

      {kind === "retrieval" && (
        <p className="hint">
          first gold hit — vector search rank {num(r, "first_hit_rank_initial") ?? "—"} → after
          rerank {num(r, "first_hit_rank_reranked") ?? "—"}
        </p>
      )}

      {kind === "faithfulness" && Array.isArray(r["claims"]) && (
        <ul className="claims">
          {(r["claims"] as { claim: string; supported: boolean }[]).map((c, i) => (
            <li key={i} className={c.supported ? "ok" : "no"}>
              {c.supported ? "supported" : "unsupported"} — {c.claim}
            </li>
          ))}
        </ul>
      )}

      {kind === "canary_probe" && (
        <p className="hint">
          canary {str(r, "canary_id")} · retrieved {String(bool(r, "retrieved"))}
        </p>
      )}
    </li>
  );
}

function Outcome({ r }: { r: Record_ }) {
  const succeeded = bool(r, "succeeded");
  if (succeeded !== undefined)
    return (
      <span className={succeeded ? "badge bad" : "badge good"}>
        {succeeded ? "attack succeeded" : "attack blocked"}
      </span>
    );
  const leaked = bool(r, "leaked");
  if (leaked !== undefined)
    return (
      <span className={leaked ? "badge bad" : "badge good"}>
        {leaked ? "canary leaked" : "no leak"}
      </span>
    );
  const match = bool(r, "answer_match");
  if (match !== undefined)
    return (
      <span className={match ? "badge good" : "badge bad"}>
        {match ? "gold answer present" : "gold answer missing"}
      </span>
    );
  const rank = num(r, "first_hit_rank_reranked");
  if (rank !== undefined)
    return <span className={rank === 1 ? "badge good" : "badge warn"}>rank {rank}</span>;
  return null;
}
