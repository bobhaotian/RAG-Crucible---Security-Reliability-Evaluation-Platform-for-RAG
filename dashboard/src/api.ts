// Typed client for the crucible API (mirrors crucible.runner.models /
// api.schemas). The dashboard is read-only: it lists runs, reads results, and
// pulls the per-item evidence behind any metric.

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
  claimed_by: string | null;
  created_at: string;
  started_at: string | null;
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

export interface RecordRow {
  id: number;
  suite: string;
  kind: string;
  payload_json: string;
}

export interface RecordsPage {
  run_id: string;
  suite: string | null;
  offset: number;
  limit: number;
  records: RecordRow[];
}

/** One decoded evidence record: the payload fields plus its store id. */
export type Evidence = Record<string, unknown> & { _id: number };

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return (await res.json()) as T;
}

export const listRuns = () => getJSON<RunRow[]>("/runs");

export const getResults = (id: string) =>
  getJSON<RunResults>(`/runs/${id}/results`);

export const getSpec = (id: string) =>
  getJSON<Record<string, unknown>>(`/runs/${id}/spec`);

/** Evidence for one suite, decoded. The store holds tens-to-hundreds of records
 *  per suite, so a single generous page is simpler than paging in the client. */
export async function getEvidence(id: string, suite: string): Promise<Evidence[]> {
  const page = await getJSON<RecordsPage>(
    `/runs/${id}/records?suite=${encodeURIComponent(suite)}&limit=1000`,
  );
  return page.records.map((r) => ({
    ...(JSON.parse(r.payload_json) as Record<string, unknown>),
    _id: r.id,
  }));
}
