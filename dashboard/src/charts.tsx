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
import type { DefenseGroup } from "./metrics";
import {
  COMPROMISE_METRICS,
  COST_METRICS,
  METRIC_GLOSS,
  breakdown,
  understatements,
  contextMetrics,
  defenseGroups,
  faithfulness,
  judgeGap,
  latency,
  rerankLift,
  tradeoffRadar,
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
  children,
}: {
  title: string;
  drill?: Drill;
  onDrill?: (drill: Drill) => void;
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
    </section>
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
  const data = tradeoffRadar(results);
  if (data.length < 3) return null;
  return (
    <Panel
      title="Quality · robustness · privacy"
      drill={{ suite: "security", label: "attacks behind the robustness axis" }}
      onDrill={onDrill}
    >
      <ResponsiveContainer width="100%" height={230}>
        <RadarChart data={data} outerRadius="68%" margin={{ top: 16, right: 56, bottom: 8, left: 56 }}>
          <PolarGrid stroke="#2a2e3a" />
          <PolarAngleAxis dataKey="name" tick={{ fill: "#9aa0ad", fontSize: 12 }} />
          <PolarRadiusAxis domain={[0, 1]} tick={false} axisLine={false} />
          <Radar dataKey="value" stroke={ACCENT} fill={ACCENT} fillOpacity={0.45} />
        </RadarChart>
      </ResponsiveContainer>
      <ul className="axis-values">
        {data.map((d) => (
          <li key={String(d.name)}>
            <span>{d.name}</span>
            <b>{Number(d.value).toFixed(3)}</b>
          </li>
        ))}
      </ul>
      <p className="hint">
        Each axis 0–1, bigger is safer. Robustness and privacy are plotted inverted
        (1 − attack success, 1 − leakage); the cards above show them undirected.
      </p>
    </Panel>
  );
}

// ---------------------------------------------------------------- rerank lift

export function RerankLift({ results, onDrill }: PanelProps) {
  const { rows, min, max } = rerankLift(results);
  if (rows.length === 0) return null;
  const shown = rows.filter((r) => r.headline);
  const rest = rows.filter((r) => !r.headline);
  const best = rows.reduce((a, b) => (Math.abs(b.delta) > Math.abs(a.delta) ? b : a));

  const row = (r: (typeof rows)[number]) => {
    const a = pct(r.off, min, max);
    const b = pct(r.on, min, max);
    return (
      <li key={r.name} title={`off ${r.off.toFixed(4)} → on ${r.on.toFixed(4)}`}>
        <span className="db-label">{r.name}</span>
        <span className="db-track">
          <span
            className={r.delta >= 0 ? "db-line pos" : "db-line neg"}
            style={{ left: `${Math.min(a, b)}%`, width: `${Math.abs(b - a)}%` }}
          />
          <span className="db-dot off" style={{ left: `${a}%` }} />
          <span className="db-dot on" style={{ left: `${b}%` }} />
        </span>
        <span className={r.delta > 0 ? "db-delta pos" : r.delta < 0 ? "db-delta neg" : "db-delta"}>
          {signed(r.delta)}
        </span>
      </li>
    );
  };

  return (
    <Panel
      title="Rerank lift"
      drill={{ suite: "retrieval", label: "per-question retrieval ranks" }}
      onDrill={onDrill}
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
          <i className="db-dot on" /> rerank on
        </span>
        <span>{max.toFixed(3)}</span>
      </div>
      <p className="hint">
        Axis is scaled to the data, not to 0–1, so the lift is the visible quantity.
        Largest movement: <b>{best.name}</b> {signed(best.delta)}.
      </p>
    </Panel>
  );
}

// --------------------------------------------------------------- faithfulness

