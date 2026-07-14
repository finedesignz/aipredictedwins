export interface Reconciliation {
  alpaca_realized_pnl: number;
  trade_log_pnl: number;
  delta: number;
  within_tolerance: boolean;
  checked_at: string | null;
}

export interface Portfolio {
  equity: number;
  total_pnl: number;
  total_pnl_percent: number;
  daily_pnl: number;
  daily_pnl_percent: number;
  win_rate: number;          // 0-100 percentage
  total_trades: number;
  trades_resolved: number;
  wins: number;
  losses: number;
  open_positions: number;
  mode: string;
  // Phase 19 (RUN-02). TS silently DROPS unknown JSON keys, so these fields were
  // invisible until they were declared here — a field nobody renders is the bug.
  unresolved: number;
  pnl_source: "reconciled" | "alpaca_live" | "trade_log";
  stale: boolean;
  reconciled?: Reconciliation | null;
}

export interface Position {
  id: number;
  symbol: string;
  side: string;
  entry_price: number;
  current_price: number;
  quantity: number;
  unrealized_pnl: number;
  unrealized_pnl_percent: number;
  confluence_score: number;
  trailing_stop: number | null;
  opened_at: string;
  bot?: string;
}

export interface ClosedPosition {
  id: string;
  symbol: string;
  side: "long" | "short";
  entry_price: number;
  exit_price: number;
  quantity: number;
  realized_pnl: number;
  realized_pnl_percent: number;
  confluence_score: number;
  close_reason: string;
  opened_at: string;
  closed_at: string;
}

export interface Trade {
  id: string;
  timestamp: string;
  symbol: string;
  side: "long" | "short";
  confluence_score: number;
  entry_price: number;
  exit_price: number | null;
  quantity: number;
  pnl: number | null;
  pnl_percent: number | null;
  status: "open" | "closed" | "cancelled";
  close_reason: string | null;
  notes: string | null;
  bot?: string;
}

export interface Signal {
  symbol: string;
  ema_signal: "bullish" | "bearish" | "neutral";
  adx_value: number;
  adx_signal: "bullish" | "bearish" | "neutral";
  rsi_value: number;
  rsi_signal: "bullish" | "bearish" | "neutral";
  volume_spike: boolean;
  vwap_signal: "bullish" | "bearish" | "neutral";
  confluence_score: number;
  action: "BUY" | "WATCH" | "SKIP";
  scanned_at: string;
  bot_id?: string;
}

export interface RiskDecision {
  id: string;
  timestamp: string;
  symbol: string;
  event_title: string;
  confluence: number;           // 0-5 scaled score (mirofish_prob * 5)
  decision: "PROCEED" | "VETO";
  confidence: number | null;
  risk_assessment: string | null;
  veto_reason: string | null;
  proposed_side: string | null;
  mirofish_prob: number | null;
}

export interface ActivityEvent {
  id: string;
  type:
    | "trade_placed"
    | "trade_closed"
    | "scan_complete"
    | "risk_decision"
    | "cycle_complete"
    | "error";
  message: string;
  detail?: string;
  timestamp: string;
}

export interface BotSettings {
  mode: string;
  running: boolean;
  last_cycle: string | null;
  uptime_seconds: number;
  cycle_count: number;
  paper_trades_completed: number;
  paper_trades_target: number;
  win_rate: number;            // 0-100 percentage
  win_rate_target: number;     // 0-100 percentage
  equity: number;
  equity_target: number;
  unresolved: number;
  config: Record<string, string | number | boolean>;
  health: {
    claude_cli: boolean;
    alpaca_api: boolean;
    database: boolean;
    db_size_mb: number;
    // Phase 19 (RUN-01) — absence and staleness both mean DEAD; never default healthy.
    manager_alive: boolean;
    alerts_configured: boolean;
    alerts_last_error: string | null;
    bots_alive: number;
    bots_enabled: number;
    last_heartbeat: string | null;
  };
}

export interface EquityPoint {
  timestamp: string;
  equity: number;
  bot?: string;
}

export interface EquitySeriesPoint {
  timestamp: string;
  equity: number;
  return_pct: number;
  bot_id?: string;
}

export interface EquitySeries {
  bot_id: string;
  points: EquitySeriesPoint[];
}

export interface EquityResponse {
  series: EquitySeries[];
}

export interface BenchmarkPoint {
  timestamp: string;
  return_pct: number;
  price?: number;   // actual close price: SPY share price or BTC/USD
}

export interface BotInfo {
  id: string;
  label: string;
  starting_equity: number;
  alpaca_key_prefix?: string;
  config_flags?: Record<string, string | number | boolean>;
}

export interface BotFull {
  bot_id: string;
  label: string;
  kelly_fraction: number;
  min_confluence: number;
  hard_stop_pct: number;
  soft_stop_pct: number;
  rsi_ceiling: number;
  crypto_universe: string;
  stock_universe: string | null;
  asset_class: string | null;
  skip_risk_gate: boolean;
  max_position_pct: number;
  min_short_confluence: number | null;
  tradingagents_enabled: boolean | null;
  strategy: string | null;
  trend_ma_window: number | null;
  trend_symbol: string | null;
  trend_benchmark: string | null;
  quarantined_symbols: string;
  enabled: boolean;
  status: "running" | "stopped" | "error";
  status_detail: string | null;
  thread_alive: boolean;
}

// Phase 16 (UNIV-03) — the effective trading universe, computed server-side by
// src/effective_universe.resolve_universe. The client renders it; it never
// recomputes allow-vs-block.
export interface BlockedSymbol {
  symbol: string;
  reason: "quarantined" | "off_universe" | "meme" | "untradeable";
  open_positions: number;
  recent_trades: number;
}

export interface BotUniverse {
  bot_id: string;
  strategy: string;
  asset_class: string;
  allowlist: string[];
  quarantined: string[];
  effective: string[];
  blocked: BlockedSymbol[];
  starvation: boolean;
  leak: string[];
  shadow_applied: boolean;
  shadow_sets_loaded: boolean;
  exposure_loaded: boolean;
}

export type MultiBotPortfolio = Record<string, Portfolio>;

export interface EquityData {
  series: EquitySeries[];
}

export interface AlpacaAccountSummary {
  equity: number;
  cash: number;
  buying_power: number;
  portfolio_value: number;
  daytrade_count: number;
}

export interface AlpacaEquityData {
  agentA: EquityPoint[];
  agentB: EquityPoint[];
  sp500: EquityPoint[];
  cryptoBenchmark: EquityPoint[];
  accountA: AlpacaAccountSummary;
  accountB: AlpacaAccountSummary;
  days: number;
  errors: string[];
}

export interface APIResponse<T> {
  data: T;
  meta: {
    timestamp: string;
    count?: number;
  };
}
