// Derive chart-ready shapes from a run's flat metric list. Every selector
// tolerates missing suites, so partial runs still render.

import type { Metric, RunResults } from "./api";

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

// Retrieval metrics with rerank off vs on (the rerank-lift bars).
export function rerankLift(results: RunResults): NamedSeries[] {
  const off = results.metrics.filter((m) => m.variant === "rerank=off");
  if (off.length === 0) return [];
  const on = new Map(
    results.metrics.filter((m) => m.variant === "rerank=on").map((m) => [m.name, m.value]),
  );
  return off.map((m) => ({
    name: m.name,
    off: Number(m.value.toFixed(4)),
    on: Number((on.get(m.name) ?? m.value).toFixed(4)),
  }));
}

// Attack-success metrics grouped by defense condition.
export function attackSuccess(results: RunResults): {
  defenses: string[];
  rows: NamedSeries[];
} {
  const sec = results.metrics.filter(
    (m) => m.suite === "security" && m.variant.startsWith("defense="),
  );
  const defenses = unique(sec.map((m) => m.variant.replace("defense=", "")));
  const names = unique(sec.map((m) => m.name));
  const rows = names.map((name) => {
    const row: NamedSeries = { name };
    for (const d of defenses) {
      row[d] =
        sec.find((m) => m.name === name && m.variant === `defense=${d}`)?.value ?? 0;
    }
    return row;
  });
  return { defenses, rows };
}

// Privacy leakage decomposition by condition.
export function privacyLeakage(results: RunResults): NamedSeries[] {
  const conditions = unique(
    results.metrics
      .filter((m) => m.suite === "privacy" && m.variant.startsWith("defense="))
      .map((m) => m.variant.replace("defense=", "")),
  );
  return conditions.map((c) => ({
    name: c,
    "retrieval exposure": metric(results, "privacy", "retrieval_exposure_rate", `defense=${c}`) ?? 0,
    "generation leakage": metric(results, "privacy", "leakage_rate", `defense=${c}`) ?? 0,
  }));
}

export function latency(results: RunResults): NamedSeries[] {
  return results.stage_stats.map((s) => ({
    name: s.stage,
    p50: Number(s.p50_ms.toFixed(1)),
    p95: Number(s.p95_ms.toFixed(1)),
  }));
}

function unique<T>(xs: T[]): T[] {
  return [...new Set(xs)];
}

function summaryMetric(m: Metric): string {
  return m.variant ? `${m.name} (${m.variant})` : m.name;
}

export { summaryMetric };
