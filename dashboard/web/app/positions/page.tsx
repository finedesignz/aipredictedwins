"use client";

import { useState, useEffect } from "react";
import { useAPI } from "@/hooks/useAPI";
import type { Position, ClosedPosition } from "@/types";
import PositionCard from "@/components/positions/PositionCard";
import ClosedTable from "@/components/positions/ClosedTable";
import ErrorBanner from "@/components/shared/ErrorBanner";
import { useBotFilter } from "@/context/BotFilterContext";

type Tab = "open" | "closed";

export default function PositionsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("open");
  const { botParam } = useBotFilter();

  const { data: openPositions, loading: openLoading, error: openError, refetch: refetchOpen } = useAPI<Position[]>(
    `/api/positions/open?bot=${botParam}`,
    30000
  );
  const { data: closedPositions, loading: closedLoading, error: closedError, refetch: refetchClosed } =
    useAPI<ClosedPosition[]>(`/api/positions/closed?bot=${botParam}`);

  // Reconcile orphaned DB trades against Alpaca on mount.
  // Throttled to once per 5 minutes via sessionStorage to avoid hammering Alpaca on every navigation.
  useEffect(() => {
    const THROTTLE_KEY = "reconcile_last_run";
    const THROTTLE_MS = 5 * 60 * 1000;
    const last = Number(sessionStorage.getItem(THROTTLE_KEY) ?? 0);
    if (Date.now() - last < THROTTLE_MS) return;

    sessionStorage.setItem(THROTTLE_KEY, String(Date.now()));
    fetch("/api/positions/reconcile", { method: "POST", credentials: "same-origin" })
      .then((r) => r.json())
      .then((json) => {
        if ((json?.data?.reconciled ?? 0) > 0) {
          refetchOpen();
          refetchClosed();
        }
      })
      .catch(() => {/* silent — reconcile is best-effort */});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-text-primary">Positions</h1>

      <ErrorBanner error={openError ?? closedError} />

      {/* Tab toggle */}
      <div
        className="flex gap-1 rounded-lg bg-bg-secondary p-1 w-fit"
        role="tablist"
        aria-label="Position status tabs"
      >
        {(["open", "closed"] as Tab[]).map((tab) => (
          <button
            key={tab}
            role="tab"
            aria-selected={activeTab === tab}
            onClick={() => setActiveTab(tab)}
            className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
              activeTab === tab
                ? "bg-bg-card text-text-primary"
                : "text-text-muted hover:text-text-secondary"
            }`}
          >
            {tab === "open" ? "Open" : "Closed"}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div role="tabpanel">
        {activeTab === "open" && (
          <>
            {openPositions && openPositions.length > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {openPositions.map((pos) => (
                  <PositionCard key={pos.id} position={pos} />
                ))}
              </div>
            ) : (
              <div className="flex items-center justify-center h-48 rounded-lg border border-border-primary bg-bg-card">
                <p className="text-sm text-text-muted">
                  {openLoading
                    ? "Loading open positions..."
                    : "No open positions right now."}
                </p>
              </div>
            )}
          </>
        )}

        {activeTab === "closed" && (
          <>
            {closedLoading ? (
              <div className="flex items-center justify-center h-48 rounded-lg border border-border-primary bg-bg-card">
                <p className="text-sm text-text-muted">
                  Loading closed positions...
                </p>
              </div>
            ) : (
              <ClosedTable data={closedPositions ?? []} />
            )}
          </>
        )}
      </div>
    </div>
  );
}
