"use client";

import {
  Activity,
  Clock,
  Database,
  Terminal,
  CheckCircle,
  XCircle,
} from "lucide-react";
import type { BotSettings } from "@/types";
import { formatDuration, formatRelativeTime } from "@/lib/format";
import Badge from "@/components/shared/Badge";

interface BotStatusProps {
  settings: BotSettings;
}

function HealthIndicator({
  label,
  healthy,
  icon: Icon,
  detail,
}: {
  label: string;
  healthy: boolean;
  icon: typeof Activity;
  detail?: string;
}) {
  return (
    <div className="flex items-center justify-between py-2">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-text-muted" aria-hidden="true" />
        <span className="text-sm text-text-secondary">{label}</span>
      </div>
      <div className="flex items-center gap-2">
        {detail && (
          <span className="text-xs text-text-muted font-mono-nums">{detail}</span>
        )}
        {healthy ? (
          <CheckCircle className="h-4 w-4 text-profit-green" aria-label={`${label}: healthy`} />
        ) : (
          <XCircle className="h-4 w-4 text-loss-red" aria-label={`${label}: unhealthy`} />
        )}
      </div>
    </div>
  );
}

function ProgressBar({
  label,
  current,
  target,
  format,
}: {
  label: string;
  current: number;
  target: number;
  format?: (n: number) => string;
}) {
  const pct = Math.min((current / target) * 100, 100);
  const fmt = format || ((n: number) => String(n));

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span className="text-text-secondary">{label}</span>
        <span className="font-mono-nums text-text-muted">
          {fmt(current)} / {fmt(target)}
        </span>
      </div>
      <div className="h-2 rounded-full bg-bg-secondary overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${
            pct >= 100 ? "bg-profit-green" : "bg-accent-blue"
          }`}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={current}
          aria-valuemin={0}
          aria-valuemax={target}
          aria-label={`${label}: ${fmt(current)} of ${fmt(target)}`}
        />
      </div>
    </div>
  );
}

export default function BotStatus({ settings }: BotStatusProps) {
  return (
    <div className="space-y-6">
      {/* Status card */}
      <div className="rounded-lg border border-border-primary bg-bg-card p-4">
        <h3 className="text-sm font-medium text-text-secondary mb-4">
          Bot Status
        </h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div>
            <p className="text-xs text-text-muted uppercase tracking-wider">State</p>
            <Badge variant={settings.running ? "proceed" : "veto"}>
              {settings.running ? "RUNNING" : "STOPPED"}
            </Badge>
          </div>
          <div>
            <p className="text-xs text-text-muted uppercase tracking-wider">Uptime</p>
            <p className="font-mono-nums text-sm text-text-primary mt-1">
              {formatDuration(settings.uptime_seconds)}
            </p>
          </div>
          <div>
            <p className="text-xs text-text-muted uppercase tracking-wider">Cycles</p>
            <p className="font-mono-nums text-sm text-text-primary mt-1">
              {settings.cycle_count}
            </p>
          </div>
          <div>
            <p className="text-xs text-text-muted uppercase tracking-wider">Last Cycle</p>
            <p className="text-sm text-text-primary mt-1">
              {settings.last_cycle
                ? formatRelativeTime(settings.last_cycle)
                : "--"}
            </p>
          </div>
        </div>
      </div>

      {/* System health */}
      <div className="rounded-lg border border-border-primary bg-bg-card p-4">
        <h3 className="text-sm font-medium text-text-secondary mb-3">
          System Health
        </h3>
        <div className="divide-y divide-border-subtle">
          <HealthIndicator
            label="Claude CLI"
            healthy={settings.health.claude_cli}
            icon={Terminal}
          />
          <HealthIndicator
            label="Alpaca API"
            healthy={settings.health.alpaca_api}
            icon={Activity}
          />
          <HealthIndicator
            label="SQLite DB"
            healthy={settings.health.sqlite_db}
            icon={Database}
            detail={`${settings.health.db_size_mb.toFixed(1)} MB`}
          />
        </div>
      </div>

      {/* Paper trading progress */}
      <div className="rounded-lg border border-border-primary bg-bg-card p-4">
        <h3 className="text-sm font-medium text-text-secondary mb-4">
          Paper Trading Progress
        </h3>
        <div className="space-y-4">
          <ProgressBar
            label="Trades"
            current={settings.paper_trades_completed}
            target={settings.paper_trades_target}
          />
          <ProgressBar
            label="Win Rate"
            current={settings.win_rate}
            target={settings.win_rate_target}
            format={(n) => `${n.toFixed(1)}%`}
          />
          <ProgressBar
            label="Equity"
            current={settings.equity}
            target={settings.equity_target}
            format={(n) => `$${n.toLocaleString()}`}
          />
        </div>
      </div>

      {/* Config values */}
      <div className="rounded-lg border border-border-primary bg-bg-card p-4">
        <h3 className="text-sm font-medium text-text-secondary mb-3">
          Configuration
        </h3>
        <div className="space-y-2">
          {Object.entries(settings.config).map(([key, value]) => (
            <div key={key} className="flex items-center justify-between py-1.5">
              <span className="text-sm text-text-muted">{key}</span>
              <span className="font-mono-nums text-sm text-text-secondary">
                {String(value)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
