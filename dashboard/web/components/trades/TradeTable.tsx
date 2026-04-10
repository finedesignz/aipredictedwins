"use client";

import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
  type ColumnFiltersState,
} from "@tanstack/react-table";
import { useState } from "react";
import { ArrowUpDown } from "lucide-react";
import type { Trade } from "@/types";
import {
  formatCurrency,
  formatPercent,
  formatTimestamp,
} from "@/lib/format";
import Badge from "@/components/shared/Badge";

const columnHelper = createColumnHelper<Trade>();

const columns = [
  columnHelper.accessor("timestamp", {
    header: "Time",
    cell: (info) => (
      <span className="text-xs text-text-muted font-mono-nums">
        {formatTimestamp(info.getValue())}
      </span>
    ),
  }),
  columnHelper.accessor("symbol", {
    header: "Symbol",
    cell: (info) => (
      <span className="font-mono-nums text-sm font-medium text-text-primary">
        {info.getValue()}
      </span>
    ),
  }),
  columnHelper.accessor("confluence_score", {
    header: "Score",
    cell: (info) => (
      <span className="font-mono-nums text-sm text-text-secondary">
        {info.getValue()}/5
      </span>
    ),
  }),
  columnHelper.accessor("entry_price", {
    header: "Entry",
    cell: (info) => {
      const val = info.getValue();
      return val != null ? (
        <span className="font-mono-nums text-sm text-text-secondary">${val.toFixed(2)}</span>
      ) : <span className="text-xs text-text-muted">--</span>;
    },
  }),
  columnHelper.accessor("exit_price", {
    header: "Exit",
    cell: (info) => {
      const val = info.getValue();
      return val != null ? (
        <span className="font-mono-nums text-sm text-text-secondary">${val.toFixed(2)}</span>
      ) : (
        <span className="text-xs text-text-muted">--</span>
      );
    },
  }),
  columnHelper.accessor("pnl", {
    header: "P&L",
    cell: (info) => {
      const val = info.getValue();
      if (val === null) return <span className="text-xs text-text-muted">--</span>;
      return (
        <span
          className={`font-mono-nums text-sm font-medium ${
            val >= 0 ? "text-profit-green" : "text-loss-red"
          }`}
        >
          {formatCurrency(val)}
        </span>
      );
    },
  }),
  columnHelper.accessor("pnl_percent", {
    header: "P&L %",
    cell: (info) => {
      const val = info.getValue();
      if (val === null) return <span className="text-xs text-text-muted">--</span>;
      return (
        <span
          className={`font-mono-nums text-sm ${
            val >= 0 ? "text-profit-green" : "text-loss-red"
          }`}
        >
          {formatPercent(val)}
        </span>
      );
    },
  }),
  columnHelper.accessor("status", {
    header: "Status",
    cell: (info) => {
      const status = info.getValue() ?? "";
      const variant =
        status === "open" ? "open" : status === "closed" ? "closed" : "neutral";
      return <Badge variant={variant}>{status.toUpperCase() || "—"}</Badge>;
    },
  }),
  columnHelper.accessor("bot", {
    header: "Bot",
    cell: (info) => {
      const val = info.getValue();
      if (!val) return <span className="text-xs text-text-muted">--</span>;
      const isB = val.includes("B");
      return (
        <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${isB ? "bg-warning-amber/15 text-warning-amber" : "bg-accent-blue/15 text-accent-blue"}`}>
          {isB ? "B" : "A"}
        </span>
      );
    },
  }),
];

interface TradeTableProps {
  data: Trade[];
  symbolFilter?: string;
}

export default function TradeTable({ data, symbolFilter }: TradeTableProps) {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "timestamp", desc: true },
  ]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>(() => {
    if (symbolFilter) {
      return [{ id: "symbol", value: symbolFilter }];
    }
    return [];
  });

  const table = useReactTable({
    data,
    columns,
    state: { sorting, columnFilters },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 rounded-lg border border-border-primary bg-bg-card">
        <p className="text-sm text-text-muted">
          No trades yet. The bot will place trades when it finds signals with sufficient confluence.
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
            const pnl = row.original.pnl;
            let rowBg = "bg-bg-card";
            if (pnl !== null) {
              rowBg = pnl >= 0 ? "bg-profit-green-bg/30" : "bg-loss-red-bg/30";
            }
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