export function Faithfulness({ results, onDrill }: PanelProps) {
  const rows = faithfulness(results);
  if (rows.length === 0) return null;
  const gap = judgeGap(results);
  return (
    <Panel
      title="Answer faithfulness"
      drill={{ suite: "faithfulness", label: "judged answers" }}
      onDrill={onDrill}
    >
      <ul className="bars">
        {rows.map((r) => (
          <li key={r.name}>
            <span className="bar-label">
              {r.name}
              {r.direction === "down" && <i className="dir" title="lower is better">↓</i>}
            </span>
            <span className="bar-track">
              <span
                className={r.direction === "down" ? "bar-fill warn" : "bar-fill"}
                style={{ width: `${r.value * 100}%` }}
              />
            </span>
            <span className="bar-value">{r.value.toFixed(3)}</span>
          </li>
        ))}
      </ul>
      {gap !== undefined && gap > 0.2 && (
        <p className="callout">
          <b>The judge is the bottleneck.</b> {(rows[0].value * 100).toFixed(0)}% of answers
          contain the gold answer string, but the configured judge scores only{" "}
          {((rows[0].value - gap) * 100).toFixed(0)}% as grounded — a {gap.toFixed(2)} gap.
          Judge quality is a config choice (<code>suites.faithfulness.judge</code>), not a
          property of the pipeline under test.
        </p>
      )}
    </Panel>
  );
}

// --------------------------------------------------- security / privacy panels

/** Rates measured once per defense, each read against the no-defense baseline.
 *  Colour encodes direction of change, not defense identity: a defense that
 *  makes things worse is the finding worth seeing first. */
function DefenseBars({
  groups,
  suite,
  title,
  lead,
  drill,
  onDrill,
  context = [],
  footer,
}: {
  groups: DefenseGroup[];
  suite: string;
  title: string;
  lead?: ReactNode;
  drill: Drill;
  onDrill?: (drill: Drill) => void;
  context?: Metric[];
  footer?: ReactNode;
}) {
  if (groups.length === 0) return null;

  return (
    <Panel title={title} drill={drill} onDrill={onDrill}>
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
                  <span
                    className={`bar-fill ${b.isBaseline ? "neutral" : b.tone}`}
                    style={{ width: `${Math.max(b.value * 100, b.value === 0 ? 0 : 1)}%` }}
                  />
                  {b.value === 0 && <span className="bar-zero">0.00 ✓</span>}
                </span>
                <span className="bar-value">{b.value.toFixed(2)}</span>
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
          {context.map((m) => `${m.name} ${m.value.toFixed(2)}`).join(" · ")}
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
  const backfire = groups
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
        backfire.length > 0 ? (
          <p className="callout bad">
            <b>A defense made it worse.</b>{" "}
            {backfire
              .map((b) => `${b.defense} raised ${b.metric} by ${signed(b.delta as number, 2)}`)
              .join("; ")}
            . Lower is safer on every row — click one to read the attacks behind it.
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
                    <span
                      className="bar-fill warn"
                      style={{ width: `${Number(s.value) * 100}%` }}
                    />
                    {Number(s.value) === 0 && <span className="bar-zero">0.00 ✓</span>}
                  </span>
                  <span className="bar-value">{Number(s.value).toFixed(2)}</span>
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

  const rateFor = (name: string) =>
    groups.find((g) => g.metric === name)?.bars.filter((b) => b.value > 0) ?? [];
  const competition = rateFor("attack_competition_rate");
  const crossQuestion = rateFor("cross_question_contamination_rate");
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
          {crossQuestion.length > 0 ? (
            <p className="callout bad">
              <b>Attack documents are escaping their target question.</b>{" "}
              {crossQuestion
                .map((b) => `${b.defense} ${(b.value * 100).toFixed(0)}%`)
                .join(", ")}{" "}
              of trials answered with a marker planted on a <i>different</i> question. That
              is a retrieval failure worth investigating on its own.
            </p>
          ) : (
            competition.length > 0 && (
              <p className="callout">
                <b>No cross-question contamination.</b> Every compromised-but-blocked trial
                was beaten by the other attack on its <i>own</i> question — the poison and
                injection target lists overlap, so both documents echo that question and
                compete for the same retrieval slots. Nothing escaped the question it was
                written for.
              </p>
            )
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
          Every defense is also run on <b>unattacked</b> questions. A defense that refuses
          enough traffic will drive attack success to zero without defending anything, so
          these are the numbers that decide whether an attack reduction is real.
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
