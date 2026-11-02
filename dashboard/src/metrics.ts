// Derive chart-ready shapes from a run's flat metric list. Every selector
// tolerates missing suites, so partial runs still render.
//
// A metric reaches a panel in one of three conditions, and they are never
// merged: measured (a number, which may be a true zero), emitted but not
// measured (a state and a reason, value null), or absent (the run did not emit
// it). A null is never drawn as 0, and a figure derived from two metrics (a
// delta, a worst case, an inverted radar axis) exists only when every input
// was measured.
//
// `inapplicable` and `skipped` follow Lighthouse: they carry no weight. A metric
// that does not apply to this configuration, or that the spec deliberately did
// not run (injection attacks disabled), is set aside where a figure is derived
// from several metrics or one stands in for another (see `firstApplicable`,
// `worstOf`), and the figure names what it set aside. When every input is set
// aside, the figure is shown in that state, with its reason, rather than
// vanishing. Any other unmeasured input (`error`, `unsupported`,
// `not_estimable`) leaves the figure unmeasured: it was supposed to count.
//
// A measured value scored over part of its scope (`n_excluded > 0`) carries its
// subset on the reading, so every surface that shows the number can say "53 of
// 56" beside it: a subset score must never pass for a full-set one.

import type {
  Evidence,
  Metric,
  MetricState,
  RunResults,
  RunRow,
  StageStat,
  SuiteSummary,
} from "./api";

const NOT_MEASURED_STATES: readonly string[] = [
  "unsupported",
  "inapplicable",
  "skipped",
  "error",
  "not_estimable",
];

/** Why a metric shows no number. The API's own states, plus two this
 *  dashboard assigns when the API breaks its contract: a state it does not
 *  know (`unrecognised`), or "measured" with no finite number (`invalid`). */
export type DisplayState = Exclude<MetricState, "measured"> | "unrecognised" | "invalid";

export interface NotMeasured {
  measured: false;
  state: DisplayState;
  reason: string;
}

/** A measured value scored over part of its scope: `n` units in the
 *  denominator (undefined when the run did not record it) and `excluded` left
 *  out as not eligible, always at least 1. */
export interface Subset {
  n: number | undefined;
  excluded: number;
}

export type Reading = { measured: true; value: number; subset?: Subset } | NotMeasured;

/** A count from the API: a non-negative integer, or undefined for null, a
 *  missing key (an older server) or anything else. */
function count(v: unknown): number | undefined {
  return typeof v === "number" && Number.isInteger(v) && v >= 0 ? v : undefined;
}

/** The subset a metric was scored over, or undefined when nothing was excluded
 *  or the run did not record exclusions. */
function subsetOf(m: Metric): Subset | undefined {
  const excluded = count(m.n_excluded);
  if (excluded === undefined || excluded === 0) return undefined;
  return { n: count(m.n), excluded };
}

/** A metric's value, or why it has none. */
export function read(m: Metric): Reading {
  // A missing state is an API from before states existed, when every metric was measured.
  const state: string = m.state ?? "measured";
  const given = m.reason?.trim() ? m.reason : undefined;
  if (state === "measured") {
    if (typeof m.value === "number" && Number.isFinite(m.value)) {
      const subset = subsetOf(m);
      return subset ? { measured: true, value: m.value, subset } : { measured: true, value: m.value };
    }
    return { measured: false, state: "invalid", reason: "marked measured, but carries no number" };
  }
  if (NOT_MEASURED_STATES.includes(state)) {
    return {
      measured: false,
      state: state as Exclude<MetricState, "measured">,
      reason: given ?? "no reason given",
    };
  }
  return {
    measured: false,
    state: "unrecognised",
    reason: `unrecognised state "${state}"${given ? `: ${given}` : ""}`,
  };
}

/** States that carry no weight in a derived figure: the metric does not apply
 *  to this configuration, or the spec chose not to run it. */
const NO_WEIGHT: readonly string[] = ["inapplicable", "skipped"];

/** Whether a reading is set aside, rather than counted, in a derived figure. */
export function carriesNoWeight(r: Reading | undefined): boolean {
  return r !== undefined && !r.measured && NO_WEIGHT.includes(r.state);
}

/** `undefined` for a metric that is absent, inapplicable or skipped: none of
 *  them may stand in for another metric or take part in a worst case. */
export function applicable(r: Reading | undefined): Reading | undefined {
  return carriesNoWeight(r) ? undefined : r;
}

/** A fallback chain: the first candidate that applies, or, when none does, the
 *  first that exists, so a figure whose every input is set aside is shown in
 *  that state instead of disappearing. */
export function firstApplicable(...candidates: (Reading | undefined)[]): Reading | undefined {
  return (
    candidates.find((r) => applicable(r) !== undefined) ?? candidates.find((r) => r !== undefined)
  );
}

/** Plain text inside markdown: one line, with the characters that would turn it
 *  into emphasis, code, a link, an entity or raw HTML escaped, as summary.md
 *  does, plus `|`, which would end a table cell. */
