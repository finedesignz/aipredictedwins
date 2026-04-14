"use client";

import type { RiskDecision } from "@/types";

interface DecisionDetailProps {
  decision: RiskDecision;
}

export default function DecisionDetail({ decision }: DecisionDetailProps) {
  const hasDetail =
    decision.risk_assessment || decision.veto_reason || decision.proposed_side;

  if (!hasDetail) {
    return (
      <div className="bg-bg-secondary p-4">
        <p className="text-sm text-text-muted">No additional detail recorded.</p>
      </div>
    );
  }

  return (
    <div className="bg-bg-secondary p-4 space-y-4">
      {decision.proposed_side && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-wider text-text-muted mb-1">
            Proposed Side
          </h4>
          <p className="text-sm text-text-secondary">{decision.proposed_side}</p>
        </div>
      )}

      {decision.risk_assessment && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-wider text-text-muted mb-1">
            Risk Assessment
          </h4>
          <p className="text-sm text-text-secondary whitespace-pre-wrap">{decision.risk_assessment}</p>
        </div>
      )}

      {decision.veto_reason && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-wider text-text-muted mb-1">
            Veto Reason
          </h4>
          <p className="text-sm text-text-secondary whitespace-pre-wrap">{decision.veto_reason}</p>
        </div>
      )}
    </div>
  );
}
