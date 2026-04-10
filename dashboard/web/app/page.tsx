"use client";

import { useState, useMemo } from "react";
import { useAPI } from "@/hooks/useAPI";
import type { Portfolio, Position, EquityData, MultiBotPortfolio, BenchmarkPoint } from "@/types";

type DayOption = 7 | 14 | 30 | 60 | 90;

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}
import HeroKPI, { type HeroKPIEntry } from "@/components/kpi/HeroKPI";
import MetricCard, { type MetricCardEntry } from "@/components/kpi/MetricCard";
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
  const { botParam, bots, activeBotIds } = useBotFilter();
  const [days, setDays] = useState<DayOption>(30);

  const { data: rawPortfolio, loading: portfolioLoading } = useAPI<Portfolio | MultiBotPortfolio>(
    `/api/portfolio?bot=${botParam}`,
    10000
  );
  const { data: positions } = useAPI<Position[]>(
    `/api/positions/open?bot=${botParam}`,
    30000
  );
  const { data: equityData } = useAPI<EquityData>(`/api/equity?bot=${botParam}&days=${days}`);

  // Anchor benchmarks to the bot's first equity data point so all lines start together
  const benchmarkSince = useMemo(() => {
    if (!equityData?.series?.length) return daysAgo(days);
    const dates = equityData.series
      .flatMap((s) => s.points)
      .map((p) => p.timestamp.slice(0, 10))
      .filter(Boolean);
    return dates.length ? [...dates].sort()[0] : daysAgo(days);
  }, [equityData, days]);

  const { data: spyData } = useAPI<BenchmarkPoint[]>(`/api/benchmark/spy?since=${benchmarkSince}`, 300000);
  const { data: btcData } = useAPI<BenchmarkPoint[]>(`/api/benchmark/btc?since=${benchmarkSince}`, 300000);

  // Build label lookup from DB bots
  const botLabelMap: Record<string, string> = {};
  bots.forEach((b) => { botLabelMap[b.bot_id] = b.label; });

  const isMulti = activeBotIds.length !== 1;

  // In multi mode, portfolio is keyed by bot_id; in single mode it's a flat Portfolio
  const portMap: MultiBotPortfolio = isMulti
    ? (rawPortfolio as MultiBotPortfolio) ?? {}
    : {};
  const portfolio: Portfolio | undefined = isMulti
    ? undefined
    : (rawPortfolio as Portfolio) ?? undefined;

  // Per-bot portfolio entries for multi mode
  const activePortfolios = activeBotIds
    .map((id) => ({ id, label: botLabelMap[id] ?? id, port: portMap[id] }))
    .filter((x) => x.port !== undefined) as Array<{ id: string; label: string; port: Portfolio }>;

  // Hero KPI entries
  const heroEntries: HeroKPIEntry[] = activePortfolios.map((x) => ({
    label: x.label,
    value: x.port.equity,
    delta: x.port.total_pnl,
    deltaPercent: x.port.total_pnl_percent,
  }));

  // MetricCard entry builders
  function pnlEntries(): MetricCardEntry[] {
    return activePortfolios.map((x) => ({
      value: formatCurrency(x.port.total_pnl),
      delta: formatPercent(x.port.total_pnl_percent),
      color: x.port.total_pnl >= 0 ? "green" : "red",
    }));
  }
  function winRateEntries(): MetricCardEntry[] {
    return activePortfolios.map((x) => ({
      value: formatPercentUnsigned(x.port.win_rate),
      delta: `${x.port.wins}W / ${x.port.losses}L`,
      color: x.port.win_rate >= 50 ? "green" : "red",
    }));
  }
  function openPosEntries(): MetricCardEntry[] {
    return activePortfolios.map((x) => ({
      value: String(x.port.open_positions),
      color: "blue" as const,
    }));
  }
  function dailyPnlEntries(): MetricCardEntry[] {
    return activePortfolios.map((x) => ({
      value: formatCurrency(x.port.daily_pnl),
      delta: formatPercent(x.port.daily_pnl_percent),
      color: x.port.daily_pnl >= 0 ? "green" : "red",
    }));
  }

  return (
    <div className="space-y-6">
      {/* Bot filter */}
      <BotFilter />

      {/* Hero KPI */}
      {isMulti ? (
        heroEntries.length > 0 ? (
          <HeroKPI
            value={heroEntries[0].value}
            label="Portfolio Value"
            entries={heroEntries}
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
        {isMulti ? (
          <>
            <MetricCard label="Total P&L" value="--" entries={pnlEntries()} />
            <MetricCard label="Win Rate" value="--" entries={winRateEntries()} />
            <MetricCard label="Open Positions" value="--" entries={openPosEntries()} />
            <MetricCard label="Daily P&L" value="--" entries={dailyPnlEntries()} />
          </>
        ) : (
          <>
            <MetricCard
              label="Total P&L"
              value={portfolio ? formatCurrency(portfolio.total_pnl) : "--"}
              delta={portfolio ? formatPercent(portfolio.total_pnl_percent) : undefined}
              color={portfolio ? (portfolio.total_pnl >= 0 ? "green" : "red") : "default"}
            />
            <MetricCard
              label="Win Rate"
              value={portfolio ? formatPercentUnsigned(portfolio.win_rate) : "--"}
              delta={portfolio ? `${portfolio.wins}W / ${portfolio.losses}L` : undefined}
              color={portfolio ? (portfolio.win_rate >= 50 ? "green" : "red") : "default"}
            />
            <MetricCard
              label="Open Positions"
              value={portfolio ? String(portfolio.open_positions) : "--"}
              color="blue"
            />
            <MetricCard
              label="Daily P&L"
              value={portfolio ? formatCurrency(portfolio.daily_pnl) : "--"}
              delta={portfolio ? formatPercent(portfolio.daily_pnl_percent) : undefined}
              color={portfolio ? (portfolio.daily_pnl >= 0 ? "green" : "red") : "default"}
            />
          </>
        )}
      </div>

      {/* Equity curve */}
      <EquityCurve
        series={equityData?.series ?? []}
        spy={spyData ?? []}
        btc={btcData ?? []}
        days={days}
        onDaysChange={setDays}
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
