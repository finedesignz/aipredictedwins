"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import type { EquitySeries, BenchmarkPoint } from "@/types";
import { useBotFilter } from "@/context/BotFilterContext";

interface EquityCurveProps {
  series: EquitySeries[];
  spy?: BenchmarkPoint[];
  btc?: BenchmarkPoint[];
}

function formatAxisDate(timestamp: string): string {
  const d = new Date(timestamp);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatPct(v: number): string {
  return (v >= 0 ? "+" : "") + v.toFixed(1) + "%";
}

const BOT_COLORS = ["#60a5fa", "#fbbf24", "#34d399", "#f87171", "#a78bfa", "#fb923c"];

interface MergedPoint {
  timestamp: string;
  spy_pct?: number;
  btc_pct?: number;
  [key: string]: number | string | undefined;
}

function mergeSeries(
  series: EquitySeries[],
  spy: BenchmarkPoint[],
  btc: BenchmarkPoint[]
): MergedPoint[] {
  const map = new Map<string, MergedPoint>();

  for (const s of series) {
    for (const p of s.points) {
      const key = p.timestamp;
      const existing = map.get(key) ?? { timestamp: key };
      existing[`bot_${s.bot_id}_pct`] = p.return_pct;
      map.set(key, existing);
    }
  }

  for (const p of spy) {
    const existing = map.get(p.timestamp) ?? { timestamp: p.timestamp };
    existing.spy_pct = p.return_pct;
    map.set(p.timestamp, existing);
  }

  for (const p of btc) {
    const existing = map.get(p.timestamp) ?? { timestamp: p.timestamp };
    existing.btc_pct = p.return_pct;
    map.set(p.timestamp, existing);
  }

  return Array.from(map.values()).sort((x, y) =>
    x.timestamp < y.timestamp ? -1 : x.timestamp > y.timestamp ? 1 : 0
  );
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
    <div className="rounded-lg border border-border-primary bg-bg-card p-3 shadow-lg min-w-[160px]">
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
          <span className={`font-mono-nums text-xs font-semibold ${item.value >= 0 ? "text-profit-green" : "text-loss-red"}`}>
            {formatPct(item.value)}
          </span>
        </div>
      ))}
    </div>
  );
}

function BotStat({
  label,
  returnPct,
  color,
}: {
  label: string;
  returnPct: number;
  color: string;
}) {
  const isPos = returnPct >= 0;
  return (
    <div className="flex items-center gap-3">
      <span
        className="w-2 h-2 rounded-full flex-shrink-0"
        style={{ background: color }}
      />
      <div>
        <p className="text-xs text-text-muted uppercase tracking-wider">{label}</p>
        <span
          className={`font-mono-nums text-sm font-semibold ${
            isPos ? "text-profit-green" : "text-loss-red"
          }`}
        >
          {formatPct(returnPct)}
        </span>
      </div>
    </div>
  );
}

export default function EquityCurve({ series, spy = [], btc = [] }: EquityCurveProps) {
  const { filter, bots, activeBotIds } = useBotFilter();

  const filteredSeries = series.filter((s) => activeBotIds.includes(s.bot_id));
  const filteredSpy = filter.spy ? spy : [];
  const filteredBtc = (filter.btc ?? false) ? btc : [];

  const data = mergeSeries(filteredSeries, filteredSpy, filteredBtc);
  const hasData = data.length > 1;

  return (
    <div className="rounded-lg border border-border-primary bg-bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-4 mb-5">
        <h3 className="text-sm font-medium text-text-secondary self-center">
          Equity Curve
        </h3>
        <div className="flex flex-wrap gap-6">
          {filteredSeries.map((s, i) => {
            const bot = bots.find((b) => b.bot_id === s.bot_id);
            const label = bot?.label ?? s.bot_id;
            const color = BOT_COLORS[i % BOT_COLORS.length];
            const lastPct = s.points.at(-1)?.return_pct ?? 0;
            return <BotStat key={s.bot_id} label={label} returnPct={lastPct} color={color} />;
          })}
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
              tickFormatter={formatPct}
              axisLine={false}
              tickLine={false}
              tick={{ fill: "#64748b", fontSize: 11 }}
              dx={-4}
              width={56}
            />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine
              y={0}
              stroke="#64748b"
              strokeDasharray="3 3"
              strokeOpacity={0.4}
            />
            {filteredSeries.map((s, i) => {
              const bot = bots.find((b) => b.bot_id === s.bot_id);
              const label = bot?.label ?? s.bot_id;
              const color = BOT_COLORS[i % BOT_COLORS.length];
              return (
                <Line
                  key={s.bot_id}
                  type="monotone"
                  dataKey={`bot_${s.bot_id}_pct`}
                  name={label}
                  stroke={color}
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                />
              );
            })}
            {filter.spy && filteredSpy.length > 0 && (
              <Line
                type="monotone"
                dataKey="spy_pct"
                name="S&P 500"
                stroke="#94a3b8"
                strokeWidth={1.5}
                strokeDasharray="5 3"
                dot={false}
                connectNulls
              />
            )}
            {(filter.btc ?? false) && filteredBtc.length > 0 && (
              <Line
                type="monotone"
                dataKey="btc_pct"
                name="BTC"
                stroke="#fb923c"
                strokeWidth={1.5}
                strokeDasharray="5 3"
                dot={false}
                connectNulls
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
