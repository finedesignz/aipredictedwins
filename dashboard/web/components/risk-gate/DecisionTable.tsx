"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { RiskDecision } from "@/types";
import { formatTimestamp } from "@/lib/format";
import Badge from "@/components/shared/Badge";
import DecisionDetail from "./DecisionDetail";

interface DecisionTableProps {
  data: RiskDecision[];
  filter?: "PROCEED" | "VETO" | null;
}

export default function DecisionTable({ data, filter }: DecisionTableProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const filtered = filter
    ? data.filter((d) => d.decision === filter)
    : data;

  if (filtered.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 rounded-lg border border-border-primary bg-bg-card">
        <p className="text-sm text-text-muted">
          No risk gate decisions recorded yet.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border-primary">
      <table className="w-full text-left" role="table">
        <thead>
          <tr className="border-b border-border-primary bg-bg-secondary">
            <th scope="col" className="w-8 px-2 py-3" />
            <th
              scope="col"
              className="px-4 py-3 text-xs font-medium uppercase tracking-wider text-text-muted"
            >
              Time
            </th>
            <th
              scope="col"
              className="px-4 py-3 text-xs font-medium uppercase tracking-wider text-text-muted"
            >
              Symbol
            </th>
            <th
              scope="col"
              className="px-4 py-3 text-xs font-medium uppercase tracking-wider text-text-muted"
            >
              Score
            </th>
            <th
              scope="col"
              className="px-4 py-3 text-xs font-medium uppercase tracking-wider text-text-muted"
            >
              Decision
            </th>
            <th
              scope="col"
              className="px-4 py-3 text-xs font-medium uppercase tracking-wider text-text-muted"
            >
              Vetoes
            </th>
            <th
              scope="col"
              className="px-4 py-3 text-xs font-medium uppercase tracking-wider text-text-muted"
            >
              Reasoning
            </th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((decision) => {
            const isExpanded = expandedId === decision.id;
            return (
              <>
                <tr
                  key={decision.id}
                  className="border-b border-border-subtle bg-bg-card hover:bg-bg-card-hover transition-colors cursor-pointer"
                  onClick={() =>
                    setExpandedId(isExpanded ? null : decision.id)
                  }
                  role="row"
                  aria-expanded={isExpanded}
                >
                  <td className="px-2 py-3 text-text-muted">
                    {isExpanded ? (
                      <ChevronDown className="h-4 w-4" aria-hidden="true" />
                    ) : (
                      <ChevronRight className="h-4 w-4" aria-hidden="true" />
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs text-text-muted font-mono-nums">
                      {formatTimestamp(decision.timestamp)}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="font-mono-nums text-sm font-medium text-text-primary">
                      {decision.symbol}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="font-mono-nums text-sm text-text-secondary">
                      {decision.confluence_score}/5
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <Badge
                      variant={
                        decision.decision === "PROCEED" ? "proceed" : "veto"
                      }
                    >
                      {decision.decision}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">
                    <span className="font-mono-nums text-sm text-text-secondary">
                      {decision.veto_count}/5
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-sm text-text-muted truncate max-w-xs block">
                      {decision.reasoning}
                    </span>
                  </td>
                </tr>
                {isExpanded && (
                  <tr key={`${decision.id}-detail`}>
                    <td colSpan={7} className="p-0">
                      <DecisionDetail decision={decision} />
                    </td>
                  </tr>
                )}
              </>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
