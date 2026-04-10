"use client";

import { useState, useMemo, useCallback } from "react";
import { Download } from "lucide-react";
import { useAPI } from "@/hooks/useAPI";
import type { Trade } from "@/types";
import { buildQueryString } from "@/lib/api";
import { formatCurrency, formatPercentUnsigned } from "@/lib/format";
import TradeTable from "@/components/trades/TradeTable";
import ErrorBanner from "@/components/shared/ErrorBanner";
import { useBotFilter } from "@/context/BotFilterContext";

const SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "ADA/USD", "AVAX/USD", "DOT/USD", "LINK/USD"];

export default function TradesPage() {
  const { botParam } = useBotFilter();
  const [symbol, setSymbol] = useState<string>("");
  const [dateFrom, setDateFrom] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() - 30);
    return d.toISOString().slice(0, 10);
  });
  const [dateTo, setDateTo] = useState<string>("");

  const qs = buildQueryString({ bot: botParam, symbol, date_from: dateFrom, date_to: dateTo });
  const { data: trades, loading, error } = useAPI<Trade[]>(`/api/trades${qs}`);

  const summary = useMemo(() => {
    if (!trades || trades.length === 0) return null;
    const closed = trades.filter((t) => t.status === "closed" && t.pnl !== null);
    const totalPnl = closed.reduce((sum, t) => sum + (t.pnl ?? 0), 0);
    const wins = closed.filter((t) => (t.pnl ?? 0) > 0).length;
    const winRate = closed.length > 0 ? (wins / closed.length) * 100 : 0;
    const avgPnl = closed.length > 0 ? totalPnl / closed.length : 0;
    return {
      total: trades.length,
      closed: closed.length,
      totalPnl,
      winRate,
      avgPnl,
    };
  }, [trades]);

  const exportCSV = useCallback(() => {
    if (!trades || trades.length === 0) return;
    const headers = [
      "timestamp",
      "symbol",
      "side",
      "confluence_score",
      "entry_price",
      "exit_price",
      "pnl",
      "pnl_percent",
      "status",
      "close_reason",
    ];
    const rows = trades.map((t) =>
      [
        t.timestamp,
        t.symbol,
        t.side,
        t.confluence_score,
        t.entry_price,
        t.exit_price ?? "",
        t.pnl ?? "",
        t.pnl_percent ?? "",
        t.status,
        t.close_reason ?? "",
      ].join(",")
    );
    const csv = [headers.join(","), ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `trades-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [trades]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-text-primary">
          Trade History
        </h1>
        <button
          onClick={exportCSV}
          disabled={!trades || trades.length === 0}
          className="flex items-center gap-1.5 rounded-md bg-bg-card border border-border-primary px-3 py-1.5 text-sm text-text-secondary hover:text-text-primary hover:bg-bg-card-hover transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          aria-label="Export trades as CSV"
        >
          <Download className="h-4 w-4" aria-hidden="true" />
          Export CSV
        </button>
      </div>

      <ErrorBanner error={error} />

      {/* Filter bar */}
      <div className="flex flex-wrap gap-3">
        <select
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="rounded-md border border-border-primary bg-bg-input px-3 py-1.5 text-sm text-text-secondary focus:outline-none focus:ring-1 focus:ring-accent-blue"
          aria-label="Filter by symbol"
        >
          <option value="">All Symbols</option>
          {SYMBOLS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
          className="rounded-md border border-border-primary bg-bg-input px-3 py-1.5 text-sm text-text-secondary focus:outline-none focus:ring-1 focus:ring-accent-blue"
          aria-label="From date"
        />
        <input
          type="date"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
          className="rounded-md border border-border-primary bg-bg-input px-3 py-1.5 text-sm text-text-secondary focus:outline-none focus:ring-1 focus:ring-accent-blue"
          aria-label="To date"
        />
      </div>

      {/* Trade table */}
      {loading ? (
        <div className="flex items-center justify-center h-48 rounded-lg border border-border-primary bg-bg-card">
          <p className="text-sm text-text-muted">Loading trades...</p>
        </div>
      ) : (
        <TradeTable data={trades ?? []} symbolFilter={symbol} />
      )}

      {/* Summary stats */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 rounded-lg border border-border-primary bg-bg-card p-4">
          <div>
            <p className="text-xs text-text-muted uppercase tracking-wider">
              Total Trades
            </p>
            <p className="font-mono-nums text-lg font-semibold text-text-primary mt-1">
              {summary.total}
            </p>
          </div>
          <div>
            <p className="text-xs text-text-muted uppercase tracking-wider">
              Win Rate
            </p>
            <p
              className={`font-mono-nums text-lg font-semibold mt-1 ${
                summary.winRate >= 50 ? "text-profit-green" : "text-loss-red"
              }`}
            >
              {formatPercentUnsigned(summary.winRate)}
            </p>
          </div>
          <div>
            <p className="text-xs text-text-muted uppercase tracking-wider">
              Total P&L
            </p>
            <p
              className={`font-mono-nums text-lg font-semibold mt-1 ${
                summary.totalPnl >= 0 ? "text-profit-green" : "text-loss-red"
              }`}
            >
              {formatCurrency(summary.totalPnl)}
            </p>
          </div>
          <div>
            <p className="text-xs text-text-muted uppercase tracking-wider">
              Avg P&L / Trade
            </p>
            <p
              className={`font-mono-nums text-lg font-semibold mt-1 ${
                summary.avgPnl >= 0 ? "text-profit-green" : "text-loss-red"
              }`}
            >
              {formatCurrency(summary.avgPnl)}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
