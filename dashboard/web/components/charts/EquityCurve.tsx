"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Legend,
} from "recharts";
import type { EquityPoint } from "@/types";

interface EquityCurveProps {
  agentA: EquityPoint[];
  agentB: EquityPoint[];
}

function formatAxisDate(timestamp: string): string {
  const d = new Date(timestamp);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

interface TooltipPayloadItem {
  value: number;
  name: string;
  color: string;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-lg border border-border-primary bg-bg-card p-3 shadow-lg min-w-[140px]">
      {label && (
        <p className="text-xs text-text-muted mb-2">
          {new Date(label).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
            year: "numeric",
          })}
        </p>
      )}
      {payload.map((item) => (
        <div key={item.name} className="flex items-center justify-between gap-4">
          <span className="text-xs font-medium" style={{ color: item.color }}>
            {item.name}
          </span>
          <span className="font-mono-nums text-xs font-semibold text-text-primary">
            ${item.value.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
          </span>
        </div>
      ))}
    </div>
  );
}

function BotStat({ label, points, color }: { label: string; points: EquityPoint[]; color: string }) {
  const start = 100_000;
  const last = points.length > 0 ? points[points.length - 1].equity : start;
  const delta = last - start;
  const deltaPct = (delta / start) * 100;
  const isPos = delta >= 0;

  return (
    <div className="flex items-center gap-3">
      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
      <div>
        <p className="text-xs text-text-muted uppercase tracking-wider">{label}</p>
        <div className="flex items-baseline gap-2 mt-0.5">
          <span className="font-mono-nums text-lg font-semibold text-text-primary">
            ${Math.round(last).toLocaleString("en-US")}
          </span>
          <span className={`font-mono-nums text-xs font-medium ${isPos ? "text-profit-green" : "text-loss-red"}`}>
            {isPos ? "+" : ""}{deltaPct.toFixed(2)}%
          </span>
        </div>
      </div>
    </div>
  );
}

/**
 * Merge two equity series by timestamp into a recharts-compatible dataset.
 * Each point has { timestamp, a?, b? } where a/b are equity values.
 */
function mergeSeries(aPoints: EquityPoint[], bPoints: EquityPoint[]) {
  const map = new Map<string, { timestamp: string; a?: number; b?: number }>();

  for (const p of aPoints) {
    map.set(p.timestamp, { timestamp: p.timestamp, a: p.equity });
  }
  for (const p of bPoints) {
    const existing = map.get(p.timestamp);
    if (existing) {
      existing.b = p.equity;
    } else {
      map.set(p.timestamp, { timestamp: p.timestamp, b: p.equity });
    }
  }

  return Array.from(map.values()).sort((x, y) =>
    x.timestamp < y.timestamp ? -1 : x.timestamp > y.timestamp ? 1 : 0
  );
}

export default function EquityCurve({ agentA, agentB }: EquityCurveProps) {
  const data = mergeSeries(agentA, agentB);
  const hasData = agentA.length > 1 || agentB.length > 1;

  return (
    <div className="rounded-lg border border-border-primary bg-bg-card p-4">
      {/* Header with per-bot stats */}
      <div className="flex flex-wrap items-start justify-between gap-4 mb-5">
        <h3 className="text-sm font-medium text-text-secondary self-center">Equity Curve</h3>
        <div className="flex flex-wrap gap-6">
          <BotStat label="Agent A" points={agentA} color="#60a5fa" />
          <BotStat label="Agent B" points={agentB} color="#f59e0b" />
        </div>
      </div>

      {!hasData ? (
        <div className="flex items-center justify-center h-56 text-sm text-text-muted">
          No closed trades yet. Equity will appear here once trades close.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <XAxis
              dataKey="timestamp"
              tickFormatter={formatAxisDate}
              axisLine={false}
              tickLine={false}
              tick={{ fill: "#64748b", fontSize: 11 }}
              dy={8}
            />
            <YAxis
              tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
              axisLine={false}
              tickLine={false}
              tick={{ fill: "#64748b", fontSize: 11 }}
              dx={-4}
              width={52}
            />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine
              y={100_000}
              stroke="#64748b"
              strokeDasharray="3 3"
              strokeOpacity={0.4}
            />
            <Line
              type="monotone"
              dataKey="a"
              name="Agent A"
              stroke="#60a5fa"
              strokeWidth={2}
              dot={false}
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="b"
              name="Agent B"
              stroke="#f59e0b"
              strokeWidth={2}
              dot={false}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
