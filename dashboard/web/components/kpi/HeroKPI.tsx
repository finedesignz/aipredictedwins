"use client";

import { formatCurrency, formatPercent } from "@/lib/format";

const ENTRY_COLORS = [
  "text-accent-blue",
  "text-warning-amber",
  "text-profit-green",
  "text-loss-red",
  "text-text-secondary",
];

export interface HeroKPIEntry {
  label: string;
  value: number;
  delta?: number;
  deltaPercent?: number;
}

interface HeroKPIProps {
  value: number;
  label: string;
  delta?: number;
  deltaPercent?: number;
  entries?: HeroKPIEntry[];
}

function DeltaBadge({ delta, pct }: { delta?: number; pct?: number }) {
  if (delta === undefined) return null;
  const isPos = delta >= 0;
  return (
    <span className={`text-sm font-medium ${isPos ? "text-profit-green" : "text-loss-red"}`}>
      {isPos ? "+" : ""}{pct !== undefined ? pct.toFixed(2) + "%" : delta.toLocaleString("en-US", { style: "currency", currency: "USD" })}
    </span>
  );
}

export default function HeroKPI({
  value,
  label,
  delta,
  deltaPercent,
  entries,
}: HeroKPIProps) {
  if (entries && entries.length >= 2) {
    return (
      <div className="text-center py-8">
        <p className="text-xs font-medium uppercase tracking-wider text-text-muted mb-3">
          {label}
        </p>
        <div className="flex flex-col gap-2 items-center">
          {entries.map((e, i) => (
            <div key={e.label} className="flex items-baseline gap-3">
              <span className={`text-xs font-medium w-16 text-right ${ENTRY_COLORS[i % ENTRY_COLORS.length]}`}>
                {e.label}:
              </span>
              <span className="font-mono-nums text-2xl font-bold text-text-primary">
                ${Math.abs(e.value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
              <DeltaBadge delta={e.delta} pct={e.deltaPercent} />
            </div>
          ))}
        </div>
      </div>
    );
  }

  const isPositive = (delta ?? 0) >= 0;
  const colorClass = isPositive ? "text-profit-green" : "text-loss-red";

  return (
    <div className="text-center py-8">
      <p className="text-xs font-medium uppercase tracking-wider text-text-muted mb-2">
        {label}
      </p>
      <p className="font-mono-nums text-4xl font-bold text-text-primary sm:text-5xl">
        ${Math.abs(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </p>
      {delta !== undefined && (
        <p className={`font-mono-nums text-sm mt-2 ${colorClass}`}>
          {formatCurrency(delta)} ({formatPercent(deltaPercent ?? 0)})
        </p>
      )}
    </div>
  );
}
