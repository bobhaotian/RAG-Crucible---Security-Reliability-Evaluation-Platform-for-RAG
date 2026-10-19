// Panels over the shapes from metrics.ts. Each returns null when there's
// nothing to plot, so views compose suites that may be absent.
//
// Most panels are hand-rolled bars rather than Recharts: every quantity here is
// a rate in [0,1] or a duration, read against a baseline, and a labelled
// horizontal bar shows that without rotated ticks, colliding legends, or a
// value axis that hides the difference the panel exists to show. Recharts still
// draws the radar, where it earns its keep.

import type { ReactNode } from "react";
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from "recharts";
import type { Metric, RunResults } from "./api";
import type { Drill } from "./Evidence";
import type { DefenseGroup, Reading, Unmeasured } from "./metrics";
import {
  COMPROMISE_METRICS,
  COST_METRICS,
  METRIC_GLOSS,
  breakdown,
  understatements,
  contamination,
  contextMetrics,
  defenseGroups,
  faithfulness,
  formatReading,
  groupUnmeasured,
  judgeGap,
  latency,
  read,
  rerankLift,
  tradeoffRadar,
  unmeasured,
  unmeasuredOf,
} from "./metrics";

const ACCENT = "#6c5ce7";

export interface PanelProps {
  results: RunResults;
  onDrill?: (drill: Drill) => void;
}

function Panel({
  title,
  drill,
  onDrill,
  notMeasured = [],
  children,
}: {
  title: string;
  drill?: Drill;
  onDrill?: (drill: Drill) => void;
  notMeasured?: Unmeasured[];
  children: ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h3>{title}</h3>
        {drill && onDrill && (
          <button className="drill" onClick={() => onDrill(drill)}>
            evidence →
          </button>
        )}
      </div>
      {children}
      <NotMeasuredList items={notMeasured} />
    </section>
  );
}

/** Why each metric in a panel has no number — the panel's equivalent of the
 *  report's "Not measured" list, one line per distinct state and reason.
 *  Renders nothing when everything was measured. */
