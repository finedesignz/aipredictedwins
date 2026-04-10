"use client";

import TopNav from "@/components/nav/TopNav";
import { useAPI } from "@/hooks/useAPI";
import type { MultiBotPortfolio } from "@/types";

export default function NavWrapper() {
  const { data: portfolio } = useAPI<MultiBotPortfolio>("/api/portfolio?bot=both", 10000);

  // Sum equity across both bots for the nav display
  const totalEquity = (portfolio?.A?.equity ?? 0) + (portfolio?.B?.equity ?? 0);
  const mode = portfolio?.A?.mode ?? portfolio?.B?.mode ?? "paper";

  return (
    <TopNav
      mode={mode}
      equity={totalEquity}
    />
  );
}
