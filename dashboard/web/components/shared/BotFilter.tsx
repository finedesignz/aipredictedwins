"use client";

import { useBotFilter } from "@/context/BotFilterContext";
import { useAPI } from "@/hooks/useAPI";
import type { BotInfo } from "@/types";

const BOT_COLORS: Record<string, string> = {
  A: "#60a5fa",
  B: "#fbbf24",
};

const DEFAULT_BOTS: BotInfo[] = [
  { id: "A", label: "Bot A", starting_equity: 100000 },
  { id: "B", label: "Bot B", starting_equity: 100000 },
];

export default function BotFilter() {
  const { filter, setFilter } = useBotFilter();
  const { data: bots } = useAPI<BotInfo[]>("/api/bots", 0);

  const toggle = (key: "A" | "B" | "spy" | "btc") =>
    setFilter({ ...filter, [key]: !filter[key] });

  const botList = bots && bots.length > 0 ? bots : DEFAULT_BOTS;

  return (
    <div className="flex flex-wrap gap-2 items-center">
      {botList.map((bot) => {
        const botKey = bot.id as "A" | "B";
        const color = BOT_COLORS[bot.id] ?? "#60a5fa";
        const active = filter[botKey];
        return (
          <button
            key={bot.id}
            onClick={() => toggle(botKey)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-opacity ${
              active ? "opacity-100" : "opacity-40"
            }`}
            style={{ borderColor: color, color }}
          >
            <span
              className="w-2 h-2 rounded-full flex-shrink-0"
              style={{ background: color }}
            />
            {bot.label}
          </button>
        );
      })}
      <button
        onClick={() => toggle("spy")}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border border-slate-400 text-slate-400 transition-opacity ${
          filter.spy ? "opacity-100" : "opacity-40"
        }`}
      >
        <span className="w-2 h-2 rounded-full bg-slate-400 flex-shrink-0" />
        S&amp;P 500
      </button>
      <button
        onClick={() => toggle("btc")}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border border-orange-400 text-orange-400 transition-opacity ${
          filter.btc ? "opacity-100" : "opacity-40"
        }`}
      >
        <span className="w-2 h-2 rounded-full bg-orange-400 flex-shrink-0" />
        BTC
      </button>
    </div>
  );
}
