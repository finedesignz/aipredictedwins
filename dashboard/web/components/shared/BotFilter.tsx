"use client";
import { useBotFilter } from "@/context/BotFilterContext";

const COLORS = ["#60a5fa", "#fbbf24", "#34d399", "#f87171", "#a78bfa", "#fb923c"];

export default function BotFilter() {
  const { filter, setFilter, bots } = useBotFilter();

  return (
    <div className="flex flex-wrap gap-2 items-center">
      {bots.map((bot, i) => {
        const color = COLORS[i % COLORS.length];
        const active = filter[bot.bot_id] !== false;
        return (
          <button
            key={bot.bot_id}
            onClick={() => setFilter({ ...filter, [bot.bot_id]: !active })}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-opacity ${
              active ? "opacity-100" : "opacity-40"
            }`}
            style={{ borderColor: color, color }}
          >
            <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
            {bot.label}
            <span className={`w-1.5 h-1.5 rounded-full ml-0.5 ${
              bot.status === "running" ? "bg-green-400" :
              bot.status === "error" ? "bg-red-400" : "bg-slate-500"
            }`} />
          </button>
        );
      })}
      <button
        onClick={() => setFilter({ ...filter, spy: filter.spy === false })}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border border-slate-400 text-slate-400 transition-opacity ${
          filter.spy !== false ? "opacity-100" : "opacity-40"
        }`}
      >
        <span className="w-2 h-2 rounded-full bg-slate-400 flex-shrink-0" />
        S&amp;P 500
      </button>
      <button
        onClick={() => setFilter({ ...filter, btc: filter.btc === false })}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border border-orange-400 text-orange-400 transition-opacity ${
          filter.btc !== false ? "opacity-100" : "opacity-40"
        }`}
      >
        <span className="w-2 h-2 rounded-full bg-orange-400 flex-shrink-0" />
        BTC
      </button>
    </div>
  );
}