export function plainMarkdown(text: string): string {
  return text
    .trim()
    .split(/\s+/)
    .join(" ")
    .replace(/([\\`*_[\]<>~&|])/g, "\\$1");
}

function find(results: RunResults, suite: string, name: string, variant: string) {
  return results.metrics.find(
    (m) => m.suite === suite && m.name === name && m.variant === variant,
  );
}

/** The metric's reading, or `undefined` when the run did not emit it. */
export function reading(
  results: RunResults,
  suite: string,
  name: string,
  variant = "",
): Reading | undefined {
  const m = find(results, suite, name, variant);
  return m === undefined ? undefined : read(m);
}

/** The value of a measured metric. `undefined` both when the metric is absent
 *  and when it was not measured, so use it only to compute something that needs
 *  a number; to show a metric, use `reading`. */
export function measured(
  results: RunResults,
  suite: string,
  name: string,
  variant = "",
): number | undefined {
  const r = reading(results, suite, name, variant);
  return r?.measured ? r.value : undefined;
}

/** `0.123`, or `— (unsupported)` for a metric that was not measured. */
export function formatReading(r: Reading | undefined, digits = 3): string {
  if (r === undefined) return "—";
  return r.measured ? r.value.toFixed(digits) : `— (${r.state})`;
}

// --------------------------------------------------------------------- counts

/** Metrics that count things rather than rate them. A count is never drawn as
 *  a 0–1 bar, is written as an integer, and a change in it is neither good nor
 *  bad: more canaries dropped by the ingest filters is the user's own hygiene,
 *  not a regression. */
export const COUNT_METRICS: ReadonlySet<string> = new Set(["canary_docs_dropped_by_filter"]);

/** Whether a metric is a count. A cut of a count (`name@style`) is one too. */
export function isCount(name: string): boolean {
  return COUNT_METRICS.has(name.split("@")[0]);
}

/** A metric's value as text: an integer for a count, `digits` places for a
 *  rate, `— (<state>)` when it was not measured. */
export function formatMetric(m: Metric, digits = 3): string {
  const r = read(m);
  return isCount(m.name) && r.measured ? r.value.toFixed(0) : formatReading(r, digits);
}

// -------------------------------------------------------------------- subsets

/** `53 of 56`, or `3 excluded` when the run did not record the denominator. */
export function subsetShort(s: Subset): string {
  return s.n === undefined ? `${s.excluded} excluded` : `${s.n} of ${s.n + s.excluded}`;
}

/** One entry in a panel's "scored over a subset" list. */
export interface Subsetted {
  label: string;
  subset: Subset;
}

export interface SubsetGroup {
  n: number | undefined;
  excluded: number;
  labels: string[];
}

export function subsetted(label: string, r: Reading | undefined): Subsetted[] {
  return r?.measured && r.subset ? [{ label, subset: r.subset }] : [];
}

/** The measured metrics in a list that were scored over a subset, labelled. */
export function subsettedOf(metrics: Metric[]): Subsetted[] {
  return metrics.flatMap((m) => subsetted(labelOf(m), read(m)));
}

/** One line per distinct (n, excluded), as the "Not measured" list groups by
 *  state and reason: a suite scored over one subset is one line. */
export function groupSubsets(items: Subsetted[]): SubsetGroup[] {
  const groups = new Map<string, SubsetGroup>();
  for (const { label, subset } of items) {
    const key = `${subset.n ?? "?"}\u0000${subset.excluded}`;
    const group = groups.get(key) ?? { n: subset.n, excluded: subset.excluded, labels: [] };
    if (!group.labels.includes(label)) group.labels.push(label);
    groups.set(key, group);
  }
  return [...groups.values()];
}

/** `scored over 53 of 56; 3 excluded`, the text after a group's labels, as
 *  summary.md words it. */
export function subsetLine(g: { n: number | undefined; excluded: number }): string {
  return g.n === undefined
    ? `${g.excluded} excluded; denominator not recorded`
    : `scored over ${g.n} of ${g.n + g.excluded}; ${g.excluded} excluded`;
}

/** The "53 of 56" a track shows at its end, or nothing for a full-set value. */
export function subsetTag(r: Reading | undefined): string | undefined {
  return r?.measured && r.subset ? subsetShort(r.subset) : undefined;
}

/** One block of a panel's footnotes, in the order they are shown: what was
 *  scored over a subset, then what was not measured. A block with no lines is
 *  left out, so a fully measured, full-set panel has no footnotes. */
export interface Footnote {
  kind: "subset" | "not-measured";
  heading: string;
  lines: { key: string; labels: string[]; state: DisplayState | undefined; text: string }[];
}

export function panelFootnotes(notMeasured: Unmeasured[], subsets: Subsetted[]): Footnote[] {
  const blocks: Footnote[] = [
    {
      kind: "subset",
      heading: "Scored over a subset",
      lines: groupSubsets(subsets).map((g) => ({
        key: `${g.n ?? "?"}|${g.excluded}`,
        labels: g.labels,
        state: undefined,
        text: `— ${subsetLine(g)}`,
      })),
    },
    {
      kind: "not-measured",
      heading: "Not measured",
      lines: groupUnmeasured(notMeasured).map((g) => ({
        key: `${g.state}|${g.reason}`,
        labels: g.labels,
        state: g.state,
        text: g.reason,
      })),
    },
  ];
  return blocks.filter((b) => b.lines.length > 0);
}

/** One entry in a panel's "not measured" list. */
export interface Unmeasured extends NotMeasured {
  label: string;
}

export interface UnmeasuredGroup {
  state: DisplayState;
  reason: string;
  labels: string[];
}

/** One line per distinct state and reason, as in summary.md: a suite that is
 *  unsupported as a whole is one line, not one per metric. */
export function groupUnmeasured(items: Unmeasured[]): UnmeasuredGroup[] {
  const groups = new Map<string, UnmeasuredGroup>();
  for (const u of items) {
    const key = `${u.state}\u0000${u.reason}`;
    const group = groups.get(key) ?? { state: u.state, reason: u.reason, labels: [] };
    if (!group.labels.includes(u.label)) group.labels.push(u.label);
    groups.set(key, group);
  }
  return [...groups.values()];
}

export function unmeasured(label: string, r: Reading | undefined): Unmeasured[] {
  return r !== undefined && !r.measured ? [{ ...r, label }] : [];
}

function labelOf(m: Metric): string {
  return m.variant ? `${m.name} [${m.variant}]` : m.name;
}

/** The not-measured metrics in a list, labelled for a panel footnote. */
export function unmeasuredOf(metrics: Metric[]): Unmeasured[] {
  return metrics.flatMap((m) => unmeasured(labelOf(m), read(m)));
}

/** The larger of several rates, defined only when all of them were measured:
 *  a worst case over a set with an unknown member is itself unknown. Inputs
 *  the run did not emit, or that carry no weight (inapplicable, skipped), are
 *  left out; when every input present carries none, the worst case takes the
 *  first one's state, and its reason names each. */
export function worstOf(parts: [string, Reading | undefined][]): Reading | undefined {
  const emitted = parts.filter((p): p is [string, Reading] => p[1] !== undefined);
  if (emitted.length === 0) return undefined;
  const present = emitted.filter(([, r]) => applicable(r) !== undefined);
  if (present.length === 0) {
    const aside = emitted.map(([name, r]) => [name, r as NotMeasured] as const);
    const oneState = aside.every(([, r]) => r.state === aside[0][1].state);
    const reasons = aside.map(([name, r]) =>
      oneState ? `${name}: ${r.reason}` : `${name}: ${r.state}, ${r.reason}`,
    );
    return { measured: false, state: aside[0][1].state, reason: reasons.join("; ") };
  }
  // The worst case is one of its inputs, so it keeps that input's subset.
  let worst: Extract<Reading, { measured: true }> | undefined;
  for (const [name, r] of present) {
    if (!r.measured) return { ...r, reason: `${name}: ${r.reason}` };
    if (worst === undefined || r.value > worst.value) worst = r;
  }
  return worst as Reading;
}

/** The inputs a derived figure set aside, by name and state. */
export function setAside(parts: [string, Reading | undefined][]): [string, DisplayState][] {
  return parts.flatMap(([name, r]) =>
    r !== undefined && !r.measured && carriesNoWeight(r) ? [[name, r.state] as [string, DisplayState]] : [],
  );
}

/** The two attack rates a worst case is taken over, by their short names. */
function attackParts(results: RunResults): [string, Reading | undefined][] {
  return [
    ["poison", reading(results, "security", "knowledge_corruption_rate", "defense=none")],
    ["injection", reading(results, "security", "injection_compliance_rate", "defense=none")],
  ];
}

/** What a worst case was taken over: "poison vs injection", or, when inputs
 *  were set aside or absent, the ones that counted and then what was set
 *  aside, e.g. "poison only; injection skipped". `qualifier` follows the
 *  counted part ("poison only, no defense; injection skipped"). */
export function worstCaseScope(parts: [string, Reading | undefined][], qualifier = ""): string {
  const counted = parts.filter(([, r]) => r !== undefined && applicable(r) !== undefined);
  const names = (ps: [string, unknown][]) => ps.map(([name]) => name).join(" vs ");
  if (counted.length === parts.length || counted.length === 0) return `${names(parts)}${qualifier}`;
  const aside = setAside(parts).map(([name, state]) => `${name} ${state}`);
  return `${names(counted)} only${qualifier}${aside.length > 0 ? `; ${aside.join(", ")}` : ""}`;
}

function invert(r: Reading | undefined): Reading | undefined {
  return r?.measured ? { ...r, value: 1 - r.value } : r;
}

export interface NamedSeries {
  name: string;
  [series: string]: number | string;
}

// ---------------------------------------------------------------- KPI header

export type Direction = "up" | "down";

export interface Kpi {
  key: string;
  label: string;
  detail: string;
  reading: Reading;
  direction: Direction; // which way is better
  suite: string; // which evidence the card drills into
}

/** The four properties in tension, each in its natural direction — no inverted
 *  axes to explain. The radar keeps the inverted framing for shape only. */
export function kpis(results: RunResults): Kpi[] {
  // Falls back to rerank off only when the run has no rerank-on figure, or one
  // that is inapplicable (no reranker); one that was not measured for any other
  // reason is shown as such, not swapped out.
  const on = reading(results, "retrieval", "ndcg@10", "rerank=on");
  const off = reading(results, "retrieval", "ndcg@10", "rerank=off");
  const retrieval = firstApplicable(on, off);
  const parts = attackParts(results);
  const attack = worstOf(parts.map(([name, r]) => [ATTACK_RATE[name], r]));

  const cards: (Omit<Kpi, "reading"> & { reading: Reading | undefined })[] = [
    {
      key: "retrieval",
      label: "Retrieval quality",
      detail: withSubset(
        retrieval !== undefined && retrieval === off ? "nDCG@10, rerank off" : "nDCG@10, rerank on",
        retrieval,
      ),
      reading: retrieval,
      direction: "up",
      suite: "retrieval",
    },
    {
      key: "faithfulness",
      label: "Answer accuracy",
      detail: withSubset("gold answer present", reading(results, "faithfulness", "answer_accuracy")),
      reading: reading(results, "faithfulness", "answer_accuracy"),
      direction: "up",
      suite: "faithfulness",
    },
    {
      key: "security",
      label: "Worst-case attack",
      detail: withSubset(
        attack?.measured ? worstCaseScope(parts, ", no defense") : "poison vs injection, no defense",
        attack,
      ),
      reading: attack,
      direction: "down",
      suite: "security",
    },
    {
      key: "privacy",
      label: "Canary leakage",
      // The `none` arm, not "no defense": with `pii` in the ingest filters the
      // canaries were redacted before any arm ran.
      detail: withSubset("none arm", reading(results, "privacy", "leakage_rate", "defense=none")),
      reading: reading(results, "privacy", "leakage_rate", "defense=none"),
      direction: "down",
      suite: "privacy",
    },
  ];
  // A card the run has no metric for is dropped; one it could not measure stays, with its reason.
  return cards.flatMap((k) => (k.reading === undefined ? [] : [{ ...k, reading: k.reading }]));
}

/** The metric behind each attack's short name. */
const ATTACK_RATE: Record<string, string> = {
  poison: "knowledge_corruption_rate",
  injection: "injection_compliance_rate",
};

function withSubset(detail: string, r: Reading | undefined): string {
  return r?.measured && r.subset ? `${detail} · ${subsetShort(r.subset)}` : detail;
}

// One headline number per property, 0..1, higher = better. Robustness and
// privacy are inverted (1 − attack success / leakage) so the radar reads
// "bigger is safer" on every axis.
// An axis that was not measured is left off the radar and listed instead:
// plotted as 0 it would read as the worst score, and inverted it would read as
// a perfect one.
export interface Radar {
  data: NamedSeries[];
  unmeasured: Unmeasured[];
  subsets: Subsetted[];
  notes: string[]; // what a measured axis set aside, e.g. "Robustness: poison only; injection skipped"
}

export function tradeoffRadar(results: RunResults): Radar {
  const retrieval = firstApplicable(
    reading(results, "retrieval", "ndcg@10", "rerank=on"),
    reading(results, "retrieval", "ndcg@10", "rerank=off"),
    reading(results, "retrieval", "mrr", "rerank=off"),
  );
  const faithfulness = reading(results, "faithfulness", "groundedness");
  const parts = attackParts(results);
  const robustness = invert(worstOf(parts.map(([name, r]) => [ATTACK_RATE[name], r])));
  const privacy = invert(reading(results, "privacy", "leakage_rate", "defense=none"));

  const axes: [string, Reading | undefined][] = [
    ["Retrieval", retrieval],
    ["Faithfulness", faithfulness],
    ["Robustness", robustness],
    ["Privacy", privacy],
  ];
  return {
    data: axes.flatMap(([name, r]) =>
      r?.measured ? [{ name, value: Number(r.value.toFixed(3)) }] : [],
    ),
    unmeasured: axes.flatMap(([name, r]) => unmeasured(name, r)),
    subsets: axes.flatMap(([name, r]) => subsetted(name, r)),
    notes:
      robustness?.measured && setAside(parts).length > 0
        ? [`Robustness: ${worstCaseScope(parts)}`]
        : [],
  };
}

// --------------------------------------------------------------- rerank lift

export interface LiftRow {
  name: string;
  off: Reading;
  on: Reading | undefined; // undefined: the run has no rerank-on figure for it
  delta: number | undefined; // only when both sides were measured
  headline: boolean;
}

export interface LiftChart {
  rows: LiftRow[];
  axis: { min: number; max: number } | undefined; // undefined: nothing measured to place
  hasOn: boolean; // false: the run has no rerank-on figures, so there is no lift
  unmeasured: Unmeasured[];
  subsets: Subsetted[];
}

// The metrics worth showing before the reader asks for all of them.
const HEADLINE_RETRIEVAL = ["recall@1", "recall@5", "ndcg@10", "mrr"];

/** Rerank off vs on as a dumbbell: the axis is scaled to the data, not to
 *  [0,1], because the quantity of interest (the lift) is often a rounding
 *  error against a full 0–1 axis and disappears entirely. */
export function rerankLift(results: RunResults): LiftChart {
  const retrieval = results.metrics.filter((m) => m.suite === "retrieval");
  const off = retrieval.filter((m) => m.variant === "rerank=off");
  if (off.length === 0) {
    return { rows: [], axis: undefined, hasOn: false, unmeasured: [], subsets: [] };
  }
  const on = new Map(
    retrieval.filter((m) => m.variant === "rerank=on").map((m) => [m.name, read(m)]),
  );

  // A missing rerank-on figure is not a lift of zero: the row keeps its single
  // dot and no delta, rather than borrowing the off value for both sides.
  const rows: LiftRow[] = off
    .map((m) => {
      const offR = read(m);
      const onR = on.get(m.name);
      const delta = offR.measured && onR?.measured ? onR.value - offR.value : undefined;
      return {
        name: m.name,
        off: offR,
        on: onR,
        delta,
        headline: HEADLINE_RETRIEVAL.includes(m.name),
      };
    })
    .sort((a, b) => {
      if (a.headline !== b.headline) return a.headline ? -1 : 1;
      // rows with no lift sort last, not as the largest movement
      const size = (r: LiftRow) => (r.delta === undefined ? -1 : Math.abs(r.delta));
      return size(b) - size(a);
    });

  const values = rows.flatMap((r) =>
    [r.off, r.on].flatMap((x) => (x?.measured ? [x.value] : [])),
  );
  const ranked = retrieval.filter((m) => m.variant === "rerank=off" || m.variant === "rerank=on");
  const unmeasuredRows = unmeasuredOf(ranked);
  const subsets = subsettedOf(ranked);
  // A rerank-on figure that does not apply (no reranker) or was not run is not
  // one to draw a lift against, so the legend and the hint say there is none.
  const hasOn = [...on.values()].some((r) => applicable(r) !== undefined);
  if (values.length === 0) {
    return { rows, axis: undefined, hasOn, unmeasured: unmeasuredRows, subsets };
  }
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  // Pad so the dots never sit on the panel edge, and so a run where every
  // metric is identical still renders a sane track instead of dividing by zero.
  const pad = Math.max((hi - lo) * 0.25, 0.01);
  return {
    rows,
    axis: { min: Math.max(0, lo - pad), max: Math.min(1, hi + pad) },
    hasOn,
    unmeasured: unmeasuredRows,
    subsets,
  };
}

// --------------------------------------------------------------- suite panels

export interface FaithfulnessRow {
  name: string;
  reading: Reading;
  direction: Direction;
}

const FAITHFULNESS_ROWS = [
  "answer_accuracy",
  "groundedness",
  "hallucination_rate",
  "citation_parse_rate",
  "citation_precision",
];

export function faithfulness(results: RunResults): FaithfulnessRow[] {
  return FAITHFULNESS_ROWS.flatMap((name) => {
    const r = reading(results, "faithfulness", name);
    const direction: Direction = betterOf(name) === "lower" ? "down" : "up";
    return r === undefined ? [] : [{ name, reading: r, direction }];
  });
}

/** The gap the platform exists to surface: a deterministic accuracy check and
 *  an LLM judge disagreeing about the same answers means the judge, not the
 *  pipeline, is the binding constraint. */
export interface JudgeGap {
  accuracy: number;
  grounded: number;
  gap: number;
}

/** A measured faithfulness figure with its denominator, or undefined. */
function sample(
  results: RunResults,
  name: string,
): { value: number; subset?: Subset; n?: number } | undefined {
  const m = find(results, "faithfulness", name, "");
  const r = m === undefined ? undefined : read(m);
  return r?.measured ? { value: r.value, subset: r.subset, n: count(m?.n) } : undefined;
}

/** The gap between the two, only when they were scored over the same answers:
 *  both measured, neither over a subset, and the same denominator (or, from an
 *  older run, none recorded on either). A difference of two rates over
 *  different answers is not a gap in anything. */
export function judgeGap(results: RunResults): JudgeGap | undefined {
  const accuracy = sample(results, "answer_accuracy");
  const grounded = sample(results, "groundedness");
  if (accuracy === undefined || grounded === undefined) return undefined;
  if (accuracy.subset || grounded.subset || accuracy.n !== grounded.n) return undefined;
  return { accuracy: accuracy.value, grounded: grounded.value, gap: accuracy.value - grounded.value };
}

/** What the faithfulness panel says about answer accuracy against the judge:
 *  the bottleneck callout when they are comparable and far apart; both
 *  figures, each with its denominator and nothing subtracted, when they were
 *  scored over different answers; otherwise nothing. Text marks code with
 *  backticks. */
export type JudgeNote =
  | { kind: "bottleneck"; lead: string; text: string }
  | { kind: "unlike"; lead: string; text: string };

export function judgeNote(results: RunResults): JudgeNote | undefined {
  const gap = judgeGap(results);
  if (gap !== undefined) {
    if (gap.gap <= 0.2) return undefined;
    return {
      kind: "bottleneck",
      lead: "The judge is the bottleneck.",
      text:
        `${(gap.accuracy * 100).toFixed(0)}% of answers contain the gold answer string, but the ` +
        `configured judge scores only ${(gap.grounded * 100).toFixed(0)}% as grounded — a ` +
        `${gap.gap.toFixed(2)} gap. Judge quality is a config choice (\`suites.faithfulness.judge\`), ` +
        "not a property of the pipeline under test.",
    };
  }
  const accuracy = sample(results, "answer_accuracy");
  const grounded = sample(results, "groundedness");
  if (accuracy === undefined || grounded === undefined) return undefined;
  const over = (x: { value: number; subset?: Subset; n?: number }) =>
    `${x.value.toFixed(2)} (${
      x.subset ? subsetShort(x.subset) : x.n !== undefined ? `${x.n} of ${x.n}` : "denominator not recorded"
    })`;
  return {
    kind: "unlike",
    lead: "Scored over different answers.",
    text:
      `\`answer_accuracy\` ${over(accuracy)} and \`groundedness\` ${over(grounded)} ` +
      "count different answers, so no gap between them is computed.",
  };
}

export type Tone = "neutral" | "good" | "bad";

export interface DefenseBar {
  defense: string;
  reading: Reading;
  delta: number | undefined; // vs the no-defense baseline, only when both were measured
  isBaseline: boolean;
  tone: Tone;
}

/** The bars that carry a number, with it. */
export function measuredBars(bars: DefenseBar[]): (DefenseBar & { value: number })[] {
  return bars.flatMap((b) => (b.reading.measured ? [{ ...b, value: b.reading.value }] : []));
}

export interface DefenseGroup {
  metric: string;
  bars: DefenseBar[];
}

const BASELINE = "none";

/** Suite-level rollups: "was the model compromised at all?", as opposed to the
 *  per-attack rates that ask "did *this* attack work?". Shown in their own
 *  panel, so the per-attack panel filters them out. */
/** What a defense costs, as opposed to what it prevents. These share the
 *  `defense=` variant shape with the attack rates but are not attack rates, so
 *  they get their own panel — and `clean_answer_accuracy` is the one metric in
 *  this family where a *rise* is the good direction. */
export const COST_METRICS = [
  "defense_clean_screen_rate",
  "attack_abstention_rate",
  "clean_abstention_rate",
  "clean_answer_accuracy",
];

/** Which way is better for each metric, as `rag_crucible/eval/catalog.py`
 *  defines it (rendered in docs/metrics.md, which npm test checks this table
 *  against). `neither` metrics are read for what they are, never coloured as a
 *  gain or a loss: an abstention defeats the attack and the question alike. */
export type Better = "higher" | "lower" | "neither";

const BETTER: [RegExp, Better][] = [
  [/^(recall|ndcg)@[^@]+$/, "higher"],
  [/^mrr$/, "higher"],
  [/^(groundedness|citation_parse_rate|answer_accuracy|citation_precision)$/, "higher"],
  [/^injection_screened_rate@[^@]+$/, "higher"],
  [/^clean_answer_accuracy$/, "higher"],
  [/^(attack_abstention_rate|attack_competition_rate)$/, "neither"],
  [/^canary_docs_dropped_by_filter$/, "neither"],
];

/** Better is lower for every other metric: attack success, compromise,
 *  exposure, leakage, hallucination and the costs of a defense. */
export function betterOf(name: string): Better {
  return BETTER.find(([pattern]) => pattern.test(name))?.[1] ?? "lower";
}

export const COMPROMISE_METRICS = [
  "poison_compromise_rate",
  "injection_compromise_rate",
  "attack_competition_rate",
  "cross_question_contamination_rate",
];

/** Plain-English gloss per metric, rendered beside the name. A reader who has
 *  never seen this project should be able to read a panel without the docs. */
export const METRIC_GLOSS: Record<string, string> = {
  knowledge_corruption_rate:
    "Poison trials where the answer repeated the false value planted for that question.",
  injection_compliance_rate:
    "Injection trials where the answer contained the token the injected instruction demanded.",
  poison_compromise_rate:
    "Poison trials where the answer contained any attacker-planted text — the poison under test, or another attack in the index.",
  injection_compromise_rate:
    "Injection trials where the answer contained any attacker-planted text — the injection under test, or another attack in the index.",
  attack_competition_rate:
    "Trials answered with a marker from the other attack targeting the same question. Expected where the poison and injection target lists overlap.",
  cross_question_contamination_rate:
    "Trials answered with a marker from an attack planted on a different question — an attack document escaping its target.",
  defense_clean_screen_rate:
    "Clean corpus chunks the defense would remove even though no attack was present. This is the retrieval-side false-positive cost.",
  attack_abstention_rate:
    "Attack trials where the defense refused to answer rather than risk the planted content.",
  clean_abstention_rate:
    "Unattacked questions the defense refused to answer. This is the false-positive cost — a defense that refuses everything blocks every attack.",
  clean_answer_accuracy:
    "Unattacked questions still answered correctly with the defense on. Higher is better; the drop from `none` is the utility the defense costs.",
  leakage_rate: "Probes where the answer text contained the seeded canary value.",
  retrieval_exposure_rate:
    "Probes where the chunk holding the canary reached the prompt context at all.",
  canary_docs_dropped_by_filter:
    "Canary documents the ingest filters removed before indexing; not probed, and outside every rate.",
};

/** Each compromise rate and the per-attack rate it generalises. They share a
 *  denominator, so the difference is the share of trials the per-attack rate
 *  scores as blocked while the model still emitted attacker-controlled text. */
export const COMPROMISE_PAIRS: [compromise: string, success: string][] = [
  ["poison_compromise_rate", "knowledge_corruption_rate"],
  ["injection_compromise_rate", "injection_compliance_rate"],
];

export interface Understatement {
  defense: string;
  success: string;
  hit: number;
  anyMarker: number;
}

/** Where a per-attack rate understates how often the model was compromised. */
export function understatements(results: RunResults): Understatement[] {
  const value = (name: string, defense: string) =>
    measured(results, "security", name, `defense=${defense}`);
  const defenses = unique(
    results.metrics
      .filter((m) => m.suite === "security" && m.variant.startsWith("defense="))
      .map((m) => m.variant.replace("defense=", "")),
  );
  return COMPROMISE_PAIRS.flatMap(([compromise, success]) =>
    defenses.flatMap((defense) => {
      const anyMarker = value(compromise, defense);
      const hit = value(success, defense);
      return anyMarker !== undefined && hit !== undefined && anyMarker > hit
        ? [{ defense, success, hit, anyMarker }]
        : [];
    }),
  );
}

/** Metrics measured once per defense condition, grouped so each defense is
 *  read against the baseline it is supposed to improve on. Both suites that
 *  use this shape (security, privacy) are lower-is-better. */
export function defenseGroups(
  results: RunResults,
  suite: string,
  opts: { only?: string[]; except?: string[] } = {},
): DefenseGroup[] {
  // A count is never a bar on a 0–1 track.
  const scoped = results.metrics.filter(
    (m) =>
      m.suite === suite &&
      m.variant.startsWith("defense=") &&
      !isCount(m.name) &&
      (opts.only ? opts.only.includes(m.name) : true) &&
      (opts.except ? !opts.except.includes(m.name) : true),
  );
  const defenseOf = (m: Metric) => m.variant.replace("defense=", "");
  const defenses = unique(scoped.map(defenseOf)).sort((a, b) =>
    a === BASELINE ? -1 : b === BASELINE ? 1 : a.localeCompare(b),
  );

  // `only` doubles as the display order; otherwise fall back to encounter order.
  const names = unique(scoped.map((m) => m.name));
  const ordered = opts.only ? opts.only.filter((n) => names.includes(n)) : names;

  return ordered.map((name) => {
    const readingFor = (d: string) => {
      const m = scoped.find((x) => x.name === name && defenseOf(x) === d);
      return m === undefined ? undefined : read(m);
    };
    const baseline = readingFor(BASELINE);
    const bars = defenses.flatMap((defense) => {
      const r = readingFor(defense);
      if (r === undefined) return [];
      const isBaseline = defense === BASELINE;
      const delta =
        isBaseline || !baseline?.measured || !r.measured ? undefined : r.value - baseline.value;
      const better = betterOf(name);
      const improved = better === "higher" ? delta !== undefined && delta > 0 : delta !== undefined && delta < 0;
      const tone: Tone =
        delta === undefined || delta === 0 || better === "neither" ? "neutral" : improved ? "good" : "bad";
      return [{ defense, reading: r, delta, isBaseline, tone }];
    });
    return { metric: name, bars };
  });
}

export type Contamination =
  | { kind: "escaping"; arms: { defense: string; value: number }[] }
  | { kind: "contained" };

/** What the compromise panel may say about attacks escaping their question.
 *
 *  "Escaping" needs one measured arm above zero. "Contained" (nothing escaped)
 *  is a claim about every arm, so it needs `cross_question_contamination_rate`
 *  present and measured in every defense the panel shows, and some measured
 *  competition to explain. Anything less says nothing: an unmeasured rate is
 *  not evidence that nothing escaped. */
export function contamination(groups: DefenseGroup[]): Contamination | undefined {
  const positive = (name: string) =>
    measuredBars(groups.find((g) => g.metric === name)?.bars ?? []).filter((b) => b.value > 0);
  const escaping = positive("cross_question_contamination_rate");
  if (escaping.length > 0) {
    return { kind: "escaping", arms: escaping.map((b) => ({ defense: b.defense, value: b.value })) };
  }
  const cross = groups.find((g) => g.metric === "cross_question_contamination_rate");
  if (cross === undefined) return undefined;
  const defenses = new Set(groups.flatMap((g) => g.bars.map((b) => b.defense)));
  const everyArmMeasured =
    [...defenses].every((d) => cross.bars.some((b) => b.defense === d)) &&
    cross.bars.every((b) => b.reading.measured);
  if (!everyArmMeasured) return undefined;
  return positive("attack_competition_rate").length > 0 ? { kind: "contained" } : undefined;
}

/** Why a delta compares unlike samples: the two runs scored the metric over a
 *  different number of units (`n`), or over the same number but a different
 *  set, judged by what each excluded (`set`). Set only when both runs measured
 *  the metric, so every flag has a delta to mark. */
export type Unlike = "n" | "set";

export interface DiffRow {
  key: string;
  a: Reading | undefined;
  b: Reading | undefined;
  delta: number | undefined; // only when both runs measured the metric
  count: boolean; // a count: written as an integer, and a change is neither good nor bad
  n: [number | undefined, number | undefined]; // each run's denominator, when recorded
  unlike: Unlike | undefined;
}

/** The two-run comparison, one row per metric either run emitted. */
export function diffRows(base: RunResults, other: RunResults): DiffRow[] {
  const keyOf = (m: Metric) => `${m.suite} · ${summaryMetric(m)}`;
  const rows = new Map<string, { name: string; a?: Metric; b?: Metric }>();
  for (const m of base.metrics) rows.set(keyOf(m), { name: m.name, a: m });
  for (const m of other.metrics) {
    rows.set(keyOf(m), { ...(rows.get(keyOf(m)) ?? { name: m.name }), b: m });
  }
  return [...rows.entries()].map(([key, { name, a: ma, b: mb }]) => {
    const a = ma === undefined ? undefined : read(ma);
    const b = mb === undefined ? undefined : read(mb);
    const n: [number | undefined, number | undefined] = [count(ma?.n), count(mb?.n)];
    const both = a?.measured === true && b?.measured === true;
    let unlike: Unlike | undefined;
    if (both && n[0] !== undefined && n[1] !== undefined && n[0] !== n[1]) {
      unlike = "n";
    } else if (both && (a.subset || b.subset)) {
      // A subset on either side, and the two sides did not exclude the same
      // number from the same denominator (or one did not record it): the
      // runs were scored over different sets.
      const ex: [number | undefined, number | undefined] = [count(ma?.n_excluded), count(mb?.n_excluded)];
      if (n[0] === undefined || n[1] === undefined || ex[0] !== ex[1]) unlike = "set";
    }
    return {
      key,
      a,
      b,
      delta: both ? (b as { value: number }).value - (a as { value: number }).value : undefined,
      count: isCount(name),
      n,
      unlike,
    };
  });
}

/** A compare-view cell: the value (an integer for a count, with "53 of 56"
 *  when scored over a subset), `— (<state>)`, or `—` when the run did not
 *  emit the metric. */
export function diffCell(r: Reading | undefined, isCountMetric: boolean): string {
  if (!r?.measured) return formatReading(r, 4);
  const value = r.value.toFixed(isCountMetric ? 0 : 4);
  return r.subset ? `${value} (${subsetShort(r.subset)})` : value;
}

export interface DiffDelta {
  text: string;
  tone: "" | "pos" | "neg"; // a count's change, or no change, has no tone
  mark: "≠n" | "≠set" | undefined;
  title: string | undefined;
}

/** A compare-view delta: only when both runs measured the metric, flagged
 *  when it compares unlike samples. */
export function diffDelta(row: DiffRow): DiffDelta {
  const { delta, count: isCountMetric, unlike, n } = row;
  if (delta === undefined) return { text: "—", tone: "", mark: undefined, title: undefined };
  return {
    text: (delta > 0 ? "+" : "") + delta.toFixed(isCountMetric ? 0 : 4),
    tone: isCountMetric || delta === 0 ? "" : delta > 0 ? "pos" : "neg",
    mark: unlike === "n" ? "≠n" : unlike === "set" ? "≠set" : undefined,
    title:
      unlike === "n"
        ? `n differs: ${n[0]} vs ${n[1]}, so this is not like-for-like`
        : unlike === "set"
          ? "scored over different sets of units in each run, so this is not like-for-like"
          : undefined,
  };
}

/** The note under the compare table, counting exactly the marks drawn. */
export function diffFootnote(rows: DiffRow[]): string | undefined {
  const marks = rows.map((r) => diffDelta(r).mark);
  const byN = marks.filter((m) => m === "≠n").length;
  const bySet = marks.filter((m) => m === "≠set").length;
  const metrics = (k: number) => `${k} ${k === 1 ? "metric" : "metrics"}`;
  const parts = [
    byN > 0 ? `≠n marks ${metrics(byN)} scored over a different number of units in each run` : "",
    bySet > 0 ? `≠set marks ${metrics(bySet)} scored over different sets of units` : "",
  ].filter(Boolean);
  return parts.length > 0 ? `${parts.join("; ")}, so their deltas compare unlike samples.` : undefined;
}

/** Suite metrics with no defense variant — the stage-level context that frames
 *  the defended numbers (e.g. attack chunks reached the context every time). */
export function contextMetrics(results: RunResults, suite: string): Metric[] {
  return results.metrics.filter(
    (m) => m.suite === suite && m.variant === "" && !m.name.includes("@"),
  );
}

export interface BreakdownRow {
  name: string;
  metric: Metric;
  reading: Reading;
}

/** `leakage_rate@direct` style metrics: the same rate cut by probe style. */
export function breakdown(results: RunResults, suite: string, name: string): BreakdownRow[] {
  return results.metrics
    .filter(
      (m) =>
        m.suite === suite && m.name.startsWith(`${name}@`) && m.variant === "" && !isCount(m.name),
    )
    .map((m) => ({ name: m.name.split("@")[1], metric: m, reading: read(m) }));
}

/** The privacy suite's baseline: its first configured condition, which the
 *  probe-style breakdown is measured on. "none" when the spec is unavailable,
 *  which is the default first condition. */
export function privacyBaseline(spec: Record<string, unknown> | null): string {
  const suites = spec?.suites;
  const privacy =
    suites && typeof suites === "object" ? (suites as Record<string, unknown>).privacy : undefined;
  const defenses =
    privacy && typeof privacy === "object" ? (privacy as Record<string, unknown>).defenses : undefined;
  const first = Array.isArray(defenses) ? defenses[0] : undefined;
  return typeof first === "string" && first ? first : "none";
}

/** The heading over the probe-style breakdown. It names the arm it was
 *  measured on rather than claiming there was no redaction: with `pii` in the
 *  ingest filters even the baseline arm was redacted. */
export function probeStyleHeading(baseline: string): string {
  return `leakage by probe style (${baseline} arm)`;
}

/** What the privacy panel says around its bars. Text marks code with backticks. */
export interface PrivacyContext {
  heading: string; // over the probe-style breakdown
  caveat: string | undefined; // when the run's own `pii` filter redacted every canary
  counts: string[]; // one line per count metric, e.g. the canaries the filters dropped
}

export function privacyContext(
  results: RunResults,
  spec: Record<string, unknown> | null,
): PrivacyContext {
  const baseline = privacyBaseline(spec);
  const counts = contextMetrics(results, "privacy")
    .filter((m) => isCount(m.name))
    .map(
      (m) =>
        `\`${m.name}\` ${formatMetric(m)}${METRIC_GLOSS[m.name] ? ` — ${METRIC_GLOSS[m.name]}` : ""}`,
    );
  return {
    heading: probeStyleHeading(baseline),
    caveat: canariesRedactedAtIngest(results, spec)
      ? `\`pii\` is in this run's ingest filters, so the canaries were redacted at ingestion in ` +
        `every arm: \`${baseline}\` is not defense-free here, and \`pii_filter\` finds nothing left to redact.`
      : undefined,
    counts,
  };
}

/** Text with `code` spans, split for rendering: odd pieces are code. */
export function codeSpans(text: string): { code: boolean; text: string }[] {
  return text.split("`").map((piece, i) => ({ code: i % 2 === 1, text: piece }));
}

/** Whether this run's own `pii` ingest filter redacted the canaries, as
 *  summary.md decides it: only code that routes canaries through the filters
 *  emits the drop count, so an older run whose spec lists `pii` is not claimed
 *  as redacted. */
export function canariesRedactedAtIngest(
  results: RunResults,
  spec: Record<string, unknown> | null,
): boolean {
  const routed = results.metrics.some(
    (m) => m.suite === "privacy" && m.name === "canary_docs_dropped_by_filter",
  );
  const ingest = spec?.ingest;
  const filters =
    ingest && typeof ingest === "object" ? (ingest as Record<string, unknown>).filters : undefined;
  return routed && Array.isArray(filters) && filters.includes("pii");
}

// --------------------------------------------------------------- suite status

export interface SuiteNotice {
  suite: string;
  status: "failed" | "skipped";
  error: string | undefined; // the suite's recorded error, when there is one
  reasons: UnmeasuredGroup[]; // why its metrics have no value, grouped
  /** The text the notice shows besides its grouped reasons, if any. */
  message: string | undefined;
}

/** The suites a reader has to be told about before reading any panel: one that
 *  failed (its panels are empty because it produced nothing) and one that was
 *  skipped (its metrics carry the reason). A succeeded suite, or a status this
 *  dashboard does not know, gets no notice. */
export function suiteNotices(results: RunResults): SuiteNotice[] {
  return results.suites.flatMap((s) => {
    if (s.status !== "failed" && s.status !== "skipped") return [];
    const reasons = groupUnmeasured(unmeasuredOf(results.metrics.filter((m) => m.suite === s.suite)));
    const error = s.error?.trim() ? s.error : undefined;
    return [{ suite: s.suite, status: s.status, error, reasons, message: noticeMessage(s.status, error, reasons) }];
  });
}

function noticeMessage(
  status: "failed" | "skipped",
  error: string | undefined,
  reasons: UnmeasuredGroup[],
): string | undefined {
  if (status === "failed") {
    return `${error ?? "The run recorded no error message."} Its panels are empty because the suite produced no results.`;
  }
  // A skipped suite gives its reasons on its metrics. One written by an older
  // version has none, and put its reason in `error` instead
  // ("unsupported: retrieval labels missing for q001, …").
  if (reasons.length > 0) return undefined;
  return error ?? "No reason was recorded.";
}

/** The run header's suite list: a suite that did not succeed says so. */
export function suitesLine(suites: SuiteSummary[]): string {
  return suites.map((s) => (s.status === "succeeded" ? s.suite : `${s.suite} (${s.status})`)).join(" · ");
}

// -------------------------------------------------------------------- latency

export interface LatencyRow {
  name: string;
  p50: number;
  p95: number;
  share: number; // fraction of total p50 across stages
}

export function latency(results: RunResults): LatencyRow[] {
  const total = results.stage_stats.reduce((sum: number, s: StageStat) => sum + s.p50_ms, 0);
  return results.stage_stats
    .map((s) => ({
      name: s.stage,
      p50: s.p50_ms,
      p95: s.p95_ms,
      share: total > 0 ? s.p50_ms / total : 0,
    }))
    .sort((a, b) => b.p50 - a.p50);
}

// ------------------------------------------------------------------- run meta

export function duration(run: RunRow): string | undefined {
  if (!run.started_at || !run.finished_at) return undefined;
  const ms = Date.parse(run.finished_at) - Date.parse(run.started_at);
  if (!Number.isFinite(ms) || ms < 0) return undefined;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
}

/** Model + corpus chips pulled out of the spec the run executed from. Every
 *  lookup is defensive: specs evolve and the dashboard should not break on a
 *  field it has not seen. */
export function pipelineChips(spec: Record<string, unknown> | null): [string, string][] {
  if (!spec) return [];
  const at = (...path: string[]): unknown =>
    path.reduce<unknown>(
      (node, key) =>
        node && typeof node === "object" ? (node as Record<string, unknown>)[key] : undefined,
      spec,
    );
  const str = (v: unknown): string | undefined =>
    typeof v === "string" ? v : typeof v === "number" ? String(v) : undefined;
  const model = (stage: string): string | undefined => {
    const name = str(at("pipeline", stage, "model"));
    return name ? name.split("/").pop() : str(at("pipeline", stage, "provider"));
  };

  const rerankerEnabled = at("pipeline", "reranker", "enabled") !== false;
  const chips: ([string, string | undefined])[] = [
    ["embedder", model("embedder")],
    ["reranker", rerankerEnabled ? model("reranker") : "off"],
    ["generator", model("generator")],
    ["index", str(at("index", "store"))],
    ["top-k", str(at("pipeline", "retriever", "k"))],
    ["seed", str(at("seed"))],
  ];
  return chips.flatMap(([k, v]) => (v ? [[k, v] as [string, string]] : []));
}

// ------------------------------------------------------------------ evidence
//
// The receipts behind a number: which records a drill shows. Kept here, beside
// the metrics, so the rules are tested rather than buried in a component.

/** An attacker-planted string with the attack that planted it. */
export interface Marker {
  marker: string;
  attack_type: string;
  qid: string;
}

const field = (r: Evidence, k: string): string | undefined =>
  typeof r[k] === "string" ? (r[k] as string) : undefined;

/** Every planted marker found in this answer, whoever planted it. `null` means
 *  the run never scanned, which is not the same as scanning and finding
 *  nothing. */
export function matchedMarkers(r: Evidence): Marker[] | null {
  const raw = r["matched_markers"];
  return Array.isArray(raw) ? (raw as Marker[]) : null;
}

/** Markers from an attack other than the one this trial was testing. */
export function foreignMarkers(r: Evidence): Marker[] | null {
  const all = matchedMarkers(r);
  if (all === null) return null;
  const own = field(r, "own_marker") ?? "";
  return all.filter((m) => m.marker !== own);
}

/** Foreign markers from the other attack on this same question. An unrecorded
 *  scan yields none: the Python side drops unrecorded trials from these rates,
 *  so a null belongs in neither bucket. */
export function competingMarkers(r: Evidence): Marker[] {
  return (foreignMarkers(r) ?? []).filter((m) => m.qid === field(r, "qid"));
}

/** Foreign markers planted on a different question: real bleed-through. */
export function crossQuestionMarkers(r: Evidence): Marker[] {
  return (foreignMarkers(r) ?? []).filter((m) => m.qid !== field(r, "qid"));
}

/** Which records a suite metric was computed over. */
const METRIC_FILTERS: Record<string, Record<string, string>> = {
  knowledge_corruption_rate: { attack_type: "poison" },
  poison_retrieval_rate: { attack_type: "poison" },
  injection_compliance_rate: { attack_type: "injection" },
  injection_retrieval_rate: { attack_type: "injection" },
  poison_compromise_rate: { attack_type: "poison" },
  injection_compromise_rate: { attack_type: "injection" },
  // The clean-traffic control is a different record kind entirely.
  clean_abstention_rate: { kind: "clean_defense" },
  clean_answer_accuracy: { kind: "clean_defense" },
  attack_abstention_rate: { kind: "attack" },
  // These span both attack types, so they add no attack_type constraint.
  attack_competition_rate: { _competing: "true" },
  cross_question_contamination_rate: { _crossQuestion: "true" },
};

/** A drill's filter with its virtual `metric` field resolved to payload fields. */
export function expandDrillFilter(filter: Record<string, string> | undefined): Record<string, string> {
  if (!filter) return {};
  const { metric, ...fields } = filter;
  return { ...fields, ...(metric ? (METRIC_FILTERS[metric] ?? {}) : {}) };
}

/** Payload fields compare by string equality; keys starting with "_" are
 *  predicates over the record instead. */
function matchesField(r: Evidence, key: string, value: string): boolean {
  if (key === "_competing") return String(competingMarkers(r).length > 0) === value;
  if (key === "_crossQuestion") return String(crossQuestionMarkers(r).length > 0) === value;
  return String(r[key]) === value;
}

/** True for the interesting kind of trial: a successful attack, a leaked
 *  canary, a wrong answer, a gold passage the reranker demoted. */
export function isFlagged(r: Evidence): boolean {
  const bool = (k: string) => (typeof r[k] === "boolean" ? (r[k] as boolean) : undefined);
  const rank = typeof r["first_hit_rank_reranked"] === "number" ? (r["first_hit_rank_reranked"] as number) : 1;
  return (
    bool("succeeded") === true ||
    bool("compromised") === true ||
    bool("leaked") === true ||
    bool("answer_match") === false ||
    rank > 1
  );
}

/** A unit left out of every rate before scoring: a question with no
 *  retrieval label, a canary an ingest filter dropped. Never a trial. */
export function isExcludedItem(r: Evidence): boolean {
  return r["kind"] === "excluded_item";
}

/** "Excluded — q001: no retrieval label". */
export function excludedItemLine(r: Evidence): string {
  const id = field(r, "item_id") ?? "(unnamed)";
  const reason = field(r, "reason") ?? "no reason recorded";
  return `Excluded — ${id}: ${reason}`;
}

export interface EvidenceView {
  trials: Evidence[]; // the scored records the drill matches, most telling first
  excluded: Evidence[]; // excluded items: never matched by a trial filter, never counted as trials
}

/** The records a drill shows. Excluded items are set apart before any trial
 *  filter runs, so a filter that assumes a scored trial never matches one and
 *  they are never counted as trials; the text filter applies to both. */
export function selectEvidence(
  records: Evidence[],
  filter: Record<string, string> | undefined,
  text: string,
): EvidenceView {
  const fields = expandDrillFilter(filter);
  const needle = text.trim().toLowerCase();
  const byText = (r: Evidence) => !needle || JSON.stringify(r).toLowerCase().includes(needle);
  const trials = records
    .filter((r) => !isExcludedItem(r))
    .filter((r) => Object.entries(fields).every(([k, v]) => matchesField(r, k, v)))
    .filter(byText)
    .sort(
      (a, b) =>
        Number((foreignMarkers(b) ?? []).length > 0) - Number((foreignMarkers(a) ?? []).length > 0) ||
        Number(isFlagged(b)) - Number(isFlagged(a)),
    );
  return { trials, excluded: records.filter(isExcludedItem).filter(byText) };
}

/** "12 shown", or "12 shown · 3 excluded". */
export function evidenceCountLine(view: EvidenceView): string {
  return `${view.trials.length} shown${view.excluded.length > 0 ? ` · ${view.excluded.length} excluded` : ""}`;
}

// ------------------------------------------------------------------ markdown

/** The run as a pasteable markdown block — what people put in issues and PRs. */
export function summaryMarkdown(results: RunResults): string {
  const { run, metrics, stage_stats } = results;
  const lines = [
    `# ${run.name}`,
    "",
    `- run id: \`${run.id}\``,
    `- spec hash: \`${run.spec_hash.slice(0, 12)}\``,
    `- status: ${run.status}${duration(run) ? ` (${duration(run)})` : ""}`,
    ...suiteNotices(results).map(
      (n) => `- ${n.suite}: ${n.status}${n.error ? ` (${plainMarkdown(n.error)})` : ""}`,
    ),
    "",
    "| suite | metric | variant | value |",
    "|---|---|---|---|",
  ];
  for (const m of [...metrics].sort(
    (a, b) => a.suite.localeCompare(b.suite) || a.name.localeCompare(b.name),
  )) {
    const r = read(m);
    const cell = r.measured
      ? `${r.value.toFixed(isCount(m.name) ? 0 : 4)}${r.subset ? ` (${subsetShort(r.subset)})` : ""}`
      : `— (${r.state}: ${plainMarkdown(r.reason)})`;
    lines.push(`| ${m.suite} | ${m.name} | ${m.variant || "—"} | ${cell} |`);
  }
  if (stage_stats.length > 0) {
    lines.push("", "| stage | count | p50 ms | p95 ms |", "|---|---|---|---|");
    for (const s of stage_stats) {
      lines.push(
        `| ${s.stage} | ${s.count} | ${s.p50_ms.toFixed(1)} | ${s.p95_ms.toFixed(1)} |`,
      );
    }
  }
  return lines.join("\n");
}

function unique<T>(xs: T[]): T[] {
  return [...new Set(xs)];
}

function summaryMetric(m: Metric): string {
  return m.variant ? `${m.name} (${m.variant})` : m.name;
}

export { summaryMetric };
