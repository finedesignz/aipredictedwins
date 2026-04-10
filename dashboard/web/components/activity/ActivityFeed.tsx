"use client";

import {
  ArrowUpRight,
  Search,
  CheckCircle,
  AlertTriangle,
  ShieldAlert,
  BarChart3,
  RefreshCw,
} from "lucide-react";
import type { ActivityEvent } from "@/types";
import { formatTime } from "@/lib/format";
import { useAPI } from "@/hooks/useAPI";

const eventConfig: Record<
  string,
  { icon: typeof Search; colorClass: string }
> = {
  scan_complete: { icon: Search, colorClass: "text-text-muted" },
  trade_placed: { icon: ArrowUpRight, colorClass: "text-profit-green" },
  trade_closed: { icon: CheckCircle, colorClass: "text-accent-blue" },
  risk_decision: { icon: ShieldAlert, colorClass: "text-warning-amber" },
  cycle_complete: { icon: RefreshCw, colorClass: "text-text-secondary" },
  error: { icon: AlertTriangle, colorClass: "text-loss-red" },
};

const defaultConfig = { icon: BarChart3, colorClass: "text-text-muted" };

function ActivityEntry({ event }: { event: ActivityEvent }) {
  const config = eventConfig[event.type] || defaultConfig;
  const Icon = config.icon;

  return (
    <div className="flex gap-3 py-2 px-3 rounded-md hover:bg-bg-card-hover transition-colors">
      <div className={`mt-0.5 shrink-0 ${config.colorClass}`}>
        <Icon className="h-4 w-4" aria-hidden="true" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm text-text-secondary leading-snug">
          {event.message}
        </p>
        {event.detail && (
          <p className="text-xs text-text-muted mt-0.5">{event.detail}</p>
        )}
      </div>
      <span className="font-mono-nums text-xs text-text-muted shrink-0">
        {formatTime(event.timestamp)}
      </span>
    </div>
  );
}

interface ActivityFeedProps {
  fallbackEvents?: ActivityEvent[];
}

export default function ActivityFeed({ fallbackEvents }: ActivityFeedProps) {
  // Poll every 10s instead of SSE — SSE breaks over Cloudflare QUIC (HTTP/3)
  const { data, loading, error } = useAPI<ActivityEvent[]>("/api/activity/recent", 10_000);

  const events: ActivityEvent[] = data ?? fallbackEvents ?? [];
  const connected = !error && !loading;

  return (
    <div className="rounded-lg border border-border-primary bg-bg-card flex flex-col h-full max-h-[480px]">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-primary">
        <h3 className="text-sm font-medium text-text-secondary">
          Activity Feed
        </h3>
        <div className="flex items-center gap-2">
          <span
            className={`h-2 w-2 rounded-full ${
              connected ? "bg-profit-green" : "bg-loss-red"
            }`}
            title={connected ? "Live" : "Reconnecting..."}
            aria-label={connected ? "Live" : "Reconnecting..."}
          />
          {error && (
            <span className="text-xs text-loss-red">Reconnecting...</span>
          )}
        </div>
      </div>
      <div
        className="flex-1 overflow-y-auto divide-y divide-border-subtle"
        role="log"
        aria-live="polite"
        aria-label="Live activity feed"
      >
        {events.length === 0 ? (
          <div className="flex items-center justify-center h-full py-12">
            <p className="text-sm text-text-muted">
              {loading ? "Loading..." : "No recent activity."}
            </p>
          </div>
        ) : (
          events.map((event) => (
            <ActivityEntry key={event.id} event={event} />
          ))
        )}
      </div>
    </div>
  );
}
