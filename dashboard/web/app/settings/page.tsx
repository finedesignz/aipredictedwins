"use client";

import { useAPI } from "@/hooks/useAPI";
import type { BotSettings } from "@/types";
import BotStatusComponent from "@/components/settings/BotStatus";
import ErrorBanner from "@/components/shared/ErrorBanner";
import { formatRelativeTime } from "@/lib/format";

function Alarm({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-lg border border-loss-red bg-loss-red/10 p-4">
      <p className="text-sm font-semibold text-loss-red">{title}</p>
      <p className="mt-1 text-xs text-text-secondary break-all">{detail}</p>
    </div>
  );
}

/**
 * Phase 19 (RUN-01) — the three states that used to be SILENT.
 *
 * `manager_alive` is computed from heartbeat ABSENCE or STALENESS and never defaults
 * healthy: the container can serve this very page while NO BOTS ARE RUNNING AT ALL.
 * And config presence != delivery — a valid-LOOKING SES config still drops every alert
 * on an unverified identity, which is what `alerts_last_error` exposes.
 */
function RuntimeAlarms({ settings }: { settings: BotSettings }) {
  const h = settings.health;
  return (
    <div className="space-y-3">
      {!h.manager_alive && (
        <Alarm
          title="BotManager NOT RUNNING"
          detail={
            "No heartbeat " +
            (h.last_heartbeat
              ? `since ${formatRelativeTime(h.last_heartbeat)}.`
              : "has ever been recorded.") +
            " The dashboard is serving read-only while no bots are running."
          }
        />
      )}
      {!h.alerts_last_error && !h.alerts_configured && (
        <Alarm
          title="Alerts are NOT configured"
          detail="This system cannot tell you when it breaks."
        />
      )}
      {h.alerts_last_error && (
        <Alarm
          title="The last alert FAILED to send"
          detail={h.alerts_last_error}
        />
      )}
    </div>
  );
}

export default function SettingsPage() {
  // Settings are system-wide (not per-bot) — no botParam needed
  const { data: settings, loading, error } = useAPI<BotSettings>(
    "/api/settings",
    10000
  );

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-text-primary">Settings</h1>
      <p className="text-sm text-text-secondary">
        System health, bot status, and configuration. All values are read-only
        -- update configuration in the bot environment.
      </p>

      <ErrorBanner error={error} />

      {loading || !settings ? (
        <div className="space-y-4">
          {[1, 2, 3].map((n) => (
            <div
              key={n}
              className="h-36 rounded-lg bg-bg-card animate-pulse"
            />
          ))}
        </div>
      ) : (
        <>
          <RuntimeAlarms settings={settings} />
          <BotStatusComponent settings={settings} />
        </>
      )}
    </div>
  );
}
