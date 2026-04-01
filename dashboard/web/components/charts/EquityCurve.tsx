"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import type { EquityPoint } from "@/types";

interface EquityCurveProps {
  data: EquityPoint[];
}

function formatAxisDate(timestamp: string): string {
  const d = new Date(timestamp);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatTooltipValue(value: number): string {
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
}

interface TooltipPayloadItem {
  value: number;
  payload: EquityPoint;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
}

function CustomTooltip({ active, payload }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;

  const point = payload[0];
  return (
    <div className="rounded-lg border border-border-primary bg-bg-card p-3 shadow-lg">
      <p className="text-xs text-text-muted">
        {new Date(point.payload.timestamp).toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
          year: "numeric",
        })}
      </p>
      <p className="font-mono-nums text-sm font-semibold text-text-primary mt-1">
        {formatTooltipValue(point.value)}
      </p>
    </div>
  );
}

export default function EquityCurve({ data }: EquityCurveProps) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 rounded-lg border border-border-primary bg-bg-card">
        <p className="text-sm text-text-muted">
          No equity data available yet. Trades will appear here once the bot places them.
        </p>
      </div>
    );
  }

  const startEquity = data[0]?.equity ?? 0;

  return (
    <div className="rounded-lg border border-border-primary bg-bg-card p-4">
      <h3 className="text-sm font-medium text-text-secondary mb-4">
        Equity Curve
      </h3>
      <ResponsiveContainer width="100%" height={280}>
        <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#4ade80" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#4ade80" stopOpacity={0} />
            </linearGradient>
          </defs>
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
            width={50}
          />
          <Tooltip content={<CustomTooltip />} />
          <ReferenceLine
            y={startEquity}
            stroke="#64748b"
            strokeDasharray="3 3"
            strokeOpacity={0.5}
          />
          <Area
            type="monotone"
            dataKey="equity"
            stroke="#4ade80"
            strokeWidth={2}
            fill="url(#equityGradient)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
