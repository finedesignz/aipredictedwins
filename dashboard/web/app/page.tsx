"use client";

import { useAPI } from "@/hooks/useAPI";
import type { Portfolio, Position, EquityData, MultiBotPortfolio, BenchmarkPoint } from "@/types";
import HeroKPI from "@/components/kpi/HeroKPI";
import MetricCard from "@/components/kpi/MetricCard";
import EquityCurve from "@/components/charts/EquityCurve";
import PositionCard from "@/components/positions/PositionCard";
import ActivityFeed from "@/components/activity/ActivityFeed";
import BotFilter from "@/components/shared/BotFilter";
import { useBotFilter } from "@/context/BotFilterContext";
import {
  formatCurrency,
  formatPercent,
  formatPercentUnsigned,
} from "@/lib/format";

export default function OverviewPage() {
  const { botParam } = useBotFilter();

  const { data: rawPortfolio, loading: portfolioLoading } = useAPI<Portfolio | MultiBotPortfolio>(
    `/api/portfolio?bot=${botParam}`,
    10000
  );
  const { data: positions } = useAPI<Position[]>(
    `/api/positions/open?bot=${botParam}`,
    30000
  );
  const { data: equityData } = useAPI<EquityData>(`/api/equity?bot=${botParam}`);
  const { data: spyData } = useAPI<BenchmarkPoint[]>("/api/benchmark/spy", 300000);
  const { data: btcData } = useAPI<BenchmarkPoint[]>("/api/benchmark/btc", 300000);

  // Derive per-bot values
  const isMulti = botParam === "both";
  const portA: Portfolio | undefined = isMulti
    ? (rawPortfolio as MultiBotPortfolio)?.A ?? undefined
    : (rawPortfolio as Portfolio) ?? undefined;
  const portB: Portfolio | undefined = isMulti
    ? (rawPortfolio as MultiBotPortfolio)?.B ?? undefined
    : undefined;

  // For single-bot mode, use the flat portfolio
  const portfolio = isMulti ? undefined : (rawPortfolio as Portfolio);

  return (
    <div className="space-y-6">
      {/* Bot filter */}
      <BotFilter />

      {/* Hero KPI */}
      {isMulti ? (
        portA || portB ? (
          <HeroKPI
            value={portA?.equity ?? 0}
            label="Portfolio Value"
            delta={portA?.total_pnl}
            deltaPercent={portA?.total_pnl_percent}
            labelA="Bot A"
            valueA={portA?.equity}
            deltaA={portA?.total_pnl}
            deltaPercentA={portA?.total_pnl_percent}
            labelB="Bot B"
            valueB={portB?.equity}
            deltaB={portB?.total_pnl}
            deltaPercentB={portB?.total_pnl_percent}
          />
        ) : (
          <div className="text-center py-8">
            <div className="h-12 w-48 mx-auto rounded bg-bg-card animate-pulse" />
            <div className="h-4 w-32 mx-auto mt-3 rounded bg-bg-card animate-pulse" />
          </div>
        )
      ) : portfolio ? (
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
          value={portA ? formatCurrency(portA.total_pnl) : "--"}
          delta={portA ? formatPercent(portA.total_pnl_percent) : undefined}
          color={portA ? (portA.total_pnl >= 0 ? "green" : "red") : "default"}
          valueB={portB ? formatCurrency(portB.total_pnl) : undefined}
          deltaB={portB ? formatPercent(portB.total_pnl_percent) : undefined}
          colorB={portB ? (portB.total_pnl >= 0 ? "green" : "red") : undefined}
        />
        <MetricCard
          label="Win Rate"
          value={portA ? formatPercentUnsigned(portA.win_rate) : "--"}
          delta={portA ? `${portA.wins}W / ${portA.losses}L` : undefined}
          color={portA ? (portA.win_rate >= 50 ? "green" : "red") : "default"}
          valueB={portB ? formatPercentUnsigned(portB.win_rate) : undefined}
          deltaB={portB ? `${portB.wins}W / ${portB.losses}L` : undefined}
          colorB={portB ? (portB.win_rate >= 50 ? "green" : "red") : undefined}
        />
        <MetricCard
          label="Open Positions"
          value={portA ? String(portA.open_positions) : "--"}
          color="blue"
          valueB={portB ? String(portB.open_positions) : undefined}
          colorB="blue"
        />
        <MetricCard
          label="Daily P&L"
          value={portA ? formatCurrency(portA.daily_pnl) : "--"}
          delta={portA ? formatPercent(portA.daily_pnl_percent) : undefined}
          color={portA ? (portA.daily_pnl >= 0 ? "green" : "red") : "default"}
          valueB={portB ? formatCurrency(portB.daily_pnl) : undefined}
          deltaB={portB ? formatPercent(portB.daily_pnl_percent) : undefined}
          colorB={portB ? (portB.daily_pnl >= 0 ? "green" : "red") : undefined}
        />
      </div>

      {/* Equity curve */}
      <EquityCurve
        series={equityData?.series ?? []}
        spy={spyData ?? []}
        btc={btcData ?? []}
      />

      {/* Two-column: positions + activity */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
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
