export interface Stock {
  code: string;
  name: string;
  market: string;
  sector?: string | null;
  listed_shares?: number | null;
  security_type?: string | null;
}

export interface Ohlcv {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  trading_value: number;
}

export interface PeriodFlow {
  foreign_qty: number;
  foreign_value: number;
  foreign_ratio: number;
  institution_qty: number;
  institution_value: number;
  institution_ratio: number;
  days: number;
}

export interface ProgramRow {
  date: string;
  close: number;
  change_rate: number | null;
  volume: number;
  sell_amount_m: number;
  buy_amount_m: number;
  net_amount_m: number;
}

export interface MarketAdrRow {
  date: string;
  advances: number;
  declines: number;
  adr: number;
}

export interface Theme {
  code: string;
  name: string;
}

export interface InvestorRow {
  date: string;
  foreign_qty: number;
  foreign_value: number;
  institution_qty: number;
  institution_value: number;
}

export interface DataQuality {
  source?: string;
  freshness?: string;
  last_updated_at?: string;
  connection_status?: string;
  price_status?: string;
  chart_status?: string;
  investor_status?: string;
  program_status?: string;
  adr_status?: string;
  theme_status?: string;
  status?: string;
  message?: string;
  messages?: string[];
}

export interface KiwoomSettings {
  configured: boolean;
  app_key_masked: string;
  secret_key_masked: string;
  account_no: string;
  env: string;
  base_url: string;
  stored_locally: boolean;
}

export interface KiwoomSettingsPayload {
  app_key: string;
  secret_key: string;
  account_no: string;
  env: string;
  base_url?: string;
}

export interface KiwoomAuthTest {
  ok: boolean;
  status: string;
  message: string;
  token_type?: string | null;
  expires_dt?: string | null;
  provider?: {
    provider: string;
    configured: boolean;
    environment: string;
    base_url: string;
    account_configured: boolean;
  };
}

export interface Dashboard {
  stock: Stock;
  summary: {
    latest_date: string | null;
    close: number | null;
    change: number | null;
    change_rate: number | null;
    volume: number | null;
    trading_value: number | null;
    turnover_rate: number | null;
    description: string;
  };
  ohlcv: Ohlcv[];
  indicators: {
    ma: Record<string, Array<number | null>>;
    obv: number[];
    rsi14: Array<number | null>;
    sentiment10: Array<number | null>;
  };
  investor_summary: {
    periods: Record<string, PeriodFlow>;
    recent_outflow_5d: {
      foreign_ratio: number;
      institution_ratio: number;
    };
  };
  investors: InvestorRow[];
  program_summary: Record<string, {
    net_amount_m: number;
    buy_amount_m: number;
    sell_amount_m: number;
    days: number;
  }>;
  program_trading: ProgramRow[];
  market_adr: MarketAdrRow[];
  themes: Theme[];
  timeframe?: ChartTimeframe;
  data_quality: DataQuality;
}

export type RankingMetric = "foreign" | "institution" | "combined";
export type RankingDirection = "inflow" | "outflow";
export type RankingMarket = "ALL" | "KOSPI" | "KOSDAQ";
export type RankingAssetType = "ALL" | "STOCK" | "ETF";

export interface InvestorRankingItem {
  trade_date: string;
  code: string;
  name: string;
  market: string;
  security_type: string;
  close: number | null;
  market_cap: number | null;
  listed_shares: number | null;
  foreign_net_qty: number | null;
  foreign_net_value: number | null;
  institution_net_qty: number | null;
  institution_net_value: number | null;
  foreign_change_ratio: number | null;
  institution_change_ratio: number | null;
  combined_change_ratio: number | null;
  foreign_holding_qty: number | null;
  foreign_holding_ratio: number | null;
  score: number;
  rank: number;
  previous_rank: number | null;
  rank_change: number | null;
}

export interface InvestorRankingResponse {
  date: string | null;
  metric?: RankingMetric;
  direction?: RankingDirection;
  market?: RankingMarket;
  asset_type?: RankingAssetType;
  items: InvestorRankingItem[];
  dates: string[];
  data_quality: DataQuality;
}

export interface RankingJob {
  status: "idle" | "running" | "completed" | "failed";
  target_date: string | null;
  total: number;
  completed: number;
  saved: number;
  failed: number;
  message: string | null;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string | null;
}

export interface InvestorRankingStatus {
  job: RankingJob;
  dates: string[];
}

export interface SearchResponse {
  items: Stock[];
  data_quality: DataQuality;
}

export type ChartTimeframe = "daily" | "weekly" | "monthly";
