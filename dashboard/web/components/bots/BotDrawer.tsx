"use client";
import { useState, useEffect, FormEvent } from "react";
import type { BotFull } from "@/types";
import { X } from "lucide-react";

interface Props {
  bot: BotFull | null;
  open: boolean;
  onClose: () => void;
  onSave: (data: Record<string, unknown>) => Promise<void>;
}

function SliderField({
  label,
  name,
  value,
  min,
  max,
  step,
  display,
  onChange,
}: {
  label: string;
  name: string;
  value: number;
  min: number;
  max: number;
  step: number;
  display: (v: number) => string;
  onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <label className="text-xs text-text-muted">{label}</label>
        <span className="text-xs font-mono text-text-primary">{display(value)}</span>
      </div>
      <input
        type="range"
        name={name}
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full accent-blue-500"
      />
    </div>
  );
}

function TextField({
  label,
  name,
  value,
  onChange,
  type = "text",
  placeholder,
}: {
  label: string;
  name: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
}) {
  return (
    <div className="space-y-1">
      <label className="text-xs text-text-muted">{label}</label>
      <input
        type={type}
        name={name}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-border-primary bg-bg-muted px-3 py-1.5 text-sm text-text-primary focus:border-blue-500 focus:outline-none"
      />
    </div>
  );
}

interface FormState {
  bot_id: string;
  label: string;
  alpaca_api_key: string;
  alpaca_secret_key: string;
  kelly_fraction: number;
  min_confluence: number;
  hard_stop_pct: number;
  soft_stop_pct: number;
  rsi_ceiling: number;
  max_position_pct: number;
  crypto_universe: string;
  skip_risk_gate: boolean;
}

function defaultForm(bot: BotFull | null): FormState {
  if (!bot) {
    return {
      bot_id: "",
      label: "",
      alpaca_api_key: "",
      alpaca_secret_key: "",
      kelly_fraction: 0.25,
      min_confluence: 3,
      hard_stop_pct: -0.04,
      soft_stop_pct: -0.02,
      rsi_ceiling: 70,
      max_position_pct: 0.05,
      crypto_universe: "BTC,ETH,SOL,XRP,ADA,AVAX,DOT,LINK",
      skip_risk_gate: false,
    };
  }
  return {
    bot_id: bot.bot_id,
    label: bot.label,
    alpaca_api_key: "",
    alpaca_secret_key: "",
    kelly_fraction: bot.kelly_fraction,
    min_confluence: bot.min_confluence,
    hard_stop_pct: bot.hard_stop_pct,
    soft_stop_pct: bot.soft_stop_pct,
    rsi_ceiling: bot.rsi_ceiling,
    max_position_pct: bot.max_position_pct,
    crypto_universe: bot.crypto_universe,
    skip_risk_gate: bot.skip_risk_gate,
  };
}

export default function BotDrawer({ bot, open, onClose, onSave }: Props) {
  const isCreate = bot === null;
  const [form, setForm] = useState<FormState>(() => defaultForm(bot));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setForm(defaultForm(bot));
      setError(null);
    }
  }, [open, bot]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const handleSubmit = async (e?: FormEvent) => {
    e?.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSave({ ...form });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/50"
        onClick={onClose}
        aria-hidden="true"
      />
      {/* Drawer */}
      <div className="fixed inset-y-0 right-0 z-50 w-full max-w-md bg-bg-card border-l border-border-primary shadow-xl flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border-primary">
          <h2 className="text-sm font-semibold text-text-primary">
            {isCreate ? "Add Bot" : `Edit ${bot?.label ?? "Bot"}`}
          </h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-text-muted hover:text-text-primary hover:bg-bg-muted"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {isCreate && (
            <TextField
              label="Bot ID (unique slug, e.g. bot-c)"
              name="bot_id"
              value={form.bot_id}
              onChange={(v) => set("bot_id", v)}
              placeholder="bot-c"
            />
          )}
          <TextField
            label="Label"
            name="label"
            value={form.label}
            onChange={(v) => set("label", v)}
            placeholder="Bot C"
          />
          <TextField
            label={`Alpaca API Key${isCreate ? "" : " (leave blank to keep current)"}`}
            name="alpaca_api_key"
            value={form.alpaca_api_key}
            onChange={(v) => set("alpaca_api_key", v)}
            type="password"
            placeholder={isCreate ? "PK..." : "••••••••"}
          />
          <TextField
            label={`Alpaca Secret Key${isCreate ? "" : " (leave blank to keep current)"}`}
            name="alpaca_secret_key"
            value={form.alpaca_secret_key}
            onChange={(v) => set("alpaca_secret_key", v)}
            type="password"
            placeholder={isCreate ? "secret..." : "••••••••"}
          />

          <SliderField
            label="Kelly Fraction"
            name="kelly_fraction"
            value={form.kelly_fraction}
            min={0.1}
            max={1.0}
            step={0.05}
            display={(v) => v.toFixed(2)}
            onChange={(v) => set("kelly_fraction", v)}
          />
          <SliderField
            label="Min Confluence (out of 5)"
            name="min_confluence"
            value={form.min_confluence}
            min={1}
            max={5}
            step={1}
            display={(v) => `${v}/5`}
            onChange={(v) => set("min_confluence", v)}
          />
          <SliderField
            label="Hard Stop"
            name="hard_stop_pct"
            value={form.hard_stop_pct}
            min={-0.15}
            max={-0.03}
            step={0.01}
            display={(v) => `${(v * 100).toFixed(0)}%`}
            onChange={(v) => set("hard_stop_pct", v)}
          />
          <SliderField
            label="Soft Stop"
            name="soft_stop_pct"
            value={form.soft_stop_pct}
            min={-0.10}
            max={-0.01}
            step={0.01}
            display={(v) => `${(v * 100).toFixed(0)}%`}
            onChange={(v) => set("soft_stop_pct", v)}
          />
          <SliderField
            label="RSI Ceiling"
            name="rsi_ceiling"
            value={form.rsi_ceiling}
            min={50}
            max={80}
            step={1}
            display={(v) => String(v)}
            onChange={(v) => set("rsi_ceiling", v)}
          />
          <SliderField
            label="Max Position Size"
            name="max_position_pct"
            value={form.max_position_pct}
            min={0.01}
            max={0.10}
            step={0.01}
            display={(v) => `${(v * 100).toFixed(0)}%`}
            onChange={(v) => set("max_position_pct", v)}
          />

          <TextField
            label="Crypto Universe (comma-separated)"
            name="crypto_universe"
            value={form.crypto_universe}
            onChange={(v) => set("crypto_universe", v)}
            placeholder="BTC,ETH,SOL,XRP"
          />

          <div className="flex items-center gap-3">
            <input
              id="skip_risk_gate"
              type="checkbox"
              checked={form.skip_risk_gate}
              onChange={(e) => set("skip_risk_gate", e.target.checked)}
              className="accent-blue-500"
            />
            <label htmlFor="skip_risk_gate" className="text-xs text-text-muted">
              Skip risk gate (disable MiroFish veto)
            </label>
          </div>

          {error && (
            <div className="text-xs text-red-400 bg-red-900/20 rounded p-2">{error}</div>
          )}
        </form>

        <div className="px-5 py-4 border-t border-border-primary flex gap-2 justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 text-xs text-text-muted hover:text-text-primary border border-border-primary rounded"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={saving}
            className="px-4 py-1.5 text-xs font-medium bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded"
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </>
  );
}
