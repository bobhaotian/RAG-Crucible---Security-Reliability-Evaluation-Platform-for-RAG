// Derive chart-ready shapes from a run's flat metric list. Every selector
// tolerates missing suites, so partial runs still render.

import type { Metric, RunResults, RunRow, StageStat } from "./api";

export function metric(
  results: RunResults,
  suite: string,
  name: string,
  variant = "",
): number | undefined {
  return results.metrics.find(
    (m) => m.suite === suite && m.name === name && m.variant === variant,
  )?.value;
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
  value: number | undefined;
  direction: Direction; // which way is better
  suite: string; // which evidence the card drills into
}

/** The four properties in tension, each in its natural direction — no inverted
 *  axes to explain. The radar keeps the inverted framing for shape only. */
export function kpis(results: RunResults): Kpi[] {
  const retrieval =
    metric(results, "retrieval", "ndcg@10", "rerank=on") ??
    metric(results, "retrieval", "ndcg@10", "rerank=off");
  const poison = metric(results, "security", "knowledge_corruption_rate", "defense=none");
  const injection = metric(results, "security", "injection_compliance_rate", "defense=none");
  const attack =
    poison === undefined && injection === undefined
      ? undefined
      : Math.max(poison ?? 0, injection ?? 0);

  const cards: Kpi[] = [
    {
      key: "retrieval",
      label: "Retrieval quality",
      detail: "nDCG@10, rerank on",
      value: retrieval,
      direction: "up",
      suite: "retrieval",
    },
    {
      key: "faithfulness",
      label: "Answer accuracy",
      detail: "gold answer present",
      value: metric(results, "faithfulness", "answer_accuracy"),
      direction: "up",
      suite: "faithfulness",
    },
    {
      key: "security",
      label: "Worst-case attack",
      detail: "poison vs injection, no defense",
      value: attack,
      direction: "down",
      suite: "security",
    },
    {
      key: "privacy",
      label: "Canary leakage",
      detail: "no defense",
      value: metric(results, "privacy", "leakage_rate", "defense=none"),
      direction: "down",
      suite: "privacy",
    },
  ];
  return cards.filter((k) => k.value !== undefined);
}

// One headline number per property, 0..1, higher = better. Robustness and
// privacy are inverted (1 − attack success / leakage) so the radar reads
// "bigger is safer" on every axis.
export function tradeoffRadar(results: RunResults): NamedSeries[] {
  const retrieval =
    metric(results, "retrieval", "ndcg@10", "rerank=on") ??
    metric(results, "retrieval", "ndcg@10", "rerank=off") ??
    metric(results, "retrieval", "mrr", "rerank=off");
  const faithfulness = metric(results, "faithfulness", "groundedness");
  const poison = metric(results, "security", "knowledge_corruption_rate", "defense=none");
  const injection = metric(results, "security", "injection_compliance_rate", "defense=none");
  const robustness =
    poison === undefined && injection === undefined
      ? undefined
      : 1 - Math.max(poison ?? 0, injection ?? 0);
  const leakage = metric(results, "privacy", "leakage_rate", "defense=none");
  const privacy = leakage === undefined ? undefined : 1 - leakage;

  const axes: [string, number | undefined][] = [
    ["Retrieval", retrieval],
    ["Faithfulness", faithfulness],
    ["Robustness", robustness],
    ["Privacy", privacy],
  ];
  return axes
    .filter(([, v]) => v !== undefined)
    .map(([name, v]) => ({ name, value: Number((v as number).toFixed(3)) }));
}

// --------------------------------------------------------------- rerank lift

export interface LiftRow {
  name: string;
  off: number;
  on: number;
  delta: number;
  headline: boolean;
}

export interface LiftChart {
  rows: LiftRow[];
  min: number;
  max: number;
}

// The metrics worth showing before the reader asks for all of them.
const HEADLINE_RETRIEVAL = ["recall@1", "recall@5", "ndcg@10", "mrr"];

/** Rerank off vs on as a dumbbell: the axis is scaled to the data, not to
 *  [0,1], because the quantity of interest (the lift) is often a rounding
 *  error against a full 0–1 axis and disappears entirely. */
