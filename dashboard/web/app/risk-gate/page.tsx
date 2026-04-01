"use client";

import { useState } from "react";
import { useAPI } from "@/hooks/useAPI";
import type { RiskDecision } from "@/types";
import DecisionTable from "@/components/risk-gate/DecisionTable";

type FilterType = "PROCEED" | "VETO" | null;

export default function RiskGatePage() {
  const [filter, setFilter] = useState<FilterType>(null);
  const { data: decisions, loading } = useAPI<RiskDecision[]>("/api/risk-gate");

  const counts = {
    all: decisions?.length ?? 0,
    proceed: decisions?.filter((d) => d.decision === "PROCEED").length ?? 0,
    veto: decisions?.filter((d) => d.decision === "VETO").length ?? 0,
  };

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-text-primary">
        Risk Gate Decisions
      </h1>

      <p className="text-sm text-text-secondary">
        Every trade candidate passes through a 5-analyst MiroFish risk panel.
        Click a row to see the full scenario analysis and individual votes.
      </p>

      {/* Filter chips */}
      <div className="flex gap-2" role="group" aria-label="Filter by decision">
        <button
          onClick={() => setFilter(null)}
          className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors border ${
            filter === null
              ? "border-accent-blue bg-accent-blue/15 text-accent-blue"
              : "border-border-primary text-text-muted hover:text-text-secondary hover:bg-bg-card-hover"
          }`}
        >
          All ({counts.all})
        </button>
        <button
          onClick={() => setFilter("PROCEED")}
          className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors border ${
            filter === "PROCEED"
              ? "border-profit-green bg-profit-green/15 text-profit-green"
              : "border-border-primary text-text-muted hover:text-text-secondary hover:bg-bg-card-hover"
          }`}
        >
          Proceed ({counts.proceed})
        </button>
        <button
          onClick={() => setFilter("VETO")}
          className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors border ${
            filter === "VETO"
              ? "border-loss-red bg-loss-red/15 text-loss-red"
              : "border-border-primary text-text-muted hover:text-text-secondary hover:bg-bg-card-hover"
          }`}
        >
          Veto ({counts.veto})
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-48 rounded-lg border border-border-primary bg-bg-card">
          <p className="text-sm text-text-muted">Loading decisions...</p>
        </div>
      ) : (
        <DecisionTable data={decisions ?? []} filter={filter} />
      )}
    </div>
  );
}
