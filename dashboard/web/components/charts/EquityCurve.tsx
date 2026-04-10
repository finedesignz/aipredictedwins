"use client";

import { useState, useMemo } from "react";
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
import { useAPI } from "@/hooks/useAPI";
import { useBotFilter } from "@/context/BotFilterContext";

// ── Days selector ─────────────────────────────────────────────────────────────
type DayOption = 7 | 14 | 30 | 60 | 90;
const DAY_OPTIONS: DayOption[] = [7, 14, 30, 60, 90];

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

// ── Props ─────────────────────────────────────────────────────────────────────
interface EquityCurveProps {
  /** Bot equity series from /api/equity — passed in so the parent controls the
   *  ?days= query param via this component's internal state. */
  series: EquitySeries[];
  /** Called when the user changes the day range so the parent can re-fetch equity. */
  days: DayOption;
  onDaysChange: (d: DayOption) => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────
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
      const existing = map.get(p.timestamp) ?? { timestamp: p.timestamp };
      existing[`bot_${s.bot_id}_pct`] = p.return_pct;
      map.set(p.timestamp, existing);
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

// ── Sub-components ────────────────────────────────────────────────────────────
interface TooltipPayloadItem {
  value: number;
  name: string;
  color: string;
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
}) {
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
          <span
            className={`font-mono-nums text-xs font-semibold ${
              item.value >= 0 ? "text-profit-green" : "text-loss-red"
            }`}
          >
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
      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
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

// ── Main component ────────────────────────────────────────────────────────────
export default function EquityCurve({ series, days, onDaysChange }: EquityCurveProps) {
  const { filter, bots, activeBotIds } = useBotFilter();

  // Anchor benchmarks to the bot's first equity point so all lines share origin
  const benchmarkSince = useMemo(() => {
    if (!series.length) return daysAgo(days);
    const dates = series
      .flatMap((s) => s.points)
      .map((p) => p.timestamp.slice(0, 10))
      .filter(Boolean);
    return dates.length ? [...dates].sort()[0] : daysAgo(days);
  }, [series, days]);

  // Benchmark data — fetched here so this component is fully self-contained
  const { data: spyData } = useAPI<BenchmarkPoint[]>(
    `/api/benchmark/spy?since=${benchmarkSince}`,
    300_000
  );
  const { data: btcData } = useAPI<BenchmarkPoint[]>(
    `/api/benchmark/btc?since=${benchmarkSince}`,
    300_000
  );

  const filteredSeries = series.filter((s) => activeBotIds.includes(s.bot_id));
  const showSpy = filter.spy !== false;
  const showBtc = filter.btc !== false;
  const filteredSpy = showSpy ? (spyData ?? []) : [];
  const filteredBtc = showBtc ? (btcData ?? []) : [];

  const data = mergeSeries(filteredSeries, filteredSpy, filteredBtc);
  const hasData = data.length > 1;

  return (
    <div className="rounded-lg border border-border-primary bg-bg-card p-4">
      {/* Header: title + day pills + bot stats */}
      <div className="flex flex-wrap items-start justify-between gap-4 mb-5">
        <div className="flex items-center gap-3 self-center">
          <h3 className="text-sm font-medium text-text-secondary">Equity Curve</h3>
          <div className="flex gap-1" role="group" aria-label="Select time range">
            {DAY_OPTIONS.map((d) => (
              <button
                key={d}
                onClick={() => onDaysChange(d)}
                className={`rounded px-2 py-0.5 text-xs font-medium transition-colors ${
                  days === d
                    ? "bg-accent-blue/20 text-accent-blue"
                    : "text-text-muted hover:text-text-secondary"
                }`}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>
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

      {/* Chart or empty state */}
      {!hasData ? (
        <div className="flex items-center justify-center h-56 text-sm text-text-muted">
          No equity data yet. Chart will populate once trades are placed.
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
            <ReferenceLine y={0} stroke="#64748b" strokeDasharray="3 3" strokeOpacity={0.4} />

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

            {showSpy && filteredSpy.length > 0 && (
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

            {showBtc && filteredBtc.length > 0 && (
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