export function rerankLift(results: RunResults): LiftChart {
  const off = results.metrics.filter((m) => m.variant === "rerank=off");
  if (off.length === 0) return { rows: [], min: 0, max: 1 };
  const on = new Map(
    results.metrics.filter((m) => m.variant === "rerank=on").map((m) => [m.name, m.value]),
  );

  const rows: LiftRow[] = off
    .map((m) => {
      const onValue = on.get(m.name) ?? m.value;
      return {
        name: m.name,
        off: m.value,
        on: onValue,
        delta: onValue - m.value,
        headline: HEADLINE_RETRIEVAL.includes(m.name),
      };
    })
    .sort((a, b) => {
      if (a.headline !== b.headline) return a.headline ? -1 : 1;
      return Math.abs(b.delta) - Math.abs(a.delta);
    });

  const values = rows.flatMap((r) => [r.off, r.on]);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  // Pad so the dots never sit on the panel edge, and so a run where every
  // metric is identical still renders a sane track instead of dividing by zero.
  const pad = Math.max((hi - lo) * 0.25, 0.01);
  return { rows, min: Math.max(0, lo - pad), max: Math.min(1, hi + pad) };
}

// --------------------------------------------------------------- suite panels

export interface FaithfulnessRow {
  name: string;
  value: number;
  direction: Direction;
}

const FAITHFULNESS_ROWS: [string, Direction][] = [
  ["answer_accuracy", "up"],
  ["groundedness", "up"],
  ["hallucination_rate", "down"],
  ["citation_parse_rate", "up"],
  ["citation_precision", "up"],
];

export function faithfulness(results: RunResults): FaithfulnessRow[] {
  return FAITHFULNESS_ROWS.flatMap(([name, direction]) => {
    const value = metric(results, "faithfulness", name);
    return value === undefined ? [] : [{ name, value, direction }];
  });
}

/** The gap the platform exists to surface: a deterministic accuracy check and
 *  an LLM judge disagreeing about the same answers means the judge, not the
 *  pipeline, is the binding constraint. */
export function judgeGap(results: RunResults): number | undefined {
  const accuracy = metric(results, "faithfulness", "answer_accuracy");
  const grounded = metric(results, "faithfulness", "groundedness");
  if (accuracy === undefined || grounded === undefined) return undefined;
  return accuracy - grounded;
}

export type Tone = "neutral" | "good" | "bad";

export interface DefenseBar {
  defense: string;
  value: number;
  delta: number | undefined; // vs the no-defense baseline
  isBaseline: boolean;
  tone: Tone;
}

export interface DefenseGroup {
  metric: string;
  bars: DefenseBar[];
}

const BASELINE = "none";

/** Suite-level rollups: "was the model compromised at all?", as opposed to the
 *  per-attack rates that ask "did *this* attack work?". Shown in their own
 *  panel, so the per-attack panel filters them out. */
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
  leakage_rate: "Probes where the answer text contained the seeded canary value.",
  retrieval_exposure_rate:
    "Probes where the chunk holding the canary reached the prompt context at all.",
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
    metric(results, "security", name, `defense=${defense}`);
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
  const scoped = results.metrics.filter(
    (m) =>
      m.suite === suite &&
      m.variant.startsWith("defense=") &&
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
    const valueFor = (d: string) =>
      scoped.find((m) => m.name === name && defenseOf(m) === d)?.value;
    const baseline = valueFor(BASELINE);
    const bars = defenses.flatMap((defense) => {
      const value = valueFor(defense);
      if (value === undefined) return [];
      const isBaseline = defense === BASELINE;
      const delta = isBaseline || baseline === undefined ? undefined : value - baseline;
      const tone: Tone =
        delta === undefined || delta === 0 ? "neutral" : delta < 0 ? "good" : "bad";
      return [{ defense, value, delta, isBaseline, tone }];
    });
    return { metric: name, bars };
  });
}

/** Suite metrics with no defense variant — the stage-level context that frames
 *  the defended numbers (e.g. attack chunks reached the context every time). */
export function contextMetrics(results: RunResults, suite: string): Metric[] {
  return results.metrics.filter(
    (m) => m.suite === suite && m.variant === "" && !m.name.includes("@"),
  );
}

/** `leakage_rate@direct` style metrics: the same rate cut by probe style. */
export function breakdown(results: RunResults, suite: string, name: string): NamedSeries[] {
  return results.metrics
    .filter((m) => m.suite === suite && m.name.startsWith(`${name}@`) && m.variant === "")
    .map((m) => ({ name: m.name.split("@")[1], value: m.value }));
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
    "",
    "| suite | metric | variant | value |",
    "|---|---|---|---|",
  ];
  for (const m of [...metrics].sort(
    (a, b) => a.suite.localeCompare(b.suite) || a.name.localeCompare(b.name),
  )) {
    lines.push(`| ${m.suite} | ${m.name} | ${m.variant || "—"} | ${m.value.toFixed(4)} |`);
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
