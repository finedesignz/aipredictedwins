"use client";

import { createContext, useContext, useState, ReactNode } from "react";

export interface BotFilter {
  A: boolean;
  B: boolean;
  spy: boolean;
}

interface BotFilterContextValue {
  filter: BotFilter;
  setFilter: (f: BotFilter) => void;
  activeBots: ("A" | "B")[];
  botParam: "A" | "B" | "both";
}

const defaultValue: BotFilterContextValue = {
  filter: { A: true, B: true, spy: true },
  setFilter: () => {},
  activeBots: ["A", "B"],
  botParam: "both",
};

const BotFilterContext = createContext<BotFilterContextValue>(defaultValue);

export function BotFilterProvider({ children }: { children: ReactNode }) {
  const [filter, setFilter] = useState<BotFilter>({ A: true, B: true, spy: true });

  const activeBots = (["A", "B"] as const).filter((b) => filter[b]);
  const botParam: "A" | "B" | "both" =
    activeBots.length === 1 ? activeBots[0] : "both";

  return (
    <BotFilterContext.Provider value={{ filter, setFilter, activeBots, botParam }}>
      {children}
    </BotFilterContext.Provider>
  );
}

export const useBotFilter = () => useContext(BotFilterContext);
