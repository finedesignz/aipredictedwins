"use client";

import { useState } from "react";
import { useAPI } from "@/hooks/useAPI";
import type { Portfolio, Position, EquityData, MultiBotPortfolio } from "@/types";

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
import ErrorBanner from "@/components/shared/ErrorBanner";

// Phase 19 (RUN-02): the headline P&L must SAY WHICH NUMBER IT IS. portfolio.py used to
// fall back from the reconciled/live Alpaca figure to the raw trade-log sum SILENTLY —
// nobody could tell which one they were looking at. An unreconciled number is never
// presented as reconciled.
const PNL_SOURCE_LABEL: Record<Portfolio["pnl_source"], string> = {
  reconciled: "Reconciled",
  alpaca_live: "Alpaca live",
  trade_log: "Trade log",
};

function PnlSourceBadge({ port }: { port: Portfolio }) {
  const label = PNL_SOURCE_LABEL[port.pnl_source] ?? "Trade log";
  const reconciled = port.pnl_source === "reconciled" && !port.stale;
  const breach = port.reconciled?.within_tolerance === false;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span
        className={`rounded px-1.5 py-0.5 text-xs font-medium ${
          reconciled
            ? "bg-profit-green/10 text-profit-green"
            : "bg-bg-secondary text-text-muted"
        }`}
        title="Where the headline P&L number comes from"
      >
        {label}
      </span>
      {port.stale && (
        <span
          className="rounded px-1.5 py-0.5 text-xs font-medium bg-loss-red/10 text-loss-red"
          title="No fresh reconciliation — this number has not been checked against Alpaca recently"
        >
          STALE
        </span>
      )}
      {breach && (
        <span
          className="rounded px-1.5 py-0.5 text-xs font-medium bg-loss-red/10 text-loss-red"
          title="The trade log and Alpaca disagree beyond tolerance"
        >
          RECONCILIATION BREACH
        </span>
      )}
    </div>
  );
}

export default function OverviewPage() {
  const { botParam, bots, activeBotIds } = useBotFilter();
  const [weeks, setWeeks] = useState<number>(4);

  const { data: rawPortfolio, loading: portfolioLoading, error: portfolioError } = useAPI<Portfolio | MultiBotPortfolio>(
    `/api/portfolio?bot=${botParam}&days=${weeks * 7}`,
    10000
  );
  const { data: positions } = useAPI<Position[]>(
    `/api/positions/open?bot=${botParam}`,
    30000
  );
  const { data: equityData } = useAPI<EquityData>(`/api/equity?bot=${botParam}&days=${weeks * 7}`);

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
  // `unresolved` is shown BESIDE wins/losses and is NEVER labelled a loss — that
  // conflation is the bug Phase 19 removed from every reader.
  function winRateDelta(port: Portfolio): string {
    const base = `${port.wins}W / ${port.losses}L`;
    return port.unresolved > 0 ? `${base} / ${port.unresolved} unresolved` : base;
  }
  function winRateEntries(): MetricCardEntry[] {
    return activePortfolios.map((x) => ({
      value: formatPercentUnsigned(x.port.win_rate),
      delta: winRateDelta(x.port),
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

      <ErrorBanner error={portfolioError} />

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

      {/* P&L provenance — what IS this number, and is it stale? */}
      <div className="flex flex-wrap items-center gap-4">
        {isMulti
          ? activePortfolios.map((x) => (
              <div key={x.id} className="flex items-center gap-2">
                <span className="text-xs text-text-muted">{x.label}</span>
                <PnlSourceBadge port={x.port} />
              </div>
            ))
          : portfolio && <PnlSourceBadge port={portfolio} />}
      </div>

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
              delta={portfolio ? winRateDelta(portfolio) : undefined}
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
        weeks={weeks}
        onWeeksChange={setWeeks}
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
