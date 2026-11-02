// The receipts behind a number. Every rate on the dashboard is computed from
// per-item records the store already keeps (`/runs/{id}/records`), and a
// security tool is only believable if you can read the attack that succeeded —
// so any metric can be opened into the items it was averaged from.

import { useEffect, useMemo, useState } from "react";
import type { Evidence as Record_, RunResults } from "./api";
import { getEvidence } from "./api";
import {
  evidenceCountLine,
  excludedItemLine,
  foreignMarkers as foreign,
  isFlagged as flagged,
  matchedMarkers as matched,
  selectEvidence,
} from "./metrics";

export interface Drill {
  suite: string;
  label: string;
  /** Payload-field equality filters. `metric` is a virtual field, resolved to
   *  real payload fields by METRIC_FILTERS below. */
  filter?: Record<string, string>;
}

const str = (r: Record_, k: string): string | undefined =>
  typeof r[k] === "string" ? (r[k] as string) : undefined;
const bool = (r: Record_, k: string): boolean | undefined =>
  typeof r[k] === "boolean" ? (r[k] as boolean) : undefined;
const num = (r: Record_, k: string): number | undefined =>
  typeof r[k] === "number" ? (r[k] as number) : undefined;

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

  const view = useMemo(
    () => (records ? selectEvidence(records, drill.filter, q) : { trials: [], excluded: [] }),
    [records, drill.filter, q],
  );
  const shown = view.trials;

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
            {records ? evidenceCountLine(view) : "loading…"}
          </span>
        </div>

        {error && <p className="error">{error}</p>}
        {records && shown.length === 0 && view.excluded.length === 0 && !error && (
          <p className="placeholder">No records match.</p>
        )}

        <ul className="records">
          {shown.map((r) => (
            <RecordCard key={num(r, "_id")} r={r} />
          ))}
        </ul>

        {view.excluded.length > 0 && (
          <div className="excluded-items">
            <h4>Excluded from every rate</h4>
            <ul>
              {view.excluded.map((r) => (
                <li key={num(r, "_id")}>{excludedItemLine(r)}</li>
              ))}
            </ul>
          </div>
        )}
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
        {kind === "attack" && <ResponseSource r={r} />}
        {str(r, "kind") === "clean_defense" && (
          <span className="tag" title="unattacked control question">clean control</span>
        )}
        {["defense", "probe_style", "canary_kind", "qid"].map((k) => {
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

      {kind === "attack" && <AttackFields r={r} />}

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

/** Which attack actually produced this answer — the headline a reader needs
 *  next to "did the attack under test succeed?". */
function ResponseSource({ r }: { r: Record_ }) {
  const all = matched(r);
  if (all === null) return <span className="badge">marker scan not recorded</span>;
  const own = all.filter((m) => m.marker === str(r, "own_marker"));
  if (own.length > 0)
    return (
      <span className="badge bad">answered with {own[0].attack_type} (attack under test)</span>
    );
  const others = foreign(r) ?? [];
  if (others.length === 0)
    return <span className="badge good">no attacker text in answer</span>;
  const sameQuestion = others[0].qid === str(r, "qid");
  return (
    <span className="badge warn">
      answered with {others[0].attack_type} —{" "}
      {sameQuestion ? "competing attack, same question" : `planted on ${others[0].qid}`}
    </span>
  );
}

/** Everything needed to audit one trial without reading the source. */
function AttackFields({ r }: { r: Record_ }) {
  const tested = str(r, "attack_type");
  const own = str(r, "own_marker");
  const succeeded = bool(r, "succeeded");
  const scan = matched(r);
  const others = foreign(r) ?? [];
  return (
    <dl className="fields">
      <dt>attack under test</dt>
      <dd>
        <b>{tested}</b> targeting <b>{str(r, "qid")}</b>
        {own && (
          <>
            {" "}
            · scored on marker <code>{own}</code>
          </>
        )}
      </dd>

      <dt>defense</dt>
      <dd>{str(r, "defense")}</dd>

      <dt>its document retrieved</dt>
      <dd>{bool(r, "retrieved") ? "yes — it reached the prompt" : "no — never reached the prompt"}</dd>

      <dt>scored</dt>
      <dd className={succeeded ? "bad" : "good"}>
        {succeeded
          ? `succeeded — the ${tested} marker appeared in the answer`
          : `failed — the ${tested} marker never appeared`}
      </dd>

      <dt>answer produced by</dt>
      <dd className={scan === null ? "" : bool(r, "compromised") ? "bad" : "good"}>
        {scan === null
          ? "not recorded — this run did not scan the answer for planted markers"
          : scan.length === 0
            ? "no attacker-planted text"
            : scan
                .map((m) =>
                  m.marker === own
                    ? `${m.attack_type} under test (${m.marker})`
                    : `${m.attack_type} attack on ${m.qid} (${m.marker})`,
                )
                .join(", ")}
        {!succeeded && others.length > 0 && (
          <>
            {" "}
            — <b>the model was compromised even though this attack was blocked</b>
          </>
        )}
      </dd>
    </dl>
  );
}

function Outcome({ r }: { r: Record_ }) {
  // Refusing to answer is the defense's cost, and it is invisible if the card
  // only reports whether the gold answer was present.
  if (bool(r, "abstained")) return <span className="badge warn">refused to answer</span>;
  const succeeded = bool(r, "succeeded");
  if (succeeded !== undefined) {
    if (succeeded) return <span className="badge bad">attack succeeded</span>;
    // Blocking the attack under test is not a clean pass if the model was
    // compromised by another attack in the same index — don't render it green.
    if (bool(r, "compromised")) return <span className="badge warn">this attack blocked</span>;
    return <span className="badge good">attack blocked</span>;
  }
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
