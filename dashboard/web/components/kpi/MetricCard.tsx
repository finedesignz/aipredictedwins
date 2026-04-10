"use client";

import { TrendingUp, TrendingDown } from "lucide-react";

type MetricColor = "green" | "red" | "blue" | "amber" | "default";

export interface MetricCardEntry {
  value: string;
  delta?: string;
  color?: MetricColor;
}

interface MetricCardProps {
  label: string;
  value: string;
  delta?: string;
  color?: MetricColor;
  entries?: MetricCardEntry[];
}

const colorMap = {
  green: "text-profit-green",
  red: "text-loss-red",
  blue: "text-accent-blue",
  amber: "text-warning-amber",
  default: "text-text-primary",
};

function colorClass(c: "green" | "red" | "blue" | "amber" | "default" | undefined): string {
  return colorMap[c ?? "default"];
}

function DeltaRow({ delta }: { delta: string }) {
  const isPos = !delta.startsWith("-");
  return (
    <>
      {isPos ? (
        <TrendingUp className="h-3 w-3 text-profit-green" aria-hidden="true" />
      ) : (
        <TrendingDown className="h-3 w-3 text-loss-red" aria-hidden="true" />
      )}
      <span className={`font-mono-nums text-xs ${isPos ? "text-profit-green" : "text-loss-red"}`}>
        {delta}
      </span>
    </>
  );
}

export default function MetricCard({
  label,
  value,
  delta,
  color = "default",
  entries,
}: MetricCardProps) {
  const allEntries: MetricCardEntry[] = entries ?? [{ value, delta, color }];
  const isMulti = allEntries.length > 1;

  return (
    <div className="rounded-lg border border-border-primary bg-bg-card p-4 transition-colors hover:bg-bg-card-hover">
      <p className="text-xs font-medium uppercase tracking-wider text-text-muted">
        {label}
      </p>
      {isMulti ? (
        <>
          <div className="flex items-baseline gap-1 flex-wrap mt-1">
            {allEntries.map((e, i) => (
              <span key={i} className="flex items-baseline gap-1">
                {i > 0 && <span className="text-text-muted text-xs">/</span>}
                <span className={`font-mono-nums text-2xl font-bold ${colorClass(e.color)}`}>
                  {e.value}
                </span>
              </span>
            ))}
          </div>
          <div className="flex items-center gap-1 mt-1 flex-wrap">
            {allEntries.map((e, i) =>
              e.delta ? (
                <span key={i} className="flex items-center gap-1">
                  {i > 0 && <span className="text-text-muted text-xs">/</span>}
                  <DeltaRow delta={e.delta} />
                </span>
              ) : null
            )}
          </div>
        </>
      ) : (
        <>
          <p className={`font-mono-nums text-2xl font-bold mt-1 ${colorMap[color]}`}>
            {value}
          </p>
          {delta && (
            <div className="flex items-center gap-1 mt-1">
              <DeltaRow delta={delta} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
