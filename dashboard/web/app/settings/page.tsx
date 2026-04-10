"use client";

import { useAPI } from "@/hooks/useAPI";
import type { BotSettings } from "@/types";
import BotStatusComponent from "@/components/settings/BotStatus";
import ErrorBanner from "@/components/shared/ErrorBanner";

export default function SettingsPage() {
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
        <BotStatusComponent settings={settings} />
      )}
    </div>
  );
}
