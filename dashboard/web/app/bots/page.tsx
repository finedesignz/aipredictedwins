"use client";
import { useState, useCallback } from "react";
import { useAPI } from "@/hooks/useAPI";
import type { BotFull } from "@/types";
import BotCard from "@/components/bots/BotCard";
import BotDrawer from "@/components/bots/BotDrawer";

async function apiFetch(path: string, options: RequestInit = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

export default function BotsPage() {
  const { data: bots, loading, refetch } = useAPI<BotFull[]>("/api/bots", 30_000);
  const [editBot, setEditBot] = useState<BotFull | null | undefined>(undefined);
  const [open, setOpen] = useState(false);

  const openNew = () => { setEditBot(null); setOpen(true); };
  const openEdit = (bot: BotFull) => { setEditBot(bot); setOpen(true); };
  const close = () => setOpen(false);

  const handleSave = useCallback(async (data: Record<string, unknown>) => {
    if (editBot === null) {
      await apiFetch("/api/bots", { method: "POST", body: JSON.stringify(data) });
    } else if (editBot) {
      const patch = { ...data };
      if (!patch.alpaca_api_key) delete patch.alpaca_api_key;
      if (!patch.alpaca_secret_key) delete patch.alpaca_secret_key;
      await apiFetch(`/api/bots/${editBot.bot_id}`, { method: "PUT", body: JSON.stringify(patch) });
    }
    refetch();
  }, [editBot, refetch]);

  const handleToggle = useCallback(async (bot: BotFull, enabled: boolean) => {
    const path = enabled ? `/api/bots/${bot.bot_id}/enable` : `/api/bots/${bot.bot_id}/disable`;
    await apiFetch(path, { method: "POST" });
    refetch();
  }, [refetch]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">Bots</h1>
        <button onClick={openNew} className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded">+ Add Bot</button>
      </div>
      {loading ? (
        <div className="flex items-center justify-center h-48 rounded-lg border border-border-primary bg-bg-card">
          <p className="text-sm text-text-muted">Loading bots...</p>
        </div>
      ) : bots && bots.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {bots.map((bot) => <BotCard key={bot.bot_id} bot={bot} onEdit={openEdit} onToggle={handleToggle} />)}
        </div>
      ) : (
        <div className="flex items-center justify-center h-48 rounded-lg border border-border-primary bg-bg-card">
          <p className="text-sm text-text-muted">No bots configured. Click &quot;+ Add Bot&quot; to get started.</p>
        </div>
      )}
      <BotDrawer bot={editBot ?? null} open={open} onClose={close} onSave={handleSave} />
    </div>
  );
}
