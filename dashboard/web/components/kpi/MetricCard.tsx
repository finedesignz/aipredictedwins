"use client";

import { TrendingUp, TrendingDown } from "lucide-react";

interface MetricCardProps {
  label: string;
  value: string;
  delta?: string;
  color?: "green" | "red" | "blue" | "amber" | "default";
  valueB?: string;
  deltaB?: string;
  colorB?: "green" | "red" | "blue" | "amber" | "default";
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

export default function MetricCard({
  label,
  value,
  delta,
  color = "default",
  valueB,
  deltaB,
  colorB,
}: MetricCardProps) {
  const isPositive = delta ? !delta.startsWith("-") : true;
  const isBPositive = deltaB ? !deltaB.startsWith("-") : true;

  return (
    <div className="rounded-lg border border-border-primary bg-bg-card p-4 transition-colors hover:bg-bg-card-hover">
      <p className="text-xs font-medium uppercase tracking-wider text-text-muted">
        {label}
      </p>
      {valueB !== undefined ? (
        <div className="flex items-baseline gap-1 flex-wrap mt-1">
          <span className={`font-mono-nums text-2xl font-bold ${colorClass(color)}`}>{value}</span>
          <span className="text-text-muted text-xs">/</span>
          <span className={`font-mono-nums text-2xl font-bold ${colorClass(colorB ?? "default")}`}>{valueB}</span>
        </div>
      ) : (
        <p className={`font-mono-nums text-2xl font-bold mt-1 ${colorMap[color]}`}>
          {value}
        </p>
      )}
      {delta && (
        <div className="flex items-center gap-1 mt-1">
          {isPositive ? (
            <TrendingUp className="h-3 w-3 text-profit-green" aria-hidden="true" />
          ) : (
            <TrendingDown className="h-3 w-3 text-loss-red" aria-hidden="true" />
          )}
          <span
            className={`font-mono-nums text-xs ${
              isPositive ? "text-profit-green" : "text-loss-red"
            }`}
          >
            {delta}
          </span>
          {deltaB && (
            <>
              <span className="text-text-muted text-xs">/</span>
              {isBPositive ? (
                <TrendingUp className="h-3 w-3 text-profit-green" aria-hidden="true" />
              ) : (
                <TrendingDown className="h-3 w-3 text-loss-red" aria-hidden="true" />
              )}
              <span
                className={`font-mono-nums text-xs ${
                  isBPositive ? "text-profit-green" : "text-loss-red"
                }`}
              >
                {deltaB}
              </span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
