/**
 * Derive a single-letter bot badge (label + color classes) from any bot value.
 *
 * Accepts "A", "Agent A", "D", "Agent D — Daytrade", etc. — strips an optional
 * "Agent " prefix and uses the first character, uppercased. No binary A/B
 * assumption: any current or future bot id renders correctly, with a neutral
 * fallback for unrecognized values.
 */
const COLORS: Record<string, string> = {
  A: "bg-accent-blue/15 text-accent-blue",
  B: "bg-warning-amber/15 text-warning-amber",
  C: "bg-profit-green/15 text-profit-green",
  D: "bg-loss-red/15 text-loss-red",
};

const NEUTRAL = "bg-bg-card-hover text-text-muted";

export function botBadge(value: string): { label: string; className: string } {
  const cleaned = value.replace(/^Agent\s+/i, "").trim();
  const label = (cleaned.charAt(0) || "?").toUpperCase();
  return { label, className: COLORS[label] ?? NEUTRAL };
}
