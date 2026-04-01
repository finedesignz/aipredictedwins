"use client";

import { formatCurrency, formatPercent } from "@/lib/format";

interface HeroKPIProps {
  value: number;
  label: string;
  delta: number;
  deltaPercent: number;
}

export default function HeroKPI({ value, label, delta, deltaPercent }: HeroKPIProps) {
  const isPositive = delta >= 0;
  const colorClass = isPositive ? "text-profit-green" : "text-loss-red";

  return (
    <div className="text-center py-8">
      <p className="text-xs font-medium uppercase tracking-wider text-text-muted mb-2">
        {label}
      </p>
      <p className="font-mono-nums text-4xl font-bold text-text-primary sm:text-5xl">
        ${Math.abs(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </p>
      <p className={`font-mono-nums text-sm mt-2 ${colorClass}`}>
        {formatCurrency(delta)} ({formatPercent(deltaPercent)})
      </p>
    </div>
  );
}
