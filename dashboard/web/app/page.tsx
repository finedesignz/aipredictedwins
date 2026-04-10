"use client";

import { useAPI } from "@/hooks/useAPI";
import type { Portfolio, Position, EquityPoint } from "@/types";
import HeroKPI from "@/components/kpi/HeroKPI";
import MetricCard from "@/components/kpi/MetricCard";
import EquityCurve from "@/components/charts/EquityCurve";
import PositionCard from "@/components/positions/PositionCard";
import ActivityFeed from "@/components/activity/ActivityFeed";
import {
  formatCurrency,
  formatPercent,
  formatPercentUnsigned,
} from "@/lib/format";

export default function OverviewPage() {
  const { data: portfolio, loading: portfolioLoading } = useAPI<Portfolio>(
    "/api/portfolio",
    10000
  );
  const { data: positions } = useAPI<Position[]>(
    "/api/positions/open",
    30000
  );
  const { data: equityData } = useAPI<EquityPoint[]>("/api/equity");

  return (
    <div className="space-y-6">
      {/* Hero KPI */}
      {portfolio ? (
        <HeroKPI
          value={portfolio.equity}
          label="Portfolio Value"
          delta={portfolio.total_pnl}
          deltaPercent={portfolio.total_pnl_percent}
        />
      ) : (
        <div className="text-center py-8">
          <div className="h-12 w-48 mx-auto rounded bg-bg-card animate-pulse" />
          <div className="h-4 w-32 mx-auto mt-3 rounded bg-bg-card animate-pulse" />
        </div>
      )}

      {/* Metric cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          label="Total P&L"
          value={portfolio ? formatCurrency(portfolio.total_pnl) : "--"}
          delta={
            portfolio
              ? formatPercent(portfolio.total_pnl_percent)
              : undefined
          }
          color={
            portfolio
              ? portfolio.total_pnl >= 0
                ? "green"
                : "red"
              : "default"
          }
        />
        <MetricCard
          label="Win Rate"
          value={
            portfolio
              ? formatPercentUnsigned(portfolio.win_rate)
              : "--"
          }
          delta={
            portfolio
              ? `${portfolio.wins}W / ${portfolio.losses}L`
              : undefined
          }
          color={
            portfolio
              ? portfolio.win_rate >= 50  // win_rate is 0-100 percentage
                ? "green"
                : "red"
              : "default"
          }
        />
        <MetricCard
          label="Open Positions"
          value={
            portfolio ? String(portfolio.open_positions) : "--"
          }
          color="blue"
        />
        <MetricCard
          label="Daily P&L"
          value={portfolio ? formatCurrency(portfolio.daily_pnl) : "--"}
          delta={
            portfolio
              ? formatPercent(portfolio.daily_pnl_percent)
              : undefined
          }
          color={
            portfolio
              ? portfolio.daily_pnl >= 0
                ? "green"
                : "red"
              : "default"
          }
        />
      </div>

      {/* Equity curve */}
      <EquityCurve data={equityData ?? []} />

      {/* Two-column: positions + activity */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Open positions */}
        <div className="lg:col-span-3">
          <h2 className="text-sm font-medium text-text-secondary mb-3">
            Open Positions
          </h2>
          {positions && positions.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {positions.map((pos) => (
                <PositionCard key={pos.id} position={pos} />
              ))}
            </div>
          ) : (
            <div className="flex items-center justify-center h-48 rounded-lg border border-border-primary bg-bg-card">
              <p className="text-sm text-text-muted">
                {portfolioLoading
                  ? "Loading positions..."
                  : "No open positions. The bot will open positions when it finds high-confluence signals."}
              </p>
            </div>
          )}
        </div>

        {/* Activity feed */}
        <div className="lg:col-span-2">
          <h2 className="text-sm font-medium text-text-secondary mb-3">
            Live Activity
          </h2>
          <ActivityFeed />
        </div>
      </div>
    </div>
  );
}
