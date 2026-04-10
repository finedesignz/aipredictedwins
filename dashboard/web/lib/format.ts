export function formatCurrency(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : value > 0 ? "+" : "";
  return `${sign}$${abs.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatCurrencyUnsigned(value: number): string {
  return `$${Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value == null) return "--";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

export function formatPercentUnsigned(value: number | null | undefined): string {
  if (value == null) return "--";
  return `${Math.abs(value).toFixed(1)}%`;
}

export function formatNumber(value: number): string {
  return value.toLocaleString("en-US");
}

export function formatRelativeTime(dateString: string | null | undefined): string {
  if (!dateString) return "--";
  // SQLite stores "YYYY-MM-DD HH:MM:SS" without T — normalise to ISO so JS parses it correctly
  const normalised = dateString.replace(" ", "T");
  const now = Date.now();
  const then = new Date(normalised).getTime();
  if (isNaN(then)) return "--";
  const diffMs = now - then;

  if (diffMs < 0) return "just now";

  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return `${seconds}s ago`;

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;

  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;

  const months = Math.floor(days / 30);
  return `${months}mo ago`;
}

export function formatTimestamp(dateString: string): string {
  const d = new Date(dateString);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function formatTime(dateString: string): string {
  const d = new Date(dateString);
  return d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  if (h < 24) return `${h}h ${rm}m`;
  const d = Math.floor(h / 24);
  const rh = h % 24;
  return `${d}d ${rh}h`;
}
