import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { BarChart3, LayoutDashboard, RefreshCw, Search, Settings as SettingsIcon, X } from "lucide-react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  LineSeries,
  type CandlestickData,
  type HistogramData,
  type ISeriesApi,
  type LineData,
  type MouseEventParams,
  type Time,
} from "lightweight-charts";
import {
  getDashboard,
  getInvestorRanking,
  getInvestorRankingStatus,
  getKiwoomSettings,
  refreshInvestorRanking,
  refreshStock,
  saveKiwoomSettings,
  searchStocks,
  testKiwoomAuth,
} from "./api";
import type {
  AutoSchedulerStatus,
  ChartTimeframe,
  Dashboard,
  DataQuality,
  InvestorRankingItem,
  InvestorRankingStatus,
  KiwoomSettings,
  KiwoomSettingsPayload,
  Ohlcv,
  RankingAssetType,
  RankingDirection,
  RankingMarket,
  RankingMetric,
  Stock,
} from "./types";
import "./styles.css";

const periods = ["5", "20", "60", "120"];
const chartTimeframes: Array<{ value: ChartTimeframe; label: string; lookback: number }> = [
  { value: "daily", label: "일봉", lookback: 300 },
  { value: "weekly", label: "주봉", lookback: 300 },
  { value: "monthly", label: "월봉", lookback: 240 },
];

type RankingSortKey =
  | "rank"
  | "previous_rank"
  | "name"
  | "market"
  | "close"
  | "market_cap"
  | "foreign_net_qty"
  | "institution_net_qty"
  | "combined_change_ratio"
  | "score"
  | "foreign_holding_ratio";
type SortDirection = "asc" | "desc";
type RankingColumnKey = RankingSortKey;
type RankingQuery = {
  date: string;
  metric: RankingMetric;
  direction: RankingDirection;
  market: RankingMarket;
  assetType: RankingAssetType;
};

const rankingColumns: Array<{ key: RankingColumnKey; label: string; defaultWidth: number; minWidth: number; maxWidth: number }> = [
  { key: "rank", label: "순위", defaultWidth: 58, minWidth: 48, maxWidth: 90 },
  { key: "previous_rank", label: "전일", defaultWidth: 64, minWidth: 52, maxWidth: 110 },
  { key: "name", label: "종목", defaultWidth: 250, minWidth: 150, maxWidth: 430 },
  { key: "market", label: "시장", defaultWidth: 92, minWidth: 72, maxWidth: 150 },
  { key: "close", label: "종가(원)", defaultWidth: 112, minWidth: 90, maxWidth: 180 },
  { key: "market_cap", label: "시가총액(원화)", defaultWidth: 132, minWidth: 100, maxWidth: 220 },
  { key: "foreign_net_qty", label: "외국인 수량(주)", defaultWidth: 138, minWidth: 105, maxWidth: 230 },
  { key: "institution_net_qty", label: "기관 수량(주)", defaultWidth: 138, minWidth: 105, maxWidth: 230 },
  { key: "combined_change_ratio", label: "합산 변동률", defaultWidth: 116, minWidth: 92, maxWidth: 190 },
  { key: "score", label: "변동률", defaultWidth: 124, minWidth: 96, maxWidth: 200 },
  { key: "foreign_holding_ratio", label: "외국인 실제 보유율", defaultWidth: 150, minWidth: 120, maxWidth: 220 },
];

const defaultRankingColumnWidths = Object.fromEntries(
  rankingColumns.map((column) => [column.key, column.defaultWidth]),
) as Record<RankingColumnKey, number>;

const defaultRankingQuery: RankingQuery = {
  date: "",
  metric: "foreign",
  direction: "inflow",
  market: "ALL",
  assetType: "ALL",
};

const rankingColumnStorageKey = "yangradar-ranking-column-widths";
const rankingRowStorageKey = "yangradar-ranking-row-heights";

type AppView = "dashboard" | "rankings";

function readViewFromLocation(): AppView {
  if (typeof window === "undefined") return "dashboard";
  return new URLSearchParams(window.location.search).get("view") === "rankings" ? "rankings" : "dashboard";
}

function kstDateKey(value: Date): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(value);
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function formatKstTimestamp(value: string | null | undefined, targetDate: string | null | undefined, forceDate = false): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  const time = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Seoul",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(parsed);
  const includeDate = forceDate || !targetDate || kstDateKey(parsed) !== targetDate;
  if (!includeDate) return `${time} KST`;
  const date = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Seoul",
    month: "numeric",
    day: "numeric",
  }).format(parsed);
  return `${date} ${time} KST`;
}

function formatAutoSchedulerMessage(autoScheduler: AutoSchedulerStatus | null | undefined): string {
  if (!autoScheduler) return "자동 수집 상태 확인 중";
  const nextCheck = formatKstTimestamp(autoScheduler.next_check_at, autoScheduler.target_date);
  const sample = typeof autoScheduler.ready_count === "number" && typeof autoScheduler.sample_count === "number"
    ? ` · 표본 ${autoScheduler.ready_count}/${autoScheduler.sample_count}`
    : "";
  switch (autoScheduler.state) {
    case "waiting_time":
      return `자동 수집 대기 · ${nextCheck || "15:40 KST"}부터 당일 데이터 확인`;
    case "waiting_data":
      return `당일 수급 데이터 반영 대기${sample}${nextCheck ? ` · 다음 확인 ${nextCheck}` : ""}`;
    case "running":
      return "자동 수집 진행 중";
    case "completed":
      return `오늘 자동 수집 완료${nextCheck ? ` · 다음 확인 ${nextCheck}` : ""}`;
    case "error":
      return `자동 확인 오류${nextCheck ? ` · 다음 확인 ${nextCheck}` : ""}`;
    case "disabled":
      return "자동 수집 비활성 · 키움 API 설정 필요";
    case "weekend":
      return `주말 자동 수집 없음${nextCheck ? ` · 다음 확인 ${formatKstTimestamp(autoScheduler.next_check_at, autoScheduler.target_date, true)}` : ""}`;
    case "idle":
    default:
      return "자동 수집 상태 확인 중";
  }
}

function rankingJobMessage(job: InvestorRankingStatus["job"] | undefined, fallback: string): string {
  if (!job) return fallback;
  const total = job.total.toLocaleString("ko-KR");
  const saved = job.saved.toLocaleString("ko-KR");
  const failed = job.failed.toLocaleString("ko-KR");
  if (job.status === "running") {
    return `${job.message ?? "수집 중"} · ${job.completed.toLocaleString("ko-KR")}/${total} · 성공 ${saved} · 실패 ${failed}`;
  }
  if (job.status === "failed") return `수집 실패 · 성공 ${saved} / ${total} · 실패 ${failed}`;
  if (job.status === "completed") {
    return job.failed > 0
      ? `수집 완료 · 성공 ${saved} / ${total} · 실패 ${failed}`
      : `수집 완료 · ${saved} / ${total}`;
  }
  return job.message ?? fallback;
}

function readRankingColumnWidths() {
  if (typeof window === "undefined") return defaultRankingColumnWidths;
  try {
    const saved = JSON.parse(window.localStorage.getItem(rankingColumnStorageKey) ?? "null") as Record<string, unknown> | null;
    if (!saved) return defaultRankingColumnWidths;
    return rankingColumns.reduce((result, column) => ({
      ...result,
      [column.key]: clamp(Number(saved[column.key]) || column.defaultWidth, column.minWidth, column.maxWidth),
    }), {} as Record<RankingColumnKey, number>);
  } catch {
    return defaultRankingColumnWidths;
  }
}

