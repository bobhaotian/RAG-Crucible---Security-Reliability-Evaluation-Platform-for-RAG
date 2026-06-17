// Typed client for the crucible API (mirrors crucible.runner.models /
// api.schemas). The dashboard is read-only: it lists runs and reads results.

export type RunStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface RunRow {
  id: string;
  name: string;
  spec_hash: string;
  status: RunStatus;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Metric {
  suite: string;
  name: string;
  variant: string;
  value: number;
}

export interface SuiteSummary {
  suite: string;
  status: string;
  error: string | null;
  metric_count: number;
  record_count: number;
}

export interface StageStat {
  stage: string;
  count: number;
  mean_ms: number;
  p50_ms: number;
  p95_ms: number;
}

export interface RunResults {
  run: RunRow;
  suites: SuiteSummary[];
  metrics: Metric[];
  stage_stats: StageStat[];
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return (await res.json()) as T;
}

export const listRuns = () => getJSON<RunRow[]>("/runs");
export const getResults = (id: string) =>
  getJSON<RunResults>(`/runs/${id}/results`);
