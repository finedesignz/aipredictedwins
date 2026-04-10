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
}

export interface RiskDecision {
  id: string;
  timestamp: string;
  symbol: string;
  confluence_score: number;
  decision: "PROCEED" | "VETO";
  veto_count: number;
  reasoning: string;
  scenarios: RiskScenario[];
}

export interface RiskScenario {
  analyst: string;
  scenario: string;
  likelihood: "high" | "medium" | "low";
  impact: "high" | "medium" | "low";
  vote: "PROCEED" | "VETO";
  reasoning: string;
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
  config: Record<string, string | number | boolean>;
  health: {
    claude_cli: boolean;
    alpaca_api: boolean;
    sqlite_db: boolean;
    db_size_mb: number;
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
}

export interface BotInfo {
  id: string;
  label: string;
  starting_equity: number;
  alpaca_key_prefix?: string;
  config_flags?: Record<string, string | number | boolean>;
}

export interface MultiBotPortfolio {
  A?: Portfolio;
  B?: Portfolio;
}

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
