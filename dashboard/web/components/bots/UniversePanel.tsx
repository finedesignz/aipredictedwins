"use client";

import { useAPI } from "@/hooks/useAPI";
import Badge from "@/components/shared/Badge";
import ErrorBanner from "@/components/shared/ErrorBanner";
import type { BlockedSymbol, BotUniverse } from "@/types";

interface Props {
  botId: string;
}

// Reason precedence — mirrors src/effective_universe (quarantined > off_universe
// > meme > untradeable). Used ONLY for display ordering; never to decide state.
const REASON_ORDER: Record<BlockedSymbol["reason"], number> = {
  quarantined: 0,
  off_universe: 1,
  meme: 2,
  untradeable: 3,
};

export default function UniversePanel({ botId }: Props) {
  const { data, loading, error } = useAPI<BotUniverse>(
    `/api/bots/${botId}/universe`,
    30_000
  );

  if (error) return <ErrorBanner error={error} />;
  if (loading || !data) {
    return <div className="text-xs text-text-muted">Universe…</div>;
  }

  const blocked = [...data.blocked].sort(
    (a, b) => REASON_ORDER[a.reason] - REASON_ORDER[b.reason]
  );
  // Render-only lookup: the server already decided WHICH symbols leak.
  const bySymbol: Record<string, BlockedSymbol> = {};
  for (const b of data.blocked) bySymbol[b.symbol] = b;
  const leakDetail = data.leak
    .map((sym) => {
      const b = bySymbol[sym];
      return b
        ? `${sym} (${b.open_positions} open, ${b.recent_trades} in 30d)`
        : sym;
    })
    .join(", ");

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs">
        <span className="text-text-primary font-medium">Universe</span>
        <span className="text-text-muted">
          {data.effective.length} of {data.allowlist.length} tradeable
        </span>
      </div>

      {data.leak.length > 0 && (
        <div
          role="alert"
          className="rounded-lg border border-loss-red/40 bg-loss-red/10 px-4 py-3"
        >
          <p className="text-sm text-loss-red">
            LEAK: {leakDetail} traded outside this bot&apos;s universe
          </p>
        </div>
      )}

      {data.starvation && (
        <div
          role="alert"
          className="rounded-lg border border-warning-amber/40 bg-warning-amber/10 px-4 py-3"
        >
          <p className="text-sm text-warning-amber">
            No tradeable symbols — every symbol is blocked. This bot cannot enter a
            position.
          </p>
        </div>
      )}

      <div className="flex flex-wrap gap-1.5">
        {data.effective.map((sym) => (
          <Badge key={sym} variant="proceed">
            {sym}
          </Badge>
        ))}
      </div>

      {blocked.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
          {blocked.map((b) => (
            <span key={b.symbol} className="inline-flex items-center gap-1">
              <Badge
                variant={
                  b.reason === "meme" || b.reason === "untradeable"
                    ? "neutral"
                    : "veto"
                }
                className="line-through"
              >
                {b.symbol}
              </Badge>
              <span className="text-[10px] text-text-muted">{b.reason}</span>
            </span>
          ))}
        </div>
      )}

      {data.exposure_loaded === false && (
        <p className="text-[10px] text-text-muted">
          leak check unavailable (trade-history query failed) — an empty leak list
          here means UNKNOWN, not clear
        </p>
      )}
      {data.shadow_sets_loaded === false && (
        <p className="text-[10px] text-text-muted">
          shadow deny-lists (meme / untradeable) unavailable in this process — the
          tradeable count may be optimistic
        </p>
      )}
      {data.shadow_applied === false && (
        <p className="text-[10px] text-text-muted">
          meme / untradeable filters do not apply to the {data.strategy} strategy
        </p>
      )}
    </div>
  );
}
