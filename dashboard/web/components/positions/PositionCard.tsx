"use client";

import { TrendingUp, TrendingDown, Clock } from "lucide-react";
import type { Position } from "@/types";
import { formatCurrency, formatPercent, formatRelativeTime } from "@/lib/format";
import Badge from "@/components/shared/Badge";

interface PositionCardProps {
  position: Position;
}

export default function PositionCard({ position }: PositionCardProps) {
  const isProfit = position.unrealized_pnl >= 0;
  const pnlColor = isProfit ? "text-profit-green" : "text-loss-red";

  return (
    <div className="rounded-lg border border-border-primary bg-bg-card p-4 transition-colors hover:bg-bg-card-hover">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="font-mono-nums text-sm font-semibold text-text-primary">
            {position.symbol}
          </span>
          <Badge variant={position.side === "long" ? "bullish" : "bearish"}>
            {position.side.toUpperCase()}
          </Badge>
          {position.bot && (
            <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${position.bot.includes("B") ? "bg-warning-amber/15 text-warning-amber" : "bg-accent-blue/15 text-accent-blue"}`}>
              {position.bot.includes("B") ? "B" : "A"}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 text-text-muted">
          <Clock className="h-3 w-3" aria-hidden="true" />
          <span className="text-xs">{formatRelativeTime(position.opened_at)}</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <p className="text-xs text-text-muted">Entry</p>
          <p className="font-mono-nums text-text-secondary">
            ${position.entry_price.toFixed(2)}
          </p>
        </div>
        <div>
          <p className="text-xs text-text-muted">Current</p>
          <p className="font-mono-nums text-text-secondary">
            ${position.current_price.toFixed(2)}
          </p>
        </div>
        <div>
          <p className="text-xs text-text-muted">Qty</p>
          <p className="font-mono-nums text-text-secondary">
            {position.quantity}
          </p>
        </div>
        <div>
          <p className="text-xs text-text-muted">Confluence</p>
          <p className="font-mono-nums text-text-secondary">
            {position.confluence_score}/5
          </p>
        </div>
      </div>

      <div className={`flex items-center justify-between mt-3 pt-3 border-t border-border-subtle`}>
        <div className="flex items-center gap-1.5">
          {isProfit ? (
            <TrendingUp className="h-4 w-4 text-profit-green" aria-hidden="true" />
          ) : (
            <TrendingDown className="h-4 w-4 text-loss-red" aria-hidden="true" />
          )}
          <span className={`font-mono-nums text-sm font-semibold ${pnlColor}`}>
            {formatCurrency(position.unrealized_pnl)}
          </span>
        </div>
        <span className={`font-mono-nums text-xs ${pnlColor}`}>
          {formatPercent(position.unrealized_pnl_percent)}
        </span>
      </div>
    </div>
  );
}
