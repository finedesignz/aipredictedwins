"use client";

import { useMemo } from "react";
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

// ── Props ─────────────────────────────────────────────────────────────────────
interface EquityCurveProps {
  series: EquitySeries[];
  weeks: number;
  onWeeksChange: (w: number) => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function formatPct(v: number): string {
  return (v >= 0 ? "+" : "") + v.toFixed(1) + "%";
}

/** Pick an X-axis tick formatter based on the selected week range. */
function getTickFormatter(weeks: number): (ts: string) => string {
  const days = weeks * 7;
  if (days <= 7) {
    // Hourly: "Mon 9 AM"
    return (ts) =>
      new Date(ts).toLocaleString("en-US", {
        weekday: "short",
        hour: "numeric",
        hour12: true,
      });
  }
  if (days < 30) {
    // Daily: "Apr 12"
    return (ts) =>
      new Date(ts).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }
  if (days < 90) {
    // Weekly: "Apr 7"
    return (ts) =>
      new Date(ts).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }
  // Monthly: "Apr '26"
  return (ts) =>
    new Date(ts).toLocaleDateString("en-US", { month: "short", year: "2-digit" });
}

/**
 * Compute explicit tick timestamps so each period label appears exactly once.
 * - Monthly (>90d): first data point of each calendar month
 * - Weekly  (30-90d): first data point of each calendar week (Sun)
 * - Daily   (7-30d): first data point of each calendar day
 * - Hourly  (≤7d): every 6th hour mark (use interval fallback instead)
 */
function computeTicks(data: MergedPoint[], weeks: number): string[] | undefined {
  if (data.length === 0) return undefined;
  const days = weeks * 7;

  if (days > 90) {
    // One tick per month
    const seen = new Set<string>();
    return data
      .filter((p) => {
        const key = p.timestamp.slice(0, 7); // "2026-03"
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .map((p) => p.timestamp);
  }

  if (days >= 30) {
    // One tick per week — keep first point whose ISO week differs from previous
    const seen = new Set<string>();
    return data
      .filter((p) => {
        const d = new Date(p.timestamp);
        // Sun-anchored week key: "2026-W14"
        const jan1 = new Date(d.getUTCFullYear(), 0, 1);
        const week = Math.ceil(((d.getTime() - jan1.getTime()) / 86400000 + jan1.getUTCDay() + 1) / 7);
        const key = `${d.getUTCFullYear()}-W${week}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .map((p) => p.timestamp);
  }

  if (days >= 7) {
    // One tick per day
    const seen = new Set<string>();
    return data
      .filter((p) => {
        const key = p.timestamp.slice(0, 10);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .map((p) => p.timestamp);
  }

  // Hourly: fall back to interval-based thinning
  return undefined;
}

/** Show time in tooltip only when the timestamp has a non-midnight hour (hourly data). */
function formatTooltipDate(label: string): string {
  const d = new Date(label);
  const hasTime = d.getUTCHours() !== 0 || d.getUTCMinutes() !== 0;
  if (hasTime) {
    return d.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      hour12: true,
    });
  }
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

const BOT_COLORS = ["#60a5fa", "#fbbf24", "#34d399", "#f87171", "#a78bfa", "#fb923c"];

interface MergedPoint {
  timestamp: string;
  spy_pct?: number;
  spy_price?: number;
  btc_pct?: number;
  btc_price?: number;
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
    if (p.price != null) existing.spy_price = p.price;
    map.set(p.timestamp, existing);
  }
  for (const p of btc) {
    const existing = map.get(p.timestamp) ?? { timestamp: p.timestamp };
    existing.btc_pct = p.return_pct;
    if (p.price != null) existing.btc_price = p.price;
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
  dataKey: string;
  payload: MergedPoint;
}

function formatPrice(price: number): string {
  if (price >= 1000) return "$" + price.toLocaleString("en-US", { maximumFractionDigits: 0 });
  return "$" + price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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
        <p className="text-xs text-text-muted mb-2">{formatTooltipDate(label)}</p>
      )}
      {payload.map((item) => {
        const isSpy = item.dataKey === "spy_pct";
        const isBtc = item.dataKey === "btc_pct";
        const price = isSpy ? item.payload.spy_price : isBtc ? item.payload.btc_price : undefined;
        return (
          <div key={item.name} className="flex items-center justify-between gap-4">
            <span className="text-xs font-medium" style={{ color: item.color }}>
              {item.name}
            </span>
            <span className="font-mono-nums text-xs font-semibold text-text-secondary">
              {price != null ? (
                formatPrice(price)
              ) : (
                <span className={item.value >= 0 ? "text-profit-green" : "text-loss-red"}>
                  {formatPct(item.value)}
                </span>
              )}
            </span>
          </div>
        );
      })}
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
export default function EquityCurve({ series, weeks, onWeeksChange }: EquityCurveProps) {
  const { filter, bots, activeBotIds } = useBotFilter();

  // Anchor benchmarks to the bot's first equity point so all lines share origin
  const benchmarkSince = useMemo(() => {
    if (!series.length) return daysAgo(weeks * 7);
    const dates = series
      .flatMap((s) => s.points)
      .map((p) => p.timestamp.slice(0, 10))
      .filter(Boolean);
    return dates.length ? [...dates].sort()[0] : daysAgo(weeks * 7);
  }, [series, weeks]);

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

  const tickFormatter = useMemo(() => getTickFormatter(weeks), [weeks]);
  const ticks = useMemo(() => computeTicks(data, weeks), [data, weeks]);
  // Hourly fallback: thin to ~7 ticks when computeTicks returns undefined
  const tickInterval = ticks ? 0 : data.length > 7 ? Math.floor(data.length / 7) : 0;

  return (
    <div className="rounded-lg border border-border-primary bg-bg-card p-4">
      {/* Header: title + week slider + bot stats */}
      <div className="flex flex-wrap items-start justify-between gap-4 mb-5">
        <div className="flex items-center gap-3 self-center">
          <h3 className="text-sm font-medium text-text-secondary">Equity Curve</h3>
          <div className="flex items-center gap-2" role="group" aria-label="Select time range">
            <input
              type="range"
              min={1}
              max={52}
              value={weeks}
              onChange={(e) => onWeeksChange(Number(e.target.value))}
              className="w-28 cursor-pointer"
              style={{ accentColor: "#60a5fa" }}
              aria-label={`${weeks} ${weeks === 1 ? "week" : "weeks"}`}
            />
            <span className="text-xs text-text-muted min-w-[4.5rem]">
              {weeks === 1 ? "1 week" : `${weeks} weeks`}
            </span>
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
              tickFormatter={tickFormatter}
              ticks={ticks}
              interval={ticks ? 0 : tickInterval}
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
