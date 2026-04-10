"use client";

import { useAPI } from "@/hooks/useAPI";
import type { Signal } from "@/types";
import SignalTable from "@/components/signals/SignalTable";
import ErrorBanner from "@/components/shared/ErrorBanner";
import { formatRelativeTime } from "@/lib/format";

export default function SignalsPage() {
  const { data: signals, loading, error } = useAPI<Signal[]>("/api/signals", 30000);

  const lastScanned =
    signals && signals.length > 0 ? signals[0].scanned_at : null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-text-primary">
          Technical Signals
        </h1>
        {lastScanned && (
          <span className="text-xs text-text-muted">
            Last scan: {formatRelativeTime(lastScanned)}
          </span>
        )}
      </div>

      <p className="text-sm text-text-secondary">
        Current technical scanner output across the 8-asset universe. Assets
        with 3+ bullish indicators are candidates for the risk gate.
      </p>

      <ErrorBanner error={error} />

      {loading ? (
        <div className="flex items-center justify-center h-48 rounded-lg border border-border-primary bg-bg-card">
          <p className="text-sm text-text-muted">Loading signals...</p>
        </div>
      ) : (
        <SignalTable data={signals ?? []} />
      )}
    </div>
  );
}
