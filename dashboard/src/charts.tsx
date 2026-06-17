// Thin Recharts wrappers over the shapes from metrics.ts. Each returns null
// when there's nothing to plot, so views compose suites that may be absent.

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { RunResults } from "./api";
import {
  attackSuccess,
  latency,
  privacyLeakage,
  rerankLift,
  tradeoffRadar,
} from "./metrics";

const COLORS = ["#6c5ce7", "#00b894", "#e17055", "#0984e3", "#fdcb6e"];

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="panel">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

export function TradeoffRadar({ results }: { results: RunResults }) {
  const data = tradeoffRadar(results);
  if (data.length < 3) return null;
  return (
    <Panel title="Quality · robustness · privacy trade-off">
      <ResponsiveContainer width="100%" height={280}>
        <RadarChart data={data} outerRadius="70%">
          <PolarGrid />
          <PolarAngleAxis dataKey="name" />
          <PolarRadiusAxis domain={[0, 1]} tick={false} />
          <Radar dataKey="value" stroke={COLORS[0]} fill={COLORS[0]} fillOpacity={0.5} />
          <Tooltip />
        </RadarChart>
      </ResponsiveContainer>
      <p className="hint">Each axis 0–1, higher is safer (robustness/privacy inverted).</p>
    </Panel>
  );
}

export function RerankLift({ results }: { results: RunResults }) {
  const data = rerankLift(results);
  if (data.length === 0) return null;
  return (
    <Panel title="Rerank lift">
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="name" angle={-30} textAnchor="end" height={60} />
          <YAxis domain={[0, 1]} />
          <Tooltip />
          <Legend />
          <Bar dataKey="off" name="rerank off" fill={COLORS[3]} />
          <Bar dataKey="on" name="rerank on" fill={COLORS[1]} />
        </BarChart>
      </ResponsiveContainer>
    </Panel>
  );
}

export function AttackSuccess({ results }: { results: RunResults }) {
  const { defenses, rows } = attackSuccess(results);
  if (rows.length === 0) return null;
  return (
    <Panel title="Attack success by defense">
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={rows}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="name" angle={-15} textAnchor="end" height={50} />
          <YAxis domain={[0, 1]} />
          <Tooltip />
          <Legend />
          {defenses.map((d, i) => (
            <Bar key={d} dataKey={d} fill={COLORS[i % COLORS.length]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
      <p className="hint">Lower is safer. Compare the no-defense bar against each defense.</p>
    </Panel>
  );
}

export function PrivacyLeakage({ results }: { results: RunResults }) {
  const data = privacyLeakage(results);
  if (data.length === 0) return null;
  return (
    <Panel title="Canary leakage (exposure vs leakage)">
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="name" />
          <YAxis domain={[0, 1]} />
          <Tooltip />
          <Legend />
          <Bar dataKey="retrieval exposure" fill={COLORS[3]} />
          <Bar dataKey="generation leakage" fill={COLORS[2]} />
        </BarChart>
      </ResponsiveContainer>
    </Panel>
  );
}

export function Latency({ results }: { results: RunResults }) {
  const data = latency(results);
  if (data.length === 0) return null;
  return (
    <Panel title="Per-stage latency (ms)">
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="name" />
          <YAxis scale="log" domain={[0.1, "auto"]} allowDataOverflow />
          <Tooltip />
          <Legend />
          <Bar dataKey="p50" fill={COLORS[0]} />
          <Bar dataKey="p95" fill={COLORS[4]} />
        </BarChart>
      </ResponsiveContainer>
    </Panel>
  );
}
