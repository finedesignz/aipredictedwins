"use client";

import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from "@tanstack/react-table";
import { useState } from "react";
import { ArrowUpDown } from "lucide-react";
import type { Signal } from "@/types";
import Badge from "@/components/shared/Badge";

const columnHelper = createColumnHelper<Signal>();

function signalBadge(signal: "bullish" | "bearish" | "neutral") {
  return <Badge variant={signal}>{signal.toUpperCase()}</Badge>;
}

const columns = [
  columnHelper.accessor("symbol", {
    header: "Symbol",
    cell: (info) => (
      <span className="font-mono-nums text-sm font-semibold text-text-primary">
        {info.getValue()}
      </span>
    ),
  }),
  columnHelper.accessor("ema_signal", {
    header: "EMA(9/21)",
    cell: (info) => signalBadge(info.getValue()),
  }),
  columnHelper.accessor("adx_value", {
    header: "ADX",
    cell: (info) => {
      const adxSignal = info.row.original.adx_signal;
      const arrow = adxSignal === "bullish" ? " ↑" : adxSignal === "bearish" ? " ↓" : "";
      const arrowColor =
        adxSignal === "bullish"
          ? "text-profit-green"
          : adxSignal === "bearish"
          ? "text-loss-red"
          : "text-text-muted";
      return (
        <span className="font-mono-nums text-sm text-text-secondary">
          {info.getValue().toFixed(1)}
          <span className={arrowColor}>{arrow}</span>
        </span>
      );
    },
  }),
  columnHelper.accessor("rsi_value", {
    header: "RSI",
    cell: (info) => {
      const val = info.getValue();
      const color =
        val > 70
          ? "text-loss-red"
          : val < 30
          ? "text-profit-green"
          : "text-text-secondary";
      return (
        <span className={`font-mono-nums text-sm ${color}`}>
          {val.toFixed(1)}
        </span>
      );
    },
  }),
  columnHelper.accessor("volume_spike", {
    header: "Volume",
    cell: (info) => (
      <Badge variant={info.getValue() ? "bullish" : "neutral"}>
        {info.getValue() ? "SPIKE" : "NORMAL"}
      </Badge>
    ),
  }),
  columnHelper.accessor("vwap_signal", {
    header: "VWAP",
    cell: (info) => signalBadge(info.getValue()),
  }),
  columnHelper.accessor("confluence_score", {
    header: "Score",
    cell: (info) => {
      const score = info.getValue();
      const color =
        score >= 4
          ? "text-profit-green"
          : score >= 3
          ? "text-warning-amber"
          : "text-text-muted";
      return (
        <span className={`font-mono-nums text-sm font-bold ${color}`}>
          {score}/5
        </span>
      );
    },
  }),
  columnHelper.accessor("action", {
    header: "Action",
    cell: (info) => {
      const action = info.getValue();
      const variant =
        action === "BUY" ? "proceed" : action === "WATCH" ? "paper" : "closed";
      return <Badge variant={variant}>{action}</Badge>;
    },
  }),
];

interface SignalTableProps {
  data: Signal[];
}

export default function SignalTable({ data }: SignalTableProps) {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "confluence_score", desc: true },
  ]);

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 rounded-lg border border-border-primary bg-bg-card">
        <p className="text-sm text-text-muted">
          No signal data available. Waiting for the next scan cycle.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border-primary">
      <table className="w-full text-left" role="table">
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id} className="border-b border-border-primary bg-bg-secondary">
              {headerGroup.headers.map((header) => (
                <th
                  key={header.id}
                  className="px-4 py-3 text-xs font-medium uppercase tracking-wider text-text-muted cursor-pointer select-none hover:text-text-secondary"
                  onClick={header.column.getToggleSortingHandler()}
                  scope="col"
                >
                  <div className="flex items-center gap-1">
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    <ArrowUpDown className="h-3 w-3" aria-hidden="true" />
                  </div>
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => {
            const score = row.original.confluence_score;
            const rowBg =
              score >= 3
                ? "bg-profit-green-bg/20"
                : score >= 2
                ? "bg-warning-amber-bg/10"
                : "bg-bg-card";
            return (
              <tr
                key={row.id}
                className={`border-b border-border-subtle ${rowBg} hover:bg-bg-card-hover transition-colors`}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-4 py-3">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
