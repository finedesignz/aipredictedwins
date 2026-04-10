"use client";

import { useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  CartesianGrid,
} from "recharts";
import { useAPI } from "@/hooks/useAPI";
import type { AlpacaEquityData, EquityPoint } from "@/types";

const AGENT_A_COLOR = "#60a5fa";
const AGENT_B_COLOR = "#f59e0b";
const SP500_COLOR = "#94a3b8";
const CRYPTO_COLOR = "#34d399";
const START_EQUITY = 100_000;

// ── Helpers ────────────────────────────────────────────────────────────────

function formatAxisDate(ts: string): string {
  return new Date(ts).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function mergeSeries(aPoints: EquityPoint[], bPoints: EquityPoint[], spPoints: EquityPoint[], cryptoPoints: EquityPoint[]) {
  const map = new Map<string, { timestamp: string; a?: number; b?: number; sp?: number; crypto?: number }>();
  for (const p of aPoints) map.set(p.timestamp, { timestamp: p.timestamp, a: p.equity });
  for (const p of bPoints) {
    const ex = map.get(p.timestamp);
    if (ex) ex.b = p.equity;
    else map.set(p.timestamp, { timestamp: p.timestamp, b: p.equity });
  }
  for (const p of spPoints) {
    const ex = map.get(p.timestamp);
    if (ex) ex.sp = p.equity;
    else map.set(p.timestamp, { timestamp: p.timestamp, sp: p.equity });
  }
  for (const p of cryptoPoints) {
    const ex = map.get(p.timestamp);
    if (ex) ex.crypto = p.equity;
    else map.set(p.timestamp, { timestamp: p.timestamp, crypto: p.equity });
  }
  const sorted = Array.from(map.values()).sort((x, y) => (x.timestamp < y.timestamp ? -1 : 1));

  // Forward-fill: carry the last known value for each series so every
  // tooltip hover shows all four lines, not just those with data that day.
  let lastA: number | undefined;
  let lastB: number | undefined;
  let lastSp: number | undefined;
  let lastCrypto: number | undefined;
  for (const pt of sorted) {
    if (pt.a != null) lastA = pt.a; else if (lastA != null) pt.a = lastA;
    if (pt.b != null) lastB = pt.b; else if (lastB != null) pt.b = lastB;
    if (pt.sp != null) lastSp = pt.sp; else if (lastSp != null) pt.sp = lastSp;
    if (pt.crypto != null) lastCrypto = pt.crypto; else if (lastCrypto != null) pt.crypto = lastCrypto;
  }
  return sorted;
}

// ── Tooltip ────────────────────────────────────────────────────────────────

interface TooltipItem { value: number; name: string; color: string }
interface TTProps { active?: boolean; payload?: TooltipItem[]; label?: string }

const SERIES_META = [
  { key: "a",      name: "Agent A",  color: AGENT_A_COLOR },
  { key: "b",      name: "Agent B",  color: AGENT_B_COLOR },
  { key: "sp",     name: "S&P 500",  color: SP500_COLOR },
  { key: "crypto", name: "BTC (mkt)", color: CRYPTO_COLOR },
] as const;

function CustomTooltip({ active, payload, label }: TTProps) {
  if (!active || !payload?.length) return null;

  // Build a value map from whatever recharts passes
  const valMap: Record<string, number> = {};
  for (const item of payload) {
    // item.name matches the `name` prop on each <Line>
    if (item.name === "Agent A") valMap.a = item.value;
    else if (item.name === "Agent B") valMap.b = item.value;
    else if (item.name === "S&P 500") valMap.sp = item.value;
    else if (item.name === "BTC (mkt)") valMap.crypto = item.value;
  }

  return (
    <div className="rounded-lg border border-border-primary bg-bg-card p-3 shadow-lg min-w-[175px]">
      {label && (
        <p className="text-xs text-text-muted mb-2">
          {new Date(label).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
        </p>
      )}
      {SERIES_META.map(({ key, name, color }) => {
        const val = valMap[key];
        if (val == null) return null;
        const pct = ((val - START_EQUITY) / START_EQUITY) * 100;
        const isPos = pct >= 0;
        return (
          <div key={key} className="flex items-center justify-between gap-5 mt-1.5">
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
              <span className="text-xs font-medium text-text-secondary">{name}</span>
            </div>
            <div className="text-right">
              <span className="font-mono-nums text-xs font-semibold text-text-primary block">
                ${val.toLocaleString("en-US", { minimumFractionDigits: 0 })}
              </span>
              <span className={`font-mono-nums text-xs ${isPos ? "text-profit-green" : "text-loss-red"}`}>
                {isPos ? "+" : ""}{pct.toFixed(2)}%
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Per-bot stat pill ──────────────────────────────────────────────────────

function BotStat({
  label, equity, color, loading,
}: {
  label: string; equity: number; color: string; loading: boolean;
}) {
  const delta = equity - START_EQUITY;
  const pct = (delta / START_EQUITY) * 100;
  const isPos = delta >= 0;

  return (
    <div className="flex items-center gap-2.5">
      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
      <div>
        <p className="text-xs text-text-muted uppercase tracking-wider leading-none">{label}</p>
        {loading ? (
          <div className="h-5 w-20 rounded bg-bg-card animate-pulse mt-1" />
        ) : (
          <div className="flex items-baseline gap-1.5 mt-0.5">
            <span className="font-mono-nums text-base font-semibold text-text-primary">
              ${Math.round(equity).toLocaleString("en-US")}
            </span>
            <span className={`font-mono-nums text-xs font-medium ${isPos ? "text-profit-green" : "text-loss-red"}`}>
              {isPos ? "+" : ""}{pct.toFixed(2)}%
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Day slider ─────────────────────────────────────────────────────────────

function DaySlider({ days, onChange }: { days: number; onChange: (d: number) => void }) {
  return (
    <div className="flex items-center gap-3 min-w-[180px]">
      <span className="text-xs text-text-muted whitespace-nowrap">{days}d</span>
      <input
        type="range"
        min={1}
        max={90}
        value={days}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-1.5 rounded-full appearance-none cursor-pointer bg-bg-secondary accent-accent-blue"
        aria-label={`Show last ${days} days`}
      />
      <span className="text-xs text-text-muted">90d</span>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────

export default function EquityCurve({
  agentA: localA,
  agentB: localB,
}: {
  agentA: EquityPoint[];
  agentB: EquityPoint[];
}) {
  const [days, setDays] = useState(30);

  const { data, loading } = useAPI<AlpacaEquityData>(`/api/alpaca/equity?days=${days}`, 0);

  // Prefer Alpaca live data; fall back to local SQLite data
  const aPoints = (data?.agentA?.length ? data.agentA : localA) ?? [];
  const bPoints = (data?.agentB?.length ? data.agentB : localB) ?? [];
  const spPoints = data?.sp500 ?? [];
  const cryptoPoints = data?.cryptoBenchmark ?? [];

  const equityA = data?.accountA?.equity ?? (aPoints.at(-1)?.equity ?? START_EQUITY);
  const equityB = data?.accountB?.equity ?? (bPoints.at(-1)?.equity ?? START_EQUITY);
  const spLast = spPoints.at(-1)?.equity ?? START_EQUITY;
  const cryptoLast = cryptoPoints.at(-1)?.equity ?? START_EQUITY;

  const chartData = mergeSeries(aPoints, bPoints, spPoints, cryptoPoints);
  const hasData = chartData.length > 1;

  // Y-axis domain — tight around actual data, never includes zero
  const allEquity = chartData
    .flatMap((p) => [p.a, p.b, p.sp, p.crypto])
    .filter((v): v is number => v != null && v > 0);
  const dataMin = allEquity.length ? Math.min(...allEquity) : START_EQUITY;
  const dataMax = allEquity.length ? Math.max(...allEquity) : START_EQUITY;
  const range = Math.max(dataMax - dataMin, dataMax * 0.01); // at least 1% range
  const minY = dataMin - range * 0.2;
  const maxY = dataMax + range * 0.2;

  return (
    <div className="rounded-lg border border-border-primary bg-bg-card p-4">
      {/* Header row */}
      <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
        <div className="flex flex-wrap gap-5">
          <BotStat label="Agent A" equity={equityA} color={AGENT_A_COLOR} loading={loading} />
          <BotStat label="Agent B" equity={equityB} color={AGENT_B_COLOR} loading={loading} />
          <BotStat label="S&P 500" equity={spLast} color={SP500_COLOR} loading={loading} />
          <BotStat label="BTC (mkt)" equity={cryptoLast} color={CRYPTO_COLOR} loading={loading} />
        </div>
        <div className="flex items-center gap-3 flex-1 max-w-xs">
          <span className="text-xs text-text-muted whitespace-nowrap">Last</span>
          <DaySlider days={days} onChange={setDays} />
        </div>
      </div>

      {/* Error notice */}
      {data?.errors?.length ? (
        <p className="text-xs text-warning-amber mb-3">
          Live data partial: {data.errors.join("; ")}
        </p>
      ) : null}

      {!hasData ? (
        <div className="flex items-center justify-center h-56">
          {loading ? (
            <div className="h-48 w-full rounded bg-bg-secondary animate-pulse" />
          ) : (
            <p className="text-sm text-text-muted">No equity data for this period.</p>
          )}
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={chartData} margin={{ top: 4, right: 52, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" strokeOpacity={0.5} vertical={false} />
            <XAxis
              dataKey="timestamp"
              tickFormatter={formatAxisDate}
              axisLine={false}
              tickLine={false}
              tick={{ fill: "#64748b", fontSize: 11 }}
              dy={8}
              interval="preserveStartEnd"
            />
            {/* Left axis — dollar value */}
            <YAxis
              yAxisId="dollar"
              orientation="left"
              domain={[minY, maxY]}
              tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
              axisLine={false}
              tickLine={false}
              tick={{ fill: "#64748b", fontSize: 11 }}
              dx={-4}
              width={52}
            />
            {/* Right axis — % return */}
            <YAxis
              yAxisId="pct"
              orientation="right"
              domain={[
                ((minY - START_EQUITY) / START_EQUITY) * 100,
                ((maxY - START_EQUITY) / START_EQUITY) * 100,
              ]}
              tickFormatter={(v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`}
              axisLine={false}
              tickLine={false}
              tick={{ fill: "#64748b", fontSize: 11 }}
              dx={4}
              width={52}
            />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine
              yAxisId="dollar"
              y={START_EQUITY}
              stroke="#64748b"
              strokeDasharray="4 4"
              strokeOpacity={0.4}
            />
            <Line
              yAxisId="dollar"
              type="monotone"
              dataKey="a"
              name="Agent A"
              stroke={AGENT_A_COLOR}
              strokeWidth={2}
              dot={false}
              connectNulls
            />
            <Line
              yAxisId="dollar"
              type="monotone"
              dataKey="b"
              name="Agent B"
              stroke={AGENT_B_COLOR}
              strokeWidth={2}
              dot={false}
              connectNulls
            />
            <Line
              yAxisId="dollar"
              type="monotone"
              dataKey="sp"
              name="S&P 500"
              stroke={SP500_COLOR}
              strokeWidth={1.5}
              strokeDasharray="5 3"
              dot={false}
              connectNulls
            />
            <Line
              yAxisId="dollar"
              type="monotone"
              dataKey="crypto"
              name="BTC (mkt)"
              stroke={CRYPTO_COLOR}
              strokeWidth={1.5}
              strokeDasharray="5 3"
              dot={false}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      )}

      <p className="text-xs text-text-muted mt-2 text-right">
        {data ? "Alpaca live" : "Local data"} · {data?.days ?? days}d window
      </p>
    </div>
  );
}
