"use client";

interface BadgeProps {
  variant: "proceed" | "veto" | "paper" | "live" | "open" | "closed" | "bullish" | "bearish" | "neutral";
  children: React.ReactNode;
  className?: string;
}

const variantStyles: Record<BadgeProps["variant"], string> = {
  proceed: "bg-profit-green/15 text-profit-green border-profit-green/30",
  veto: "bg-loss-red/15 text-loss-red border-loss-red/30",
  paper: "bg-warning-amber/15 text-warning-amber border-warning-amber/30",
  live: "bg-loss-red/15 text-loss-red border-loss-red/30",
  open: "bg-accent-blue/15 text-accent-blue border-accent-blue/30",
  closed: "bg-text-muted/15 text-text-muted border-text-muted/30",
  bullish: "bg-profit-green/15 text-profit-green border-profit-green/30",
  bearish: "bg-loss-red/15 text-loss-red border-loss-red/30",
  neutral: "bg-text-muted/15 text-text-muted border-text-muted/30",
};

export default function Badge({ variant, children, className = "" }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium border ${variantStyles[variant]} ${className}`}
    >
      {children}
    </span>
  );
}
