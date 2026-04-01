"use client";

import TopNav from "@/components/nav/TopNav";
import { useAPI } from "@/hooks/useAPI";
import type { Portfolio } from "@/types";

export default function NavWrapper() {
  const { data: portfolio } = useAPI<Portfolio>("/api/portfolio", 10000);

  return (
    <TopNav
      mode={portfolio?.mode ?? "paper"}
      equity={portfolio?.equity ?? 0}
    />
  );
}
