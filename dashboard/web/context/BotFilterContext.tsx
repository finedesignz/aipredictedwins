"use client";
import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import type { BotFull } from "@/types";
import { useAPI } from "@/hooks/useAPI";

export interface BotFilterState {
  [key: string]: boolean;
}

interface BotFilterContextValue {
  filter: BotFilterState;
  setFilter: (f: BotFilterState) => void;
  bots: BotFull[];
  activeBotIds: string[];
  botParam: string;
}

const BotFilterContext = createContext<BotFilterContextValue>({
  filter: {},
  setFilter: () => {},
  bots: [],
  activeBotIds: [],
  botParam: "both",
});

export function BotFilterProvider({ children }: { children: ReactNode }) {
  const { data } = useAPI<BotFull[]>("/api/bots", 30_000);
  const bots: BotFull[] = data ?? [];

  const [filter, setFilter] = useState<BotFilterState>({ spy: true, btc: true });

  useEffect(() => {
    if (bots.length > 0) {
      setFilter((prev) => {
        const next: BotFilterState = {
          spy: prev.spy !== false,
          btc: prev.btc !== false,
        };
        bots.forEach((b) => { next[b.bot_id] = prev[b.bot_id] !== false; });
        return next;
      });
    }
  }, [bots.length]);

  const activeBotIds = bots.map((b) => b.bot_id).filter((id) => filter[id] !== false);
  const botParam = activeBotIds.length === 1 ? activeBotIds[0] : "both";

  return (
    <BotFilterContext.Provider value={{ filter, setFilter, bots, activeBotIds, botParam }}>
      {children}
    </BotFilterContext.Provider>
  );
}

export const useBotFilter = () => useContext(BotFilterContext);