function NotMeasuredList({ items }: { items: Unmeasured[] }) {
  if (items.length === 0) return null;
  return (
    <div className="not-measured">
      <h4>Not measured</h4>
      <ul>
        {groupUnmeasured(items).map((g) => (
          <li key={`${g.state}|${g.reason}`}>
            {g.labels.map((label, i) => (
              <span key={label}>
                {i > 0 && ", "}
                <code>{label}</code>
              </span>
            ))}{" "}
            <span className={`state ${g.state}`}>{g.state}</span> {g.reason}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The narrow value column beside a bar. The state is already written in the
 *  track, so a metric that was not measured gets a bare dash here. */
function barValue(r: Reading, digits: number): string {
  return r.measured ? r.value.toFixed(digits) : "—";
}

/** Where a bar would be, for a metric that was not measured: its state, never
 *  an empty track (which reads as 0) and never the "0.00 ✓" of a true zero. */
function StateInTrack({ reading }: { reading: Reading }) {
  if (reading.measured) return null;
  return (
    <span className="bar-na" title={reading.reason}>
      {reading.state}
    </span>
  );
}

/** Percent position of `value` inside [min,max], clamped. */
function pct(value: number, min: number, max: number): number {
  if (max <= min) return 50;
  return Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100));
}

function signed(v: number, digits = 3): string {
  return (v > 0 ? "+" : v < 0 ? "−" : "±") + Math.abs(v).toFixed(digits);
}

// ------------------------------------------------------------------ trade-off

export function TradeoffRadar({ results, onDrill }: PanelProps) {
  const { data, unmeasured: missing } = tradeoffRadar(results);
  if (data.length < 3 && missing.length === 0) return null;
  const values = (
    <ul className="axis-values">
      {data.map((d) => (
        <li key={String(d.name)}>
          <span>{d.name}</span>
          <b>{Number(d.value).toFixed(3)}</b>
        </li>
      ))}
    </ul>
  );
  if (data.length < 3) {
    // Too few measured axes for a shape, but the reasons still belong on the page.
    return (
      <Panel
        title="Quality · robustness · privacy"
        drill={{ suite: "security", label: "attacks behind the robustness axis" }}
        onDrill={onDrill}
        notMeasured={missing}
      >
        <p className="hint">
          Only {data.length} of the four axes {data.length === 1 ? "was" : "were"} measured,
          too few to draw the trade-off. An axis that was not measured is never drawn at 0.
        </p>
        {data.length > 0 && values}
      </Panel>
    );
  }
  return (
    <Panel
      title="Quality · robustness · privacy"
      drill={{ suite: "security", label: "attacks behind the robustness axis" }}
      onDrill={onDrill}
      notMeasured={missing}
    >
      <ResponsiveContainer width="100%" height={230}>
        <RadarChart data={data} outerRadius="68%" margin={{ top: 16, right: 56, bottom: 8, left: 56 }}>
          <PolarGrid stroke="#2a2e3a" />
          <PolarAngleAxis dataKey="name" tick={{ fill: "#9aa0ad", fontSize: 12 }} />
          <PolarRadiusAxis domain={[0, 1]} tick={false} axisLine={false} />
          <Radar dataKey="value" stroke={ACCENT} fill={ACCENT} fillOpacity={0.45} />
        </RadarChart>
      </ResponsiveContainer>
      {values}
      <p className="hint">
        Each axis 0–1, bigger is safer. Robustness and privacy are plotted inverted
        (1 − attack success, 1 − leakage); the cards above show them undirected.
        {missing.length > 0 && " An axis that was not measured is left off, not drawn at 0."}
      </p>
    </Panel>
  );
}

// ---------------------------------------------------------------- rerank lift

export function RerankLift({ results, onDrill }: PanelProps) {
  const { rows, axis, hasOn, unmeasured: missing } = rerankLift(results);
  if (rows.length === 0) return null;
  if (axis === undefined) {
    // Nothing to place on an axis: no empty 0.000–1.000 track, just the reasons.
    return (
      <Panel
        title="Rerank lift"
        drill={{ suite: "retrieval", label: "per-question retrieval ranks" }}
        onDrill={onDrill}
        notMeasured={missing}
      >
        <p className="hint">No retrieval metric in this run was measured, so there is nothing to plot.</p>
      </Panel>
    );
  }
  const { min, max } = axis;
  const shown = rows.filter((r) => r.headline);
  const rest = rows.filter((r) => !r.headline);
  const moved = rows.filter((r) => r.delta !== undefined);
  const best = moved.length
    ? moved.reduce((a, b) => (Math.abs(b.delta ?? 0) > Math.abs(a.delta ?? 0) ? b : a))
    : undefined;

  const row = (r: (typeof rows)[number]) => {
    // Dots only for measured sides, the line only when both are; a side that
    // was not measured is named in the delta column instead.
    const a = r.off.measured ? pct(r.off.value, min, max) : undefined;
    const b = r.on?.measured ? pct(r.on.value, min, max) : undefined;
    const missingSide = !r.off.measured ? r.off : r.on && !r.on.measured ? r.on : undefined;
    return (
      <li key={r.name} title={`off ${formatReading(r.off, 4)} → on ${formatReading(r.on, 4)}`}>
        <span className="db-label">{r.name}</span>
        <span className="db-track">
          {a !== undefined && b !== undefined && r.delta !== undefined && (
            <span
              className={r.delta >= 0 ? "db-line pos" : "db-line neg"}
              style={{ left: `${Math.min(a, b)}%`, width: `${Math.abs(b - a)}%` }}
            />
          )}
          {a !== undefined && <span className="db-dot off" style={{ left: `${a}%` }} />}
          {b !== undefined && <span className="db-dot on" style={{ left: `${b}%` }} />}
        </span>
        {missingSide && !missingSide.measured ? (
          <span className="db-delta na" title={missingSide.reason}>
            {missingSide.state}
          </span>
        ) : (
          <span
            className={
              r.delta === undefined || r.delta === 0
                ? "db-delta"
                : r.delta > 0
                  ? "db-delta pos"
                  : "db-delta neg"
            }
          >
            {r.delta === undefined ? "—" : signed(r.delta)}
          </span>
        )}
      </li>
    );
  };

  return (
    <Panel
      title="Rerank lift"
      drill={{ suite: "retrieval", label: "per-question retrieval ranks" }}
      onDrill={onDrill}
      notMeasured={missing}
    >
      <ul className="dumbbell">
        {shown.map(row)}
        {rest.length > 0 && (
          <li className="db-more">
            <details>
              <summary>{rest.length} more metrics</summary>
              <ul className="dumbbell">{rest.map(row)}</ul>
            </details>
          </li>
        )}
      </ul>
      <div className="db-axis">
        <span>{min.toFixed(3)}</span>
        <span className="db-legend">
          <i className="db-dot off" /> rerank off
          {hasOn && (
            <>
              <i className="db-dot on" /> rerank on
            </>
          )}
        </span>
        <span>{max.toFixed(3)}</span>
      </div>
      <p className="hint">
        {!hasOn ? (
          "This run has no rerank-on figures, so there is no lift; the dots are the rerank-off values."
        ) : best && best.delta !== undefined ? (
          <>
            Axis is scaled to the data, not to 0–1, so the lift is the visible quantity.
            Largest movement: <b>{best.name}</b> {signed(best.delta)}.
          </>
        ) : (
          "No metric has both sides measured, so there is no lift to show."
        )}
      </p>
    </Panel>
  );
}

// --------------------------------------------------------------- faithfulness

export function Faithfulness({ results, onDrill }: PanelProps) {
  const rows = faithfulness(results);
  if (rows.length === 0) return null;
  const judge = judgeGap(results);
  return (
    <Panel
      title="Answer faithfulness"
      drill={{ suite: "faithfulness", label: "judged answers" }}
      onDrill={onDrill}
      notMeasured={rows.flatMap((r) => unmeasured(r.name, r.reading))}
    >
      <ul className="bars">
        {rows.map((r) => (
          <li key={r.name}>
            <span className="bar-label">
              {r.name}
              {r.direction === "down" && <i className="dir" title="lower is better">↓</i>}
            </span>
            <span className="bar-track">
              {r.reading.measured ? (
                <span
                  className={r.direction === "down" ? "bar-fill warn" : "bar-fill"}
                  style={{ width: `${r.reading.value * 100}%` }}
                />
              ) : (
                <StateInTrack reading={r.reading} />
              )}
            </span>
            <span className="bar-value">{barValue(r.reading, 3)}</span>
          </li>
        ))}
      </ul>
      {judge !== undefined && judge.gap > 0.2 && (
        <p className="callout">
          <b>The judge is the bottleneck.</b> {(judge.accuracy * 100).toFixed(0)}% of answers
          contain the gold answer string, but the configured judge scores only{" "}
          {(judge.grounded * 100).toFixed(0)}% as grounded — a {judge.gap.toFixed(2)} gap.
          Judge quality is a config choice (<code>suites.faithfulness.judge</code>), not a
          property of the pipeline under test.
        </p>
      )}
    </Panel>
  );
}

// --------------------------------------------------- security / privacy panels

/** Rates measured once per defense, each read against the no-defense baseline.
 *  Colour encodes direction of change, not defense identity: a defense whose arm
 *  sits above the baseline is the row worth reading first. Direction, not verdict —
 *  the panel has no significance test, so it shows the movement and leaves the
 *  causal claim to the paired comparison. */
function DefenseBars({
  groups,
  suite,
  title,
  lead,
  drill,
  onDrill,
  context = [],
  footer,
  extraUnmeasured = [],
}: {
  groups: DefenseGroup[];
  suite: string;
  title: string;
  lead?: ReactNode;
  drill: Drill;
  onDrill?: (drill: Drill) => void;
  context?: Metric[];
  footer?: ReactNode;
  extraUnmeasured?: Unmeasured[];
}) {
  if (groups.length === 0) return null;
  const missing = [
    ...groups.flatMap((g) =>
      g.bars.flatMap((b) => unmeasured(`${g.metric} [defense=${b.defense}]`, b.reading)),
    ),
    ...unmeasuredOf(context),
    ...extraUnmeasured,
  ];

  return (
    <Panel title={title} drill={drill} onDrill={onDrill} notMeasured={missing}>
      {lead && <p className="lead">{lead}</p>}
      {groups.map((g) => (
        <div className="defense-group" key={g.metric}>
          <h4>{g.metric}</h4>
          {METRIC_GLOSS[g.metric] && <p className="gloss">{METRIC_GLOSS[g.metric]}</p>}
          <ul className="bars">
            {g.bars.map((b) => (
              <li
                key={b.defense}
                className={`${b.isBaseline ? "baseline" : ""}${onDrill ? " clickable" : ""}`}
                onClick={
                  onDrill &&
                  (() =>
                    onDrill({
                      suite,
                      label: `${g.metric} · ${b.defense}`,
                      filter: { defense: b.defense, metric: g.metric },
                    }))
                }
              >
                <span className="bar-label">
                  {b.defense}
                  {b.isBaseline && <i className="tag">baseline</i>}
                </span>
                <span className="bar-track">
                  {b.reading.measured ? (
                    <>
                      <span
                        className={`bar-fill ${b.isBaseline ? "neutral" : b.tone}`}
                        style={{
                          width: `${Math.max(b.reading.value * 100, b.reading.value === 0 ? 0 : 1)}%`,
                        }}
                      />
                      {b.reading.value === 0 && <span className="bar-zero">0.00 ✓</span>}
                    </>
                  ) : (
                    <StateInTrack reading={b.reading} />
                  )}
                </span>
                <span className="bar-value">{barValue(b.reading, 2)}</span>
                <span className={`bar-delta ${b.tone}`}>
                  {b.delta === undefined ? "" : `${b.delta > 0 ? "▲" : b.delta < 0 ? "▼" : ""} ${signed(b.delta, 2)}`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {context.length > 0 && (
        <p className="hint">
          {context.map((m) => `${m.name} ${formatReading(read(m), 2)}`).join(" · ")}
        </p>
      )}
      {footer}
    </Panel>
  );
}

export function AttackSuccess({ results, onDrill }: PanelProps) {
  const groups = defenseGroups(results, "security", {
    except: [...COMPROMISE_METRICS, ...COST_METRICS],
  });
  // Arms scoring above `none`. Deliberately NOT called a backfire: the panel has
  // no significance test to justify that word, and asserting one from a raw delta
  // is the claim this project keeps having to retract. B2 adds the paired test and
  // intervals; until then this surfaces the observation and declines the verdict.
  const higherThanNone = groups
    .flatMap((g) => g.bars.map((b) => ({ ...b, metric: g.metric })))
    .filter((b) => b.delta !== undefined && b.delta > 0);

  return (
    <DefenseBars
      groups={groups}
      context={contextMetrics(results, "security")}
      onDrill={onDrill}
      suite="security"
      title="Attack success by defense"
      lead={
        <>
          Each attack document is planted in the corpus, then every targeted question is
          asked again under each defense. A row is the share of that attack's trials where
          <b> the attack under test</b> worked. Lower is safer; every defense is read
          against <b>none</b>.
        </>
      }
      drill={{ suite: "security", label: "all attacks" }}
      footer={
        higherThanNone.length > 0 ? (
          <p className="callout">
            <b>A defense scored higher than none.</b>{" "}
            {higherThanNone
              .map((b) => `${b.defense} is ${signed(b.delta as number, 2)} on ${b.metric}`)
              .join("; ")}
            .{" "}
            <b>Observed, not established.</b> These arms run over the same targets on the
            same index, so the comparison is paired and a difference this size can be
            noise at these counts — the demo's own 2/10 → 6/10 reaches only <i>p</i> = 0.125.
            Read it as a flag to investigate, not as a defense making attacks worse. Click a
            row to read the trials behind it.
          </p>
        ) : undefined
      }
    />
  );
}

export function PrivacyLeakage({ results, onDrill }: PanelProps) {
  const styles = breakdown(results, "privacy", "leakage_rate");
  return (
    <DefenseBars
      groups={defenseGroups(results, "privacy")}
      onDrill={onDrill}
      extraUnmeasured={unmeasuredOf(styles.map((s) => s.metric))}
      suite="privacy"
      title="Canary leakage by defense"
      lead={
        <>
          Synthetic secrets are seeded into the corpus, then probed for directly and
          indirectly. <code>retrieval_exposure_rate</code> is whether the secret reached the
          prompt at all; <code>leakage_rate</code> is whether it reached the answer.
        </>
      }
      drill={{ suite: "privacy", label: "all canary probes" }}
      footer={
        styles.length > 0 ? (
          <div className="defense-group">
            <h4>leakage by probe style (no redaction)</h4>
            <ul className="bars">
              {styles.map((s) => (
                <li
                  key={String(s.name)}
                  className={onDrill ? "clickable" : ""}
                  onClick={
                    onDrill &&
                    (() =>
                      onDrill({
                        suite: "privacy",
                        label: `${s.name} probes`,
                        filter: { probe_style: String(s.name) },
                      }))
                  }
                >
                  <span className="bar-label">{s.name}</span>
                  <span className="bar-track">
                    {s.reading.measured ? (
                      <>
                        <span
                          className="bar-fill warn"
                          style={{ width: `${s.reading.value * 100}%` }}
                        />
                        {s.reading.value === 0 && <span className="bar-zero">0.00 ✓</span>}
                      </>
                    ) : (
                      <StateInTrack reading={s.reading} />
                    )}
                  </span>
                  <span className="bar-value">{barValue(s.reading, 2)}</span>
                  <span className="bar-delta" />
                </li>
              ))}
            </ul>
          </div>
        ) : undefined
      }
    />
  );
}

/** The rollup the per-attack rates cannot express. One index carries every
 *  attack document, so a trial can be compromised by an attack other than the
 *  one under test — `knowledge_corruption_rate` scores that as a block. */
export function Compromise({ results, onDrill }: PanelProps) {
  const groups = defenseGroups(results, "security", { only: COMPROMISE_METRICS });
  if (groups.length === 0) return null;

  const verdict = contamination(groups);
  const missed = understatements(results);

  return (
    <DefenseBars
      groups={groups}
      onDrill={onDrill}
      suite="security"
      title="Model compromise by defense"
      lead={
        <>
          The panel on the left asks <b>did this attack work?</b> This one asks the broader
          question: <b>did the model produce attacker-controlled text at all?</b>
          <br />
          <br />
          Every attack document lives in one shared index, so a trial can be hijacked by an
          attack other than the one it was set up to measure. When that happens the
          attack-success rate records a block — the marker it was looking for never appeared
          — even though the model was compromised. Each rate below shares a denominator with
          its counterpart on the left, so <b>the gap between the two is exactly what
          per-attack scoring misses</b>.
        </>
      }
      drill={{ suite: "security", label: "all attack trials" }}
      footer={
        <>
          {missed.length > 0 && (
            <div className="callout bad">
              <b>Some defenses look safer than they are.</b> These rates report a block
              while the model still emitted attacker text on the same trial:
              <ul className="understated">
                {missed.map((m) => (
                  <li key={`${m.success}|${m.defense}`}>
                    <code>{m.success}</code> under <b>{m.defense}</b> reads{" "}
                    {m.hit.toFixed(2)} — model actually compromised on{" "}
                    <b>{m.anyMarker.toFixed(2)}</b> of those trials
                  </li>
                ))}
              </ul>
              Click any row to read the trials and see which attack produced each answer.
            </div>
          )}
          {verdict?.kind === "escaping" && (
            <p className="callout bad">
              <b>Attack documents are escaping their target question.</b>{" "}
              {verdict.arms
                .map((b) => `${b.defense} ${(b.value * 100).toFixed(0)}%`)
                .join(", ")}{" "}
              of trials answered with a marker planted on a <i>different</i> question. That
              is a retrieval failure worth investigating on its own.
            </p>
          )}
          {verdict?.kind === "contained" && (
              <p className="callout">
                <b>No cross-question contamination.</b> Every compromised-but-blocked trial
                was beaten by the other attack on its <i>own</i> question — the poison and
                injection target lists overlap, so both documents echo that question and
                compete for the same retrieval slots. Nothing escaped the question it was
                written for.
              </p>
          )}
        </>
      }
    />
  );
}

/** What the defenses cost. A defense that refuses everything blocks every
 *  attack, so an attack-reduction number is only readable next to this. */
export function DefenseCost({ results, onDrill }: PanelProps) {
  const groups = defenseGroups(results, "security", { only: COST_METRICS });
  if (groups.length === 0) return null;

  const accuracy = groups.find((g) => g.metric === "clean_answer_accuracy");
  const worst = accuracy?.bars
    .filter((b) => b.delta !== undefined && b.delta < 0)
    .sort((a, b) => (a.delta ?? 0) - (b.delta ?? 0))[0];

  return (
    <DefenseBars
      groups={groups}
      onDrill={onDrill}
      suite="security"
      title="What the defenses cost"
      lead={
        <>
          Every defense is also checked against <b>clean corpus chunks</b> and
          <b> unattacked questions</b>. A defense that deletes or refuses enough normal
          traffic will drive attack success to zero without defending anything, so these
          are the numbers that decide whether an attack reduction is real.
        </>
      }
      drill={{ suite: "security", label: "clean-traffic control" }}
      footer={
        worst ? (
          <p className="callout bad">
            <b>{worst.defense} is not free.</b> It costs{" "}
            {Math.abs(worst.delta as number).toFixed(2)} of answer accuracy on questions
            nobody attacked — read its attack-success row against that, not on its own.
          </p>
        ) : undefined
      }
    />
  );
}

// -------------------------------------------------------------------- latency

export function Latency({ results }: PanelProps) {
  const rows = latency(results);
  if (rows.length === 0) return null;
  const scale = Math.max(...rows.map((r) => r.p95));
  const total = rows.reduce((sum, r) => sum + r.p50, 0);

  return (
    <Panel title="Per-stage latency">
      <ul className="bars latency">
        {rows.map((r) => (
          <li key={r.name} title={`p50 ${r.p50.toFixed(1)}ms · p95 ${r.p95.toFixed(1)}ms`}>
            <span className="bar-label">{r.name}</span>
            <span className="bar-track">
              <span className="bar-fill p95" style={{ width: `${(r.p95 / scale) * 100}%` }} />
              <span className="bar-fill p50" style={{ width: `${(r.p50 / scale) * 100}%` }} />
            </span>
            <span className="bar-value">{fmtMs(r.p50)}</span>
            <span className="bar-delta muted">{(r.share * 100).toFixed(0)}%</span>
          </li>
        ))}
      </ul>
      <div className="db-axis">
        <span className="db-legend">
          <i className="swatch p50" /> p50
          <i className="swatch p95" /> p95
        </span>
        <span>{fmtMs(total)} total p50</span>
      </div>
      <p className="hint">
        Linear axis, share of total p50 on the right — {rows[0].name} is{" "}
        {(rows[0].share * 100).toFixed(0)}% of end-to-end latency.
      </p>
    </Panel>
  );
}

function fmtMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
  if (ms >= 10) return `${ms.toFixed(0)}ms`;
  return `${ms.toFixed(1)}ms`;
}
