"use client";
import type { BotFull } from "@/types";
import UniversePanel from "@/components/bots/UniversePanel";

interface Props {
  bot: BotFull;
  onEdit: (bot: BotFull) => void;
  onToggle: (bot: BotFull, enabled: boolean) => void;
}

export default function BotCard({ bot, onEdit, onToggle }: Props) {
  const dot = bot.status === "running" ? "bg-green-400" : bot.status === "error" ? "bg-red-400" : "bg-slate-500";
  return (
    <div className="rounded-xl border border-border-primary bg-bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`w-2.5 h-2.5 rounded-full ${dot}`} />
          <span className="font-medium text-sm">{bot.label}</span>
          <span className="text-xs text-text-muted font-mono bg-bg-muted px-1.5 py-0.5 rounded">{bot.bot_id}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => onToggle(bot, !bot.enabled)}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${bot.enabled ? "bg-blue-500" : "bg-slate-600"}`}
          >
            <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${bot.enabled ? "translate-x-4" : "translate-x-1"}`} />
          </button>
          <button onClick={() => onEdit(bot)} className="text-xs text-text-muted hover:text-text-primary px-2 py-1 rounded border border-border-primary">Edit</button>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs text-text-muted">
        <div>Kelly: <span className="text-text-primary">{bot.kelly_fraction}</span></div>
        <div>Min confluence: <span className="text-text-primary">{bot.min_confluence}/5</span></div>
        <div>Hard stop: <span className="text-text-primary">{(bot.hard_stop_pct * 100).toFixed(0)}%</span></div>
        <div>Soft stop: <span className="text-text-primary">{(bot.soft_stop_pct * 100).toFixed(0)}%</span></div>
        <div>RSI ceiling: <span className="text-text-primary">{bot.rsi_ceiling}</span></div>
        <div>Max position: <span className="text-text-primary">{(bot.max_position_pct * 100).toFixed(0)}%</span></div>
      </div>
      <UniversePanel botId={bot.bot_id} />
      {bot.status === "error" && bot.status_detail && (
        <div className="text-xs text-red-400 bg-red-900/20 rounded p-2">{bot.status_detail}</div>
      )}
    </div>
  );
}
