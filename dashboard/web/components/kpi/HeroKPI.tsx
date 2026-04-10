"use client";

import { formatCurrency, formatPercent } from "@/lib/format";

interface HeroKPIProps {
  value: number;
  label: string;
  delta?: number;
  deltaPercent?: number;
  // Dual-bot support
  labelA?: string;
  valueA?: number;
  deltaA?: number;
  deltaPercentA?: number;
  labelB?: string;
  valueB?: number;
  deltaB?: number;
  deltaPercentB?: number;
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
  labelA,
  valueA,
  deltaA,
  deltaPercentA,
  labelB,
  valueB,
  deltaB,
  deltaPercentB,
}: HeroKPIProps) {
  const isDual = valueA !== undefined && valueB !== undefined;

  if (isDual) {
    return (
      <div className="text-center py-8">
        <p className="text-xs font-medium uppercase tracking-wider text-text-muted mb-3">
          {label}
        </p>
        <div className="flex flex-col gap-2 items-center">
          <div className="flex items-baseline gap-3">
            <span className="text-xs font-medium text-accent-blue w-12 text-right">{labelA ?? "Bot A"}:</span>
            <span className="font-mono-nums text-2xl font-bold text-text-primary">
              ${Math.abs(valueA!).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
            <DeltaBadge delta={deltaA} pct={deltaPercentA} />
          </div>
          <div className="flex items-baseline gap-3">
            <span className="text-xs font-medium text-warning-amber w-12 text-right">{labelB ?? "Bot B"}:</span>
            <span className="font-mono-nums text-2xl font-bold text-text-primary">
              ${Math.abs(valueB!).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
            <DeltaBadge delta={deltaB} pct={deltaPercentB} />
          </div>
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
