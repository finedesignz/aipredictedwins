"use client";

interface ModeBadgeProps {
  mode: string;
}

export default function ModeBadge({ mode }: ModeBadgeProps) {
  if (mode === "live") {
    return (
      <span className="relative inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wider bg-loss-red/15 text-loss-red border border-loss-red/30">
        <span className="absolute -left-0.5 -top-0.5 flex h-2.5 w-2.5">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-loss-red opacity-75" />
          <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-loss-red" />
        </span>
        <span className="ml-2">LIVE</span>
      </span>
    );
  }

  return (
    <span className="inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wider bg-warning-amber/15 text-warning-amber border border-warning-amber/30">
      PAPER
    </span>
  );
}
