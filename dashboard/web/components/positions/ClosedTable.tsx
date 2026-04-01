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
import type { ClosedPosition } from "@/types";
import { formatCurrency, formatPercent, formatTimestamp, formatRelativeTime } from "@/lib/format";
import Badge from "@/components/shared/Badge";

const columnHelper = createColumnHelper<ClosedPosition>();

const columns = [
  columnHelper.accessor("symbol", {
    header: "Symbol",
    cell: (info) => (
      <span className="font-mono-nums text-sm font-medium text-text-primary">
        {info.getValue()}
      </span>
    ),
  }),
  columnHelper.accessor("side", {
    header: "Side",
    cell: (info) => (
      <Badge variant={info.getValue() === "long" ? "bullish" : "bearish"}>
        {info.getValue().toUpperCase()}
      </Badge>
    ),
  }),
  columnHelper.accessor("entry_price", {
    header: "Entry",
    cell: (info) => (
      <span className="font-mono-nums text-sm text-text-secondary">
        ${info.getValue().toFixed(2)}
      </span>
    ),
  }),
  columnHelper.accessor("exit_price", {
    header: "Exit",
    cell: (info) => (
      <span className="font-mono-nums text-sm text-text-secondary">
        ${info.getValue().toFixed(2)}
      </span>
    ),
  }),
  columnHelper.accessor("realized_pnl", {
    header: "P&L",
    cell: (info) => {
      const val = info.getValue();
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
  columnHelper.accessor("realized_pnl_percent", {
    header: "P&L %",
    cell: (info) => {
      const val = info.getValue();
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
  columnHelper.accessor("close_reason", {
    header: "Close Reason",
    cell: (info) => (
      <span className="text-sm text-text-muted">{info.getValue()}</span>
    ),
  }),
  columnHelper.accessor("closed_at", {
    header: "Closed",
    cell: (info) => (
      <span className="text-xs text-text-muted" title={formatTimestamp(info.getValue())}>
        {formatRelativeTime(info.getValue())}
      </span>
    ),
  }),
];

interface ClosedTableProps {
  data: ClosedPosition[];
}

export default function ClosedTable({ data }: ClosedTableProps) {
  const [sorting, setSorting] = useState<SortingState>([]);

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
        <p className="text-sm text-text-muted">No closed positions yet.</p>
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
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              className="border-b border-border-subtle bg-bg-card hover:bg-bg-card-hover transition-colors"
            >
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="px-4 py-3">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