function readRankingRowHeights() {
  if (typeof window === "undefined") return {};
  try {
    const saved = JSON.parse(window.localStorage.getItem(rankingRowStorageKey) ?? "{}") as Record<string, unknown>;
    return Object.fromEntries(Object.entries(saved).flatMap(([code, value]) => {
      const height = Number(value);
      return Number.isFinite(height) ? [[code, clamp(height, 24, 90)]] : [];
    }));
  } catch {
    return {};
  }
}

function App() {
  const [query, setQuery] = useState("삼성전자");
  const [results, setResults] = useState<Stock[]>([]);
  const [selected, setSelected] = useState("005930");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [timeframe, setTimeframe] = useState<ChartTimeframe>("daily");
  const [searchQuality, setSearchQuality] = useState<DataQuality | null>(null);
  const [settings, setSettings] = useState<KiwoomSettings | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [view, setView] = useState<AppView>(readViewFromLocation);

  function navigateToView(nextView: AppView, options: { replace?: boolean } = {}) {
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      const currentParam = url.searchParams.get("view");
      if (options.replace || currentParam !== nextView) {
        url.searchParams.set("view", nextView);
        const historyMethod = options.replace ? "replaceState" : "pushState";
        window.history[historyMethod]({ ...(window.history.state ?? {}), view: nextView }, "", url);
      }
    }
    setView(nextView);
  }

  useEffect(() => {
    const initialView = readViewFromLocation();
    const url = new URL(window.location.href);
    if (url.searchParams.get("view") !== initialView) {
      url.searchParams.set("view", initialView);
      window.history.replaceState({ ...(window.history.state ?? {}), view: initialView }, "", url);
    }
    setView(initialView);

    const handlePopState = () => setView(readViewFromLocation());
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    void loadSettings();
    void loadDashboard(selected, timeframe);
  }, [selected, timeframe]);

  async function loadSettings() {
    try {
      setSettings(await getKiwoomSettings());
    } catch {
      setSettings(null);
    }
  }

  async function runSearch() {
    setError("");
    try {
      const response = await searchStocks(query);
      setResults(response.items);
      setSearchQuality(response.data_quality);
      navigateToView("dashboard");
      if (response.items[0]) setSelected(response.items[0].code);
    } catch (err) {
      setError(err instanceof Error ? err.message : "검색 중 오류가 발생했습니다.");
    }
  }

  async function loadDashboard(code: string, nextTimeframe = timeframe) {
    setLoading(true);
    setError("");
    try {
      const config = chartTimeframes.find((item) => item.value === nextTimeframe) ?? chartTimeframes[0];
      setDashboard(await getDashboard(code, nextTimeframe, config.lookback));
    } catch (err) {
      setError(err instanceof Error ? err.message : "대시보드 로딩 중 오류가 발생했습니다.");
    } finally {
      setLoading(false);
    }
  }

  async function handleRefresh() {
    if (!dashboard) return;
    setLoading(true);
    setError("");
    try {
      await refreshStock(dashboard.stock.code);
      await loadDashboard(dashboard.stock.code, timeframe);
      await loadSettings();
    } catch (err) {
      setError(err instanceof Error ? err.message : "갱신에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="terminal-shell">
      <header className="topbar">
        <div className="brand">YangRadar</div>
        <form
          className="searchbar"
          onSubmit={(event) => {
            event.preventDefault();
            void runSearch();
          }}
        >
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="종목명 또는 코드" />
          <button type="submit" title="검색"><Search size={16} /></button>
        </form>
        <button className="action" onClick={() => void handleRefresh()} disabled={loading} title="데이터 갱신">
          <RefreshCw size={16} />
          갱신
        </button>
        <button
          className={`action ${view === "dashboard" ? "active-action" : ""}`}
          onClick={() => navigateToView("dashboard")}
          aria-current={view === "dashboard" ? "page" : undefined}
          title="종목 대시보드"
        >
          <LayoutDashboard size={16} />
          대시보드
        </button>
        <button
          className={`action ${view === "rankings" ? "active-action" : ""}`}
          onClick={() => navigateToView("rankings")}
          aria-current={view === "rankings" ? "page" : undefined}
          title="외국인·기관 수급 순위"
        >
          <BarChart3 size={16} />
          수급 순위
        </button>
        <button className="action" onClick={() => setSettingsOpen(true)} title="키움 API 설정">
          <SettingsIcon size={16} />
          설정
        </button>
        <StatusBadge quality={dashboard?.data_quality ?? searchQuality} configured={settings?.configured} />
      </header>

      {view === "dashboard" && results.length > 0 && (
        <div className="result-strip">
          {results.map((stock) => (
            <button key={stock.code} onClick={() => setSelected(stock.code)} className={selected === stock.code ? "active" : ""}>
              {stock.name} <span>{stock.code}</span>
            </button>
          ))}
        </div>
      )}

      {error && <div className="error">{error}</div>}
      {view === "dashboard" && dashboard && <DashboardView dashboard={dashboard} loading={loading} timeframe={timeframe} onTimeframeChange={setTimeframe} />}
      {view === "rankings" && (
        <InvestorRankingView
          onSelectStock={(code) => {
            setSelected(code);
            navigateToView("dashboard");
          }}
        />
      )}
      {settingsOpen && (
        <SettingsDialog
          current={settings}
          onClose={() => setSettingsOpen(false)}
          onSaved={async () => {
            await loadSettings();
            await loadDashboard(selected, timeframe);
          }}
        />
      )}
    </main>
  );
}

function InvestorRankingView({ onSelectStock }: { onSelectStock: (code: string) => void }) {
  const [metric, setMetric] = useState<RankingMetric>("foreign");
  const [direction, setDirection] = useState<RankingDirection>("inflow");
  const [market, setMarket] = useState<RankingMarket>("ALL");
  const [assetType, setAssetType] = useState<RankingAssetType>("ALL");
  const [date, setDate] = useState("");
  const [collectionDate, setCollectionDate] = useState("");
  const [appliedQuery, setAppliedQuery] = useState<RankingQuery>(defaultRankingQuery);
  const [sortState, setSortState] = useState<{ key: RankingSortKey; direction: SortDirection }>({ key: "rank", direction: "asc" });
  const [columnWidths, setColumnWidths] = useState<Record<RankingColumnKey, number>>(readRankingColumnWidths);
  const [rowHeights, setRowHeights] = useState<Record<string, number>>(readRankingRowHeights);
  const [response, setResponse] = useState<Awaited<ReturnType<typeof getInvestorRanking>> | null>(null);
  const [jobStatus, setJobStatus] = useState<InvestorRankingStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState("");
  const rankingRequestId = useRef(0);

  async function loadStatus() {
    try {
      setJobStatus(await getInvestorRankingStatus());
    } catch (err) {
      setError(err instanceof Error ? err.message : "수급 수집 상태를 불러오지 못했습니다.");
    }
  }

  async function loadRanking(query: RankingQuery) {
    const requestId = ++rankingRequestId.current;
    setLoading(true);
    setError("");
    try {
      const next = await getInvestorRanking({
        date: query.date || undefined,
        metric: query.metric,
        direction: query.direction,
        market: query.market,
        assetType: query.assetType,
      });
      if (requestId !== rankingRequestId.current) return;
      setResponse(next);
      setAppliedQuery(query);
    } catch (err) {
      if (requestId !== rankingRequestId.current) return;
      setError(err instanceof Error ? err.message : "수급 순위를 불러오지 못했습니다.");
    } finally {
      if (requestId === rankingRequestId.current) setLoading(false);
    }
  }

  useEffect(() => {
    void loadStatus();
  }, []);

  useEffect(() => {
    void loadRanking(defaultRankingQuery);
  }, []);

  useEffect(() => {
    const previousJobStatus = jobStatus?.job.status;
    const intervalMs = previousJobStatus === "running" ? 2000 : 30000;
    const timer = window.setInterval(() => {
      void getInvestorRankingStatus().then((next) => {
        setJobStatus(next);
        if (previousJobStatus === "running" && next.job.status !== "running") void loadRanking(appliedQuery);
      }).catch(() => undefined);
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [jobStatus?.job.status, appliedQuery.date, appliedQuery.metric, appliedQuery.direction, appliedQuery.market, appliedQuery.assetType]);

  useEffect(() => {
    try {
      window.localStorage.setItem(rankingColumnStorageKey, JSON.stringify(columnWidths));
    } catch {
      // Local storage can be disabled in a private browser context.
    }
  }, [columnWidths]);

  useEffect(() => {
    try {
      window.localStorage.setItem(rankingRowStorageKey, JSON.stringify(rowHeights));
    } catch {
      // Local storage can be disabled in a private browser context.
    }
  }, [rowHeights]);

  function handleRankingSearch() {
    const query: RankingQuery = { date, metric, direction, market, assetType };
    void loadRanking(query);
  }

  async function handleRefresh() {
    setRefreshing(true);
    setError("");
    try {
      await refreshInvestorRanking(collectionDate || undefined);
      await loadStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "전체 수급 갱신을 시작하지 못했습니다.");
    } finally {
      setRefreshing(false);
    }
  }

  async function handleRetryFailed(targetDate: string) {
    setRetrying(true);
    setError("");
    try {
      await refreshInvestorRanking(targetDate);
      setJobStatus((current) => current ? {
        ...current,
        job: {
          ...current.job,
          status: "running",
          target_date: targetDate,
          message: "실패 종목 재수집을 시작했습니다.",
        },
      } : current);
    } catch (err) {
      setError(err instanceof Error ? err.message : "실패 종목 재시도를 시작하지 못했습니다.");
    } finally {
      setRetrying(false);
    }
  }

  const job = jobStatus?.job;
  const items = response?.items ?? [];
  const dataQuality = response?.data_quality;
  const availableDates = response?.dates ?? jobStatus?.dates ?? [];
  const selectedDate = response?.date;
  const previousDate = selectedDate ? availableDates.find((candidate) => candidate < selectedDate) : undefined;
  const sortedItems = useMemo(() => sortRankingItems(items, sortState), [items, sortState]);
  const rankingTableWidth = rankingColumns.reduce((sum, column) => sum + columnWidths[column.key], 0);
  const autoScheduler = jobStatus?.auto_scheduler;
  const statusMessage = rankingJobMessage(job, dataQuality?.message ?? "전체 종목 일별 수급 데이터가 없습니다.");
  const retryTargetDate = job?.target_date;
  const showRetry = Boolean(retryTargetDate && job?.status !== "running" && (job.failed > 0 || job.status === "failed"));

  return (
    <section className="ranking-view">
      <div className="ranking-heading panel">
        <div className="ranking-heading-copy">
          <h1>매일 변동 TOP 100 · 외국인·기관 수급 순위</h1>
          <p>시가총액 환산(상장주식수 기준) 일일 보유변동률 · 전체 종목 및 ETF</p>
          <p className={`ranking-auto-status state-${autoScheduler?.state ?? "idle"}`} role="status" aria-live="polite">
            {formatAutoSchedulerMessage(autoScheduler)}
          </p>
        </div>
        <div className={`ranking-job ${job?.status === "running" ? "running" : ""}`}>
          <div className="ranking-job-copy">
            <span>{statusMessage}</span>
            {showRetry && retryTargetDate && (
              <small className="ranking-retry-hint">
                {retryTargetDate} 기준 · 저장된 성공 종목은 건너뛰고 누락 종목만 다시 수집합니다.
              </small>
            )}
          </div>
          {showRetry && retryTargetDate && (
            <div className="ranking-job-actions">
              <button
                type="button"
                className="ranking-retry-button"
                onClick={() => void handleRetryFailed(retryTargetDate)}
                disabled={retrying || refreshing || job?.status === "running"}
              >
                {retrying ? "재시도 중" : job.failed > 0 ? `실패 ${job.failed.toLocaleString("ko-KR")}개 재시도` : "실패 수집 재시도"}
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="ranking-filters panel">
        <label><span>조회 기준일</span><select value={date} onChange={(event) => setDate(event.target.value)}>
          <option value="">최신 거래일</option>
          {(response?.dates ?? jobStatus?.dates ?? []).map((item) => <option key={item} value={item}>{item}</option>)}
        </select></label>
        <label><span>지표</span><select value={metric} onChange={(event) => setMetric(event.target.value as RankingMetric)}>
          <option value="foreign">외국인</option>
          <option value="institution">기관</option>
          <option value="combined">외국인+기관</option>
        </select></label>
        <label><span>방향</span><select value={direction} onChange={(event) => setDirection(event.target.value as RankingDirection)}>
          <option value="inflow">순유입 TOP 100</option>
          <option value="outflow">순유출 TOP 100</option>
        </select></label>
        <label><span>시장</span><select value={market} onChange={(event) => setMarket(event.target.value as RankingMarket)}>
          <option value="ALL">전체 시장</option>
          <option value="KOSPI">KOSPI</option>
          <option value="KOSDAQ">KOSDAQ</option>
        </select></label>
        <label><span>종목 유형</span><select value={assetType} onChange={(event) => setAssetType(event.target.value as RankingAssetType)}>
          <option value="ALL">주식+ETF</option>
          <option value="STOCK">주식만</option>
          <option value="ETF">ETF만</option>
        </select></label>
        <div className="ranking-filter-actions">
          <span>조건을 선택한 후 ‘순위 조회’를 누르면 표에 적용됩니다.</span>
          <button type="button" onClick={handleRankingSearch} disabled={loading}>
            {loading ? "조회 중" : "순위 조회"}
          </button>
        </div>
      </div>

      <div className="ranking-collection panel">
        <div className="ranking-collection-copy">
          <strong>수동 데이터 수집</strong>
          <span>조회 기준일과 별개로 전체 종목 수급 데이터를 요청합니다. 비우면 오늘을 요청합니다.</span>
        </div>
        <label className="ranking-collect-date">
          <span>수집 요청일</span>
          <input type="date" value={collectionDate} onChange={(event) => setCollectionDate(event.target.value)} />
        </label>
        <button type="button" onClick={() => void handleRefresh()} disabled={refreshing || job?.status === "running"}>
          {refreshing || job?.status === "running" ? "수집 중" : "전체 수급 갱신"}
        </button>
      </div>

      {availableDates.length > 0 && (
        <div className="ranking-note panel">
          <span>현재 표시 기준일: <strong>{selectedDate ?? "-"}</strong></span>
          {previousDate
            ? <span>전일 비교 기준: <strong>{previousDate}</strong></span>
            : <span>이전 기준일 데이터가 없어 전일 순위는 `신규`로 표시됩니다. 수동 데이터 수집에서 요청일을 지정해 과거 거래일을 추가할 수 있습니다.</span>}
          <span>열 경계와 각 행 하단의 손잡이를 마우스로 드래그해 표를 조절할 수 있습니다.</span>
        </div>
      )}

      {error && <div className="error">{error}</div>}
      {loading && <div className="ranking-loading panel">순위를 불러오는 중입니다...</div>}
      {!loading && items.length === 0 && <EmptyPanel title="수급 순위" message={dataQuality?.message ?? "먼저 전체 수급 갱신을 실행하세요."} />}
      {!loading && items.length > 0 && (
        <div className="ranking-table-wrap panel">
          <table className="ranking-table" style={{ width: `${rankingTableWidth}px` }}>
            <colgroup>
              {rankingColumns.map((column) => <col key={column.key} style={{ width: `${columnWidths[column.key]}px` }} />)}
            </colgroup>
            <thead>
              <tr>
                {rankingColumns.map((column) => (
                  <SortableHeader
                    key={column.key}
                    column={column}
                    label={column.key === "score" ? `${metricLabel(appliedQuery.metric)} 변동률` : column.label}
                    sortState={sortState}
                    onSort={(key) => setSortState((current) => current.key === key
                      ? { key, direction: current.direction === "asc" ? "desc" : "asc" }
                      : { key, direction: "asc" })}
                    onResizeStart={(event) => startColumnResize(column.key, event, columnWidths, setColumnWidths)}
                  />
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedItems.map((item) => (
                <InvestorRankingRow
                  key={item.code}
                  item={item}
                  metric={appliedQuery.metric}
                  rowHeight={rowHeights[item.code] ?? 30}
                  onSelect={onSelectStock}
                  onResizeStart={(event) => startRowResize(item.code, event, rowHeights, setRowHeights)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function SortableHeader({
  column,
  label,
  sortState,
  onSort,
  onResizeStart,
}: {
  column: { key: RankingColumnKey; label: string; defaultWidth: number; minWidth: number; maxWidth: number };
  label: string;
  sortState: { key: RankingSortKey; direction: SortDirection };
  onSort: (key: RankingSortKey) => void;
  onResizeStart: (event: React.PointerEvent<HTMLButtonElement>) => void;
}) {
  const active = sortState.key === column.key;
  return (
    <th aria-sort={active ? sortState.direction === "asc" ? "ascending" : "descending" : "none"}>
      <button
        type="button"
        className="sortable-heading"
        onClick={() => onSort(column.key)}
        title={`${label} 기준 정렬`}
      >
        <span>{label}</span>
        <small aria-hidden="true">{active ? (sortState.direction === "asc" ? "▲" : "▼") : "↕"}</small>
      </button>
      <button
        type="button"
        className="column-resize-handle"
        aria-label={`${label} 열 너비 조절`}
        onPointerDown={onResizeStart}
        onClick={(event) => event.stopPropagation()}
      />
    </th>
  );
}

function InvestorRankingRow({
  item,
  metric,
  rowHeight,
  onSelect,
  onResizeStart,
}: {
  item: InvestorRankingItem;
  metric: RankingMetric;
  rowHeight: number;
  onSelect: (code: string) => void;
  onResizeStart: (event: React.PointerEvent<HTMLButtonElement>) => void;
}) {
  const score = metricValue(item, metric);
  const rankChange = item.rank_change;
  return (
    <tr style={{ "--ranking-row-height": `${rowHeight}px` } as React.CSSProperties}>
      <td className="rank-number">
        <span>{item.rank}</span>
        <button type="button" className="row-resize-handle" aria-label={`${item.name} 행 높이 조절`} onPointerDown={onResizeStart} />
      </td>
      <td
        className={rankChange == null ? "rank-new" : rankChange > 0 ? "up" : rankChange < 0 ? "down" : ""}
        title={rankChange == null ? "이전 기준일에 같은 종목의 순위가 없어 비교할 수 없습니다." : undefined}
      >
        {rankChange == null ? "신규" : rankChange === 0 ? "-" : `${rankChange > 0 ? "▲" : "▼"}${Math.abs(rankChange)}`}
      </td>
      <td className="ranking-name"><button type="button" onClick={() => onSelect(item.code)}>{item.name}<small>{item.code}</small></button></td>
      <td>{item.market}{item.security_type === "ETF" && <em className="asset-badge">ETF</em>}</td>
      <td>{price(item.close)}</td>
      <td>{moneyWon(item.market_cap)}</td>
      <td className={numberClass(item.foreign_net_qty)}>{shares(item.foreign_net_qty)}</td>
      <td className={numberClass(item.institution_net_qty)}>{shares(item.institution_net_qty)}</td>
      <td className={numberClass(item.combined_change_ratio)}>{ratio(item.combined_change_ratio)}</td>
      <td className={numberClass(score)}>{ratio(score)}</td>
      <td>{ratio(item.foreign_holding_ratio)}</td>
    </tr>
  );
}

function startColumnResize(
  key: RankingColumnKey,
  event: React.PointerEvent<HTMLButtonElement>,
  widths: Record<RankingColumnKey, number>,
  setWidths: React.Dispatch<React.SetStateAction<Record<RankingColumnKey, number>>>,
) {
  event.preventDefault();
  event.stopPropagation();
  const column = rankingColumns.find((item) => item.key === key);
  if (!column) return;
  const startX = event.clientX;
  const startWidth = widths[key];
  const onMove = (moveEvent: PointerEvent) => {
    const nextWidth = clamp(startWidth + moveEvent.clientX - startX, column.minWidth, column.maxWidth);
    setWidths((current) => ({ ...current, [key]: nextWidth }));
  };
  listenForDrag(onMove);
}

function startRowResize(
  code: string,
  event: React.PointerEvent<HTMLButtonElement>,
  heights: Record<string, number>,
  setHeights: React.Dispatch<React.SetStateAction<Record<string, number>>>,
) {
  event.preventDefault();
  event.stopPropagation();
  const startY = event.clientY;
  const startHeight = heights[code] ?? 30;
  const onMove = (moveEvent: PointerEvent) => {
    setHeights((current) => ({ ...current, [code]: clamp(startHeight + moveEvent.clientY - startY, 24, 90) }));
  };
  listenForDrag(onMove);
}

function sortRankingItems(
  items: InvestorRankingItem[],
  sortState: { key: RankingSortKey; direction: SortDirection },
) {
  const multiplier = sortState.direction === "asc" ? 1 : -1;
  return [...items].sort((left, right) => {
    const leftValue = rankingSortValue(left, sortState.key);
    const rightValue = rankingSortValue(right, sortState.key);
    if (leftValue == null && rightValue == null) return left.rank - right.rank;
    if (leftValue == null) return 1;
    if (rightValue == null) return -1;
    const comparison = typeof leftValue === "string" && typeof rightValue === "string"
      ? leftValue.localeCompare(rightValue, "ko")
      : Number(leftValue) - Number(rightValue);
    return comparison === 0 ? left.rank - right.rank : comparison * multiplier;
  });
}

function rankingSortValue(item: InvestorRankingItem, key: RankingSortKey): number | string | null {
  if (key === "name" || key === "market") return item[key];
  if (key === "score") return item.score;
  return item[key];
}

function metricLabel(metric: RankingMetric) {
  if (metric === "institution") return "기관";
  if (metric === "combined") return "합산";
  return "외국인";
}

function metricValue(item: InvestorRankingItem, metric: RankingMetric) {
  if (metric === "institution") return item.institution_change_ratio;
  if (metric === "combined") return item.combined_change_ratio;
  return item.foreign_change_ratio;
}

function ratio(value: number | null | undefined) {
  if (value == null) return "-";
  return `${value > 0 ? "+" : ""}${value.toFixed(4)}%`;
}

function percent(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "-";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function themeCount(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? "-" : fmt(value);
}

function numberClass(value: number | null | undefined) {
  if (value == null || value === 0) return "";
  return value > 0 ? "up" : "down";
}

function SettingsDialog({
  current,
  onClose,
  onSaved,
}: {
  current: KiwoomSettings | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [form, setForm] = useState<KiwoomSettingsPayload>({
    app_key: "",
    secret_key: "",
    account_no: "",
    env: current?.env ?? "real",
    base_url: "",
  });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [authResult, setAuthResult] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    setAuthResult("");
    try {
      await saveKiwoomSettings(form);
      setMessage("저장했습니다. 키는 이 PC의 프로젝트 폴더 .env에만 저장됩니다.");
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "설정 저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  async function runAuthTest() {
    setTesting(true);
    setError("");
    setAuthResult("");
    try {
      const result = await testKiwoomAuth();
      const provider = result.provider;
      const target = provider ? `${provider.environment} ${provider.base_url}` : "";
      setAuthResult(`${result.ok ? "성공" : "실패"}: ${result.message}${target ? ` (${target})` : ""}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "키움 REST 인증 테스트에 실패했습니다.");
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <section className="settings-modal" role="dialog" aria-modal="true" aria-label="키움 API 설정">
        <div className="modal-header">
          <div>
            <h2>키움 API 설정</h2>
            <p>입력한 키는 로컬 `.env` 파일에만 저장됩니다. GitHub에는 올라가지 않습니다.</p>
          </div>
          <button className="icon-button" onClick={onClose} title="닫기"><X size={18} /></button>
        </div>

        <div className="saved-state">
          <span className={current?.configured ? "dot ok-dot" : "dot warn-dot"} />
          {current?.configured ? "저장된 키가 있습니다." : "아직 저장된 키가 없습니다."}
          {current?.app_key_masked && <em>앱키 {current.app_key_masked}</em>}
          {current?.account_no && <em>계좌 {current.account_no}</em>}
          {current?.base_url && <em>{current.env} {current.base_url}</em>}
        </div>

        <form className="settings-form" onSubmit={(event) => void submit(event)}>
          <label>
            <span>앱키</span>
            <input value={form.app_key} onChange={(event) => setForm({ ...form, app_key: event.target.value })} placeholder="KIWOOM_APP_KEY" autoComplete="off" />
          </label>
          <label>
            <span>시크릿키</span>
            <input type="password" value={form.secret_key} onChange={(event) => setForm({ ...form, secret_key: event.target.value })} placeholder="KIWOOM_SECRET_KEY" autoComplete="off" />
          </label>
          <label>
            <span>계좌번호</span>
            <input value={form.account_no} onChange={(event) => setForm({ ...form, account_no: event.target.value })} placeholder={current?.account_no ? "변경 시 입력 (기존 유지)" : "선택 입력"} autoComplete="off" />
          </label>
          <label>
            <span>환경</span>
            <select value={form.env} onChange={(event) => setForm({ ...form, env: event.target.value })}>
              <option value="real">실전(real)</option>
              <option value="mock">모의(mock)</option>
            </select>
          </label>
          <label>
            <span>Base URL</span>
            <input value={form.base_url ?? ""} onChange={(event) => setForm({ ...form, base_url: event.target.value })} placeholder="비우면 환경에 맞게 자동 선택" autoComplete="off" />
          </label>

          {message && <div className="settings-message">{message}</div>}
          {authResult && <div className={authResult.startsWith("성공") ? "settings-message" : "settings-error"}>{authResult}</div>}
          {error && <div className="settings-error">{error}</div>}

          <div className="modal-actions">
            <button type="button" onClick={onClose}>닫기</button>
            <button type="button" onClick={() => void runAuthTest()} disabled={testing || !current?.configured}>
              {testing ? "테스트 중" : "저장된 키 인증 테스트"}
            </button>
            <button type="submit" disabled={saving}>{saving ? "저장 중" : "로컬에 저장"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}

function DashboardView({
  dashboard,
  loading,
  timeframe,
  onTimeframeChange,
}: {
  dashboard: Dashboard;
  loading: boolean;
  timeframe: ChartTimeframe;
  onTimeframeChange: (timeframe: ChartTimeframe) => void;
}) {
  const gridRef = useRef<HTMLDivElement | null>(null);
  const [rightWidth, setRightWidth] = useState(550);
  const [chartHeight, setChartHeight] = useState(465);
  const [themeHeight, setThemeHeight] = useState(112);
  const [investorHeight, setInvestorHeight] = useState(205);

  function startColumnResize(event: React.PointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    const grid = gridRef.current;
    if (!grid) return;
    const bounds = grid.getBoundingClientRect();
    const onMove = (moveEvent: PointerEvent) => {
      const width = bounds.right - moveEvent.clientX;
      setRightWidth(clamp(width, 380, Math.max(bounds.width - 520, 380)));
    };
    listenForDrag(onMove);
  }

  function startHeightResize(setter: React.Dispatch<React.SetStateAction<number>>, min: number, max: number) {
    return (event: React.PointerEvent<HTMLButtonElement>) => {
      event.preventDefault();
      const startY = event.clientY;
      setter((startHeight) => {
        const onMove = (moveEvent: PointerEvent) => setter(clamp(startHeight + moveEvent.clientY - startY, min, max));
        listenForDrag(onMove);
        return startHeight;
      });
    };
  }

  return (
    <section className={loading ? "dashboard busy" : "dashboard"}>
      <Summary dashboard={dashboard} />
      <div className="grid" ref={gridRef} style={{ gridTemplateColumns: `minmax(520px, 1fr) 8px ${rightWidth}px` }}>
        <div className="left-pane">
          <PriceChart dashboard={dashboard} height={chartHeight} timeframe={timeframe} onTimeframeChange={onTimeframeChange} />
          <ResizeBar direction="horizontal" label="차트 높이 조절" onPointerDown={startHeightResize(setChartHeight, 320, 780)} />
          <IndicatorPanel dashboard={dashboard} />
          <DailyTradingPanel dashboard={dashboard} />
        </div>
        <ResizeBar direction="vertical" label="좌우 폭 조절" onPointerDown={startColumnResize} />
        <aside className="right-pane" style={{ gridTemplateRows: `${themeHeight}px 8px ${investorHeight}px 8px minmax(360px, auto)` }}>
          <div className="right-slot"><ThemePanel dashboard={dashboard} /></div>
          <ResizeBar direction="horizontal" label="종목 설명 높이 조절" onPointerDown={startHeightResize(setThemeHeight, 86, 260)} />
          <div className="right-slot"><InvestorPanel dashboard={dashboard} /></div>
          <ResizeBar direction="horizontal" label="수급 패널 높이 조절" onPointerDown={startHeightResize(setInvestorHeight, 150, 420)} />
          <div className="right-slot program-slot"><ProgramPanel dashboard={dashboard} /></div>
        </aside>
      </div>
    </section>
  );
}

function ResizeBar({
  direction,
  label,
  onPointerDown,
}: {
  direction: "vertical" | "horizontal";
  label: string;
  onPointerDown: (event: React.PointerEvent<HTMLButtonElement>) => void;
}) {
  return (
    <button
      type="button"
      className={`resize-bar ${direction}`}
      aria-label={label}
      title={label}
      onPointerDown={onPointerDown}
    />
  );
}

function Summary({ dashboard }: { dashboard: Dashboard }) {
  const { stock, summary, data_quality } = dashboard;
  return (
    <section className="summary">
      <div>
        <h1>{stock.name}</h1>
        <p>{stock.code} · {stock.market} · {stock.sector ?? "업종 없음"}</p>
      </div>
      <Metric label="현재가 · 원" value={price(summary.close)} accent={(summary.change ?? 0) >= 0 ? "up" : "down"} />
      <Metric label="등락률" value={summary.change_rate == null ? "-" : `${summary.change_rate > 0 ? "+" : ""}${summary.change_rate}%`} accent={(summary.change ?? 0) >= 0 ? "up" : "down"} />
      <Metric label="거래량 · 주" value={shares(summary.volume)} />
      <Metric label="거래대금(원화)" value={moneyFromMillionWon(summary.trading_value)} />
      <Metric label="회전률" value={summary.turnover_rate == null ? "-" : `${summary.turnover_rate}%`} />
      <div className="description">
        <strong>{statusText(data_quality)}</strong>
        <span>{summary.description}</span>
      </div>
    </section>
  );
}

function Metric({ label, value, accent }: { label: string; value: string; accent?: "up" | "down" }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={accent}>{value}</strong>
    </div>
  );
}

function StatusBadge({ quality, configured }: { quality: DataQuality | null | undefined; configured?: boolean }) {
  const status = quality?.connection_status ?? quality?.status;
  const label = configured && !quality ? "키움 API 저장됨" : statusText(quality);
  return <div className={status === "ok" || configured ? "status ok" : "status warn"}>{label}</div>;
}

function PriceChart({
  dashboard,
  height,
  timeframe,
  onTimeframeChange,
}: {
  dashboard: Dashboard;
  height: number;
  timeframe: ChartTimeframe;
  onTimeframeChange: (timeframe: ChartTimeframe) => void;
}) {
  if (dashboard.ohlcv.length === 0) {
    return <EmptyPanel title={`${timeframeLabel(timeframe)} 차트`} message={panelMessage(dashboard.data_quality, "chart_status")} />;
  }
  return (
    <section className="panel chart-panel" style={{ height }}>
      <div className="panel-title chart-title">
        <span className="chart-title-copy">{timeframeLabel(timeframe)} 가격·거래량 차트 · 과거 {dashboard.ohlcv.length}개</span>
        <div className="timeframe-tabs">
          {chartTimeframes.map((item) => (
            <button
              key={item.value}
              type="button"
              className={timeframe === item.value ? "active" : ""}
              onClick={() => onTimeframeChange(item.value)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <span className="chart-legend">
          <span><i className="ma5" />이평 5</span>
          <span><i className="ma10" />이평 10</span>
          <span><i className="ma20" />이평 20</span>
          <span><i className="ma60" />이평 60</span>
          <span><i className="ma120" />이평 120</span>
        </span>
      </div>
      <ChartStats rows={dashboard.ohlcv} />
      <TradingChart dashboard={dashboard} />
    </section>
  );
}

function ChartStats({ rows }: { rows: Ohlcv[] }) {
  const latest = rows[rows.length - 1];
  const first = rows[0];
  const high = Math.max(...rows.map((row) => row.high));
  const low = Math.min(...rows.map((row) => row.low));
  const averageVolume = rows.reduce((sum, row) => sum + row.volume, 0) / rows.length;
  const periodReturn = first?.close ? ((latest.close / first.close) - 1) * 100 : null;
  return (
    <div className="chart-stats">
      <span><small>기간 고가</small><strong>{price(high)}</strong></span>
      <span><small>기간 저가</small><strong>{price(low)}</strong></span>
      <span><small>기간 수익률</small><strong className={numberClass(periodReturn)}>{percent(periodReturn)}</strong></span>
      <span><small>평균 거래량</small><strong>{shares(averageVolume)}</strong></span>
      <span><small>최근 거래대금(원화)</small><strong>{moneyFromMillionWon(latest?.trading_value)}</strong></span>
    </div>
  );
}

function TradingChart({ dashboard }: { dashboard: Dashboard }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    const tooltip = tooltipRef.current;
    if (!container || !tooltip) return;

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#f6f8fa" },
        textColor: "#2b3c4d",
        fontFamily: "\"Malgun Gothic\", \"Segoe UI\", sans-serif",
        fontSize: 12,
      },
      grid: {
        vertLines: { color: "#d4dde7" },
        horzLines: { color: "#d4dde7" },
      },
      rightPriceScale: {
        borderColor: "#a9b7c6",
        minimumWidth: 96,
        scaleMargins: { top: 0.08, bottom: 0.28 },
      },
      leftPriceScale: {
        borderColor: "#a9b7c6",
        minimumWidth: 96,
        scaleMargins: { top: 0.78, bottom: 0 },
      },
      timeScale: {
        borderColor: "#a9b7c6",
        timeVisible: false,
        secondsVisible: false,
        rightOffset: 8,
        barSpacing: 8,
      },
      crosshair: {
        mode: 1,
        vertLine: { color: "#5f7287", labelBackgroundColor: "#315f99" },
        horzLine: { color: "#5f7287", labelBackgroundColor: "#315f99" },
      },
      localization: {
        priceFormatter: (value: number) => price(value),
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#e12424",
      downColor: "#1268c4",
      borderUpColor: "#e12424",
      borderDownColor: "#1268c4",
      wickUpColor: "#26384b",
      wickDownColor: "#26384b",
    });
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "custom", formatter: compactShares, minMove: 1 },
      priceScaleId: "left",
      color: "#7f97b0",
      priceLineVisible: false,
      lastValueVisible: false,
    });

    const rows = dashboard.ohlcv;
    const candleData: CandlestickData<Time>[] = rows.map((row) => ({
      time: row.date,
      open: row.open,
      high: row.high,
      low: row.low,
      close: row.close,
    }));
    const volumeData: HistogramData<Time>[] = rows.map((row) => ({
      time: row.date,
      value: row.volume,
      color: row.close >= row.open ? "rgba(225, 36, 36, 0.82)" : "rgba(18, 104, 196, 0.82)",
    }));

    candleSeries.setData(candleData);
    volumeSeries.setData(volumeData);

    const maSeries = [
      addMaLine(chart, "#d87b00", 1),
      addMaLine(chart, "#7f52c7", 1),
      addMaLine(chart, "#0b8f72", 1),
      addMaLine(chart, "#4d74c8", 2),
      addMaLine(chart, "#7d8792", 2),
    ];
    [5, 10, 20, 60, 120].forEach((window, index) => {
      maSeries[index].setData(toLineData(rows, dashboard.indicators.ma[String(window)] ?? []));
    });

    const crosshairHandler = (param: MouseEventParams<Time>) => {
      if (!param.point || !param.time || param.point.x < 0 || param.point.y < 0) {
        tooltip.classList.remove("visible");
        return;
      }
      const candle = param.seriesData.get(candleSeries) as CandlestickData<Time> | undefined;
      const volume = param.seriesData.get(volumeSeries) as HistogramData<Time> | undefined;
      if (!candle) {
        tooltip.classList.remove("visible");
        return;
      }
      const date = typeof param.time === "string" ? param.time : String(param.time);
      tooltip.innerHTML = `
        <strong>${date}</strong>
        <span>시 ${price(candle.open)} · 고 ${price(candle.high)} · 저 ${price(candle.low)} · 종 ${price(candle.close)}</span>
        <span>거래량 ${shares(volume?.value)} · 거래대금 ${moneyFromMillionWon(rowByDate(rows, date)?.trading_value)}</span>
      `;
      const left = Math.min(Math.max(param.point.x + 14, 8), container.clientWidth - 270);
      const top = Math.min(Math.max(param.point.y + 14, 8), container.clientHeight - 78);
      tooltip.style.transform = `translate(${left}px, ${top}px)`;
      tooltip.classList.add("visible");
    };
    chart.subscribeCrosshairMove(crosshairHandler);
    chart.timeScale().fitContent();

    return () => {
      chart.unsubscribeCrosshairMove(crosshairHandler);
      chart.remove();
    };
  }, [dashboard]);

  return (
    <div className="trading-chart-wrap">
      <div className="trading-chart" ref={containerRef} />
      <div className="chart-tooltip" ref={tooltipRef} />
    </div>
  );
}

function IndicatorPanel({ dashboard }: { dashboard: Dashboard }) {
  const hasPriceData = dashboard.ohlcv.length > 0;
  const marketAdr = dashboard.market_adr ?? [];
  const adrValues = marketAdr.map((row) => row.adr);
  return (
    <section className="indicator-stack">
      {hasPriceData ? <Spark title="OBV" values={dashboard.indicators.obv} /> : <EmptyPanel title="OBV" message="일봉 데이터가 없어 계산하지 못했습니다." />}
      {hasPriceData ? <Spark title="RSI 14" values={dashboard.indicators.rsi14} guide={50} /> : <EmptyPanel title="RSI 14" message="일봉 데이터가 없어 계산하지 못했습니다." />}
      {marketAdr.length > 0 ? <Spark title="시장 ADR" values={adrValues} guide={100} /> : <EmptyPanel title="시장 ADR" message={panelMessage(dashboard.data_quality, "adr_status")} />}
      {hasPriceData ? <Spark title="심리도 10" values={dashboard.indicators.sentiment10} guide={50} /> : <EmptyPanel title="심리도 10" message="일봉 데이터가 없어 계산하지 못했습니다." />}
    </section>
  );
}

function Spark({ title, values, guide }: { title: string; values: Array<number | null>; guide?: number }) {
  const valid = values.filter((value): value is number => value != null).slice(-90);
  const points = useMemo(() => sparkPoints(valid), [valid]);
  const latest = valid.length > 0 ? valid[valid.length - 1] : undefined;
  return (
    <div className="spark panel">
      <div className="panel-title">{title}{latest == null ? "" : ` · ${fmt(latest)}`}</div>
      <svg viewBox="0 0 900 90" preserveAspectRatio="none" role="img">
        {guide != null && <line x1="0" x2="900" y1="45" y2="45" className="guide" />}
        <polyline points={points} />
      </svg>
    </div>
  );
}

function DailyTradingPanel({ dashboard }: { dashboard: Dashboard }) {
  if (dashboard.ohlcv.length === 0) {
    return <EmptyPanel title="일별 거래대금" message={panelMessage(dashboard.data_quality, "chart_status")} />;
  }
  const listedShares = dashboard.stock.listed_shares || 0;
  return (
    <section className="panel daily-panel">
      <div className="panel-title">{historyLabel(dashboard.timeframe ?? "daily")} 과거 내역 · 거래대금 · 거래량 회전률</div>
      <table>
        <thead>
          <tr>
            <th>일자</th>
            <th>종가(원)</th>
            <th>거래량(주)</th>
            <th>거래대금(원화)</th>
            <th>회전률</th>
          </tr>
        </thead>
        <tbody>
          {dashboard.ohlcv.slice().reverse().map((row) => (
            <tr key={row.date}>
              <td>{row.date}</td>
              <td>{price(row.close)}</td>
              <td>{shares(row.volume)}</td>
              <td>{moneyFromMillionWon(row.trading_value)}</td>
              <td>{listedShares ? `${((row.volume / listedShares) * 100).toFixed(4)}%` : "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ThemePanel({ dashboard }: { dashboard: Dashboard }) {
  const themes = (dashboard.themes ?? []).filter((theme) => Boolean(theme.name?.trim())).slice(0, 8);
  const themeStatus = dashboard.data_quality.theme_status;
  const emptyMessage = themeStatus === "ok"
    ? "이 종목에 대해 확인된 관련 테마가 없습니다."
    : panelMessage(dashboard.data_quality, "theme_status");

  return (
    <section className="panel theme-panel">
      <div className="panel-title">종목 개요 · 관련 테마</div>
      <p className="theme-description">{dashboard.summary.description}</p>
      {themes.length > 0 && <div className="theme-context">키움 API 관련 테마 · 최대 8개 표시</div>}
      <div className="theme-list">
        {themes.length > 0
          ? themes.map((theme) => (
            <article className="theme-card" key={theme.code}>
              <div className="theme-card-heading">
                <strong>{theme.name}</strong>
              </div>
              {theme.stock_count != null && Number.isFinite(theme.stock_count) && (
                <div className="theme-card-meta">구성 {fmt(theme.stock_count)}종목</div>
              )}
              <div className="theme-card-stats">
                <span className={numberClass(theme.change_rate)}>등락률 {percent(theme.change_rate)}</span>
                <span>기간 수익률 {percent(theme.period_return)}</span>
              </div>
              {(theme.rising_count != null || theme.falling_count != null) && (
                <small className="theme-card-breadth">
                  상승 {themeCount(theme.rising_count)} · 하락 {themeCount(theme.falling_count)}
                </small>
              )}
              {theme.main_stock?.trim() && <small className="theme-card-breadth">대표 종목 {theme.main_stock.trim()}</small>}
            </article>
          ))
          : <span className="theme-empty">{emptyMessage}</span>}
      </div>
    </section>
  );
}

function InvestorPanel({ dashboard }: { dashboard: Dashboard }) {
  const recentOutflow = dashboard.investor_summary?.recent_outflow_5d ?? { foreign_ratio: 0, institution_ratio: 0 };
  if (dashboard.investors.length === 0) {
    return <EmptyPanel title="외국인/기관 누적 수급" message={panelMessage(dashboard.data_quality, "investor_status")} />;
  }
  return (
    <section className="panel investor-panel">
      <div className="panel-title">외국인/기관 누적 수급 · 상장주식수 대비</div>
      <table>
        <thead>
          <tr>
            <th>기간</th>
            <th>외국인 수량(주)</th>
            <th>외국인 금액(원화)</th>
            <th>비율</th>
            <th>기관 수량(주)</th>
            <th>기관 금액(원화)</th>
            <th>비율</th>
          </tr>
        </thead>
        <tbody>
          {periods.map((period) => {
            const row = dashboard.investor_summary?.periods?.[period] ?? emptyPeriodFlow();
            return (
              <tr key={period}>
                <td>{period}일</td>
                <td className={row.foreign_qty >= 0 ? "up" : "down"}>{shares(row.foreign_qty)}</td>
                <td className={row.foreign_value >= 0 ? "up" : "down"}>{moneyFromMillionWon(row.foreign_value)}</td>
                <td>{row.foreign_ratio}%</td>
                <td className={row.institution_qty >= 0 ? "up" : "down"}>{shares(row.institution_qty)}</td>
                <td className={row.institution_value >= 0 ? "up" : "down"}>{moneyFromMillionWon(row.institution_value)}</td>
                <td>{row.institution_ratio}%</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="mini-note">
        최근 5일 이탈률: 외국인 {recentOutflow.foreign_ratio}% · 기관 {recentOutflow.institution_ratio}%
      </div>
    </section>
  );
}

function ProgramPanel({ dashboard }: { dashboard: Dashboard }) {
  if (dashboard.program_trading.length === 0) {
    return <EmptyPanel title="프로그램매매 비차익 추이" message={panelMessage(dashboard.data_quality, "program_status")} />;
  }
  return (
    <section className="panel program">
      <div className="panel-title">프로그램매매 비차익 추이</div>
      <div className="program-summary">
        {periods.map((period) => (
          <span key={period}>{period}일 {moneyFromMillionWon(dashboard.program_summary[period]?.net_amount_m)}</span>
        ))}
      </div>
      <table>
        <thead>
          <tr>
            <th>일자</th>
            <th>현재가(원)</th>
            <th>등락률</th>
            <th>거래량(주)</th>
            <th>매도(원화)</th>
            <th>매수(원화)</th>
            <th>순매수(원화)</th>
          </tr>
        </thead>
        <tbody>
          {dashboard.program_trading.slice(-18).reverse().map((row) => (
            <tr key={row.date}>
              <td>{row.date.slice(5)}</td>
              <td>{price(row.close)}</td>
              <td className={(row.change_rate ?? 0) >= 0 ? "up" : "down"}>{row.change_rate == null ? "-" : `${row.change_rate}%`}</td>
              <td>{shares(row.volume)}</td>
              <td>{moneyFromMillionWon(row.sell_amount_m)}</td>
              <td>{moneyFromMillionWon(row.buy_amount_m)}</td>
              <td className={row.net_amount_m >= 0 ? "up" : "down"}>{moneyFromMillionWon(row.net_amount_m)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function EmptyPanel({ title, message }: { title: string; message: string }) {
  return (
    <section className="panel empty-panel">
      <div className="panel-title">{title}</div>
      <div className="empty-body">
        <strong>데이터 없음</strong>
        <span>{message}</span>
      </div>
    </section>
  );
}

function emptyPeriodFlow() {
  return {
    foreign_qty: 0,
    foreign_value: 0,
    foreign_ratio: 0,
    institution_qty: 0,
    institution_value: 0,
    institution_ratio: 0,
    days: 0,
  };
}

function statusText(quality: DataQuality | null | undefined) {
  const status = quality?.connection_status ?? quality?.status;
  if (!quality) return "상태 확인 중";
  if (status === "ok") return "키움 REST 연결됨";
  if (status === "api_not_configured") return "API 미설정";
  if (status === "auth_failed") return "인증 실패";
  if (status === "token_expired") return "토큰 만료";
  if (status === "rate_limited") return "요청 제한";
  if (status === "network_error") return "네트워크 오류";
  return "데이터 없음";
}

function panelMessage(quality: DataQuality, key: keyof DataQuality) {
  const status = quality[key];
  if (status === "api_not_configured") return "키움 REST API 키가 없어 데이터를 요청하지 못했습니다.";
  if (status === "auth_failed") return "키움 REST 인증에 실패했습니다. .env의 앱키/시크릿키를 확인하세요.";
  if (status === "token_expired") return "키움 접근토큰이 만료되었습니다. 다시 갱신해 주세요.";
  if (status === "network_error") return "키움 REST 서버에 연결하지 못했습니다.";
  if (status === "rate_limited") return "키움 REST 요청 제한에 걸렸습니다.";
  if (status === "unavailable") return "키움 REST 응답에서 이 항목을 가져오지 못했습니다.";
  if (status === "api_error") return "키움 REST API가 이 항목에 오류를 반환했습니다.";
  return quality.messages?.[0] ?? "데이터가 수신되지 않았습니다.";
}

function scale(value: number, min: number, max: number) {
  return ((value - min) / Math.max(max - min, 1)) * 100;
}

function sparkPoints(values: number[]) {
  if (values.length === 0) return "";
  const max = Math.max(...values);
  const min = Math.min(...values);
  return values.map((value, idx) => {
    const x = (idx / Math.max(values.length - 1, 1)) * 900;
    const y = 84 - ((value - min) / Math.max(max - min, 1)) * 78;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function fmt(value: number | null | undefined) {
  if (value == null) return "-";
  return Math.round(value).toLocaleString("ko-KR");
}

function price(value: number | null | undefined) {
  return value == null ? "-" : `${fmt(value)}원`;
}

function shares(value: number | null | undefined) {
  return value == null ? "-" : `${fmt(value)}주`;
}

function compactShares(value: number | null | undefined) {
  if (value == null) return "-";
  const sign = value < 0 ? "-" : "";
  const absolute = Math.abs(value);
  const compact = (divisor: number) => Number((absolute / divisor).toFixed(1)).toLocaleString("ko-KR", { maximumFractionDigits: 1 });
  if (absolute >= 100_000_000) return `${sign}${compact(100_000_000)}억주`;
  if (absolute >= 10_000) return `${sign}${compact(10_000)}만주`;
  return `${sign}${Math.round(absolute).toLocaleString("ko-KR")}주`;
}

function moneyWon(value: number | null | undefined) {
  return value == null ? "-" : compactWon(value);
}

function moneyFromMillionWon(value: number | null | undefined) {
  if (value == null) return "-";
  return compactWon(value * 1_000_000);
}

function compactWon(value: number) {
  const sign = value < 0 ? "-" : "";
  const absolute = Math.abs(value);
  if (absolute >= 1_000_000_000_000) return `${sign}${(absolute / 1_000_000_000_000).toFixed(2)}조원`;
  if (absolute >= 100_000_000) return `${sign}${(absolute / 100_000_000).toFixed(1)}억원`;
  if (absolute >= 10_000) return `${sign}${(absolute / 10_000).toFixed(1)}만원`;
  return `${sign}${Math.round(absolute).toLocaleString("ko-KR")}원`;
}

function timeframeLabel(timeframe: ChartTimeframe) {
  if (timeframe === "weekly") return "주봉";
  if (timeframe === "monthly") return "월봉";
  return "일봉";
}

function historyLabel(timeframe: ChartTimeframe) {
  if (timeframe === "weekly") return "주간";
  if (timeframe === "monthly") return "월간";
  return "일별";
}

function addMaLine(chart: ReturnType<typeof createChart>, color: string, lineWidth: 1 | 2): ISeriesApi<"Line", Time> {
  return chart.addSeries(LineSeries, {
    color,
    lineWidth,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
  });
}

function toLineData(rows: Ohlcv[], values: Array<number | null>): LineData<Time>[] {
  const data: LineData<Time>[] = [];
  rows.forEach((row, index) => {
    const value = values[index];
    if (value != null) data.push({ time: row.date, value });
  });
  return data;
}

function rowByDate(rows: Ohlcv[], date: string) {
  return rows.find((row) => row.date === date);
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function listenForDrag(onMove: (event: PointerEvent) => void) {
  const onUp = () => {
    document.body.classList.remove("is-resizing");
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
  };
  document.body.classList.add("is-resizing");
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp, { once: true });
}

createRoot(document.getElementById("root")!).render(<App />);
