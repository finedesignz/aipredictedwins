"use client";

import type { RiskDecision } from "@/types";
import Badge from "@/components/shared/Badge";

interface DecisionDetailProps {
  decision: RiskDecision;
}

function likelihoodColor(level: "high" | "medium" | "low"): string {
  if (level === "high") return "text-loss-red";
  if (level === "medium") return "text-warning-amber";
  return "text-text-muted";
}

export default function DecisionDetail({ decision }: DecisionDetailProps) {
  return (
    <div className="bg-bg-secondary p-4 space-y-4">
      <div>
        <h4 className="text-xs font-medium uppercase tracking-wider text-text-muted mb-2">
          Reasoning
        </h4>
        <p className="text-sm text-text-secondary">{decision.reasoning}</p>
      </div>

      {decision.scenarios.length > 0 && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-wider text-text-muted mb-2">
            Analyst Scenarios
          </h4>
          <div className="space-y-3">
            {decision.scenarios.map((scenario, idx) => (
              <div
                key={idx}
                className="rounded-md border border-border-subtle bg-bg-card p-3"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-text-secondary">
                    {scenario.analyst}
                  </span>
                  <Badge variant={scenario.vote === "PROCEED" ? "proceed" : "veto"}>
                    {scenario.vote}
                  </Badge>
                </div>
                <p className="text-sm text-text-secondary mb-2">
                  {scenario.scenario}
                </p>
                <div className="flex gap-4 text-xs">
                  <span>
                    Likelihood:{" "}
                    <span className={likelihoodColor(scenario.likelihood)}>
                      {scenario.likelihood}
                    </span>
                  </span>
                  <span>
                    Impact:{" "}
                    <span className={likelihoodColor(scenario.impact)}>
                      {scenario.impact}
                    </span>
                  </span>
                </div>
                {scenario.reasoning && (
                  <p className="text-xs text-text-muted mt-1">{scenario.reasoning}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
