import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { BarChart3, RefreshCw, Search, Settings as SettingsIcon, X } from "lucide-react";
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
  const [view, setView] = useState<"dashboard" | "rankings">("dashboard");

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
      setView("dashboard");
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
        <button className={`action ${view === "rankings" ? "active-action" : ""}`} onClick={() => setView("rankings")} title="외국인·기관 수급 순위">
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
            setView("dashboard");
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
  const [response, setResponse] = useState<Awaited<ReturnType<typeof getInvestorRanking>> | null>(null);
  const [jobStatus, setJobStatus] = useState<InvestorRankingStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  async function loadStatus() {
    try {
      setJobStatus(await getInvestorRankingStatus());
    } catch (err) {
      setError(err instanceof Error ? err.message : "수급 수집 상태를 불러오지 못했습니다.");
    }
  }

  async function loadRanking() {
    setLoading(true);
    setError("");
    try {
      const next = await getInvestorRanking({ date: date || undefined, metric, direction, market, assetType });
      setResponse(next);
      if (!date && next.date) setDate(next.date);
    } catch (err) {
      setError(err instanceof Error ? err.message : "수급 순위를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadStatus();
  }, []);

  useEffect(() => {
    void loadRanking();
  }, [date, metric, direction, market, assetType]);

  useEffect(() => {
    if (jobStatus?.job.status !== "running") return;
    const timer = window.setInterval(() => {
      void getInvestorRankingStatus().then((next) => {
        setJobStatus(next);
        if (next.job.status !== "running") void loadRanking();
      }).catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [jobStatus?.job.status]);

  async function handleRefresh() {
    setRefreshing(true);
    setError("");
    try {
      await refreshInvestorRanking(date || undefined);
      await loadStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "전체 수급 갱신을 시작하지 못했습니다.");
    } finally {
      setRefreshing(false);
    }
  }

  const job = jobStatus?.job;
  const items = response?.items ?? [];
  const dataQuality = response?.data_quality;
  const statusMessage = job?.status === "running"
    ? `${job.message ?? "수집 중"} (${job.completed.toLocaleString("ko-KR")}/${job.total.toLocaleString("ko-KR")})`
    : job?.message ?? dataQuality?.message ?? "전체 종목 일별 수급 데이터가 없습니다.";

  return (
    <section className="ranking-view">
      <div className="ranking-heading panel">
        <div>
          <h1>외국인·기관 수급 순위</h1>
          <p>시총 대비 일일 보유변동률 · 전체 종목 및 ETF</p>
        </div>
        <div className={`ranking-job ${job?.status === "running" ? "running" : ""}`}>
          <span>{statusMessage}</span>
          <button type="button" onClick={() => void handleRefresh()} disabled={refreshing || job?.status === "running"}>
            {refreshing || job?.status === "running" ? "수집 중" : "전체 수급 갱신"}
          </button>
        </div>
      </div>

      <div className="ranking-filters panel">
        <label><span>기준일</span><select value={date} onChange={(event) => setDate(event.target.value)}>
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
      </div>

      {error && <div className="error">{error}</div>}
      {loading && <div className="ranking-loading panel">순위를 불러오는 중입니다...</div>}
      {!loading && items.length === 0 && <EmptyPanel title="수급 순위" message={dataQuality?.message ?? "먼저 전체 수급 갱신을 실행하세요."} />}
      {!loading && items.length > 0 && (
        <div className="ranking-table-wrap panel">
          <table className="ranking-table">
            <thead>
              <tr>
                <th>순위</th>
                <th>전일</th>
                <th>종목</th>
                <th>시장</th>
                <th>종가</th>
                <th>시가총액</th>
                <th>외국인 수량</th>
                <th>기관 수량</th>
                <th>합산 변동률</th>
                <th>{metricLabel(metric)} 변동률</th>
                <th>외국인 실제 보유율</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <InvestorRankingRow key={item.code} item={item} metric={metric} onSelect={onSelectStock} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function InvestorRankingRow({ item, metric, onSelect }: { item: InvestorRankingItem; metric: RankingMetric; onSelect: (code: string) => void }) {
  const score = metricValue(item, metric);
  const rankChange = item.rank_change;
  return (
    <tr>
      <td className="rank-number">{item.rank}</td>
      <td className={rankChange == null ? "rank-new" : rankChange > 0 ? "up" : rankChange < 0 ? "down" : ""}>
        {rankChange == null ? "신규" : rankChange === 0 ? "-" : `${rankChange > 0 ? "▲" : "▼"}${Math.abs(rankChange)}`}
      </td>
      <td className="ranking-name"><button type="button" onClick={() => onSelect(item.code)}>{item.name}<small>{item.code}</small></button></td>
      <td>{item.market}{item.security_type === "ETF" && <em className="asset-badge">ETF</em>}</td>
      <td>{fmt(item.close)}</td>
      <td>{money(item.market_cap)}</td>
      <td className={numberClass(item.foreign_net_qty)}>{fmt(item.foreign_net_qty)}</td>
      <td className={numberClass(item.institution_net_qty)}>{fmt(item.institution_net_qty)}</td>
      <td className={numberClass(item.combined_change_ratio)}>{ratio(item.combined_change_ratio)}</td>
      <td className={numberClass(score)}>{ratio(score)}</td>
      <td>{ratio(item.foreign_holding_ratio)}</td>
    </tr>
  );
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
    account_no: current?.account_no ?? "",
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
            <input value={form.account_no} onChange={(event) => setForm({ ...form, account_no: event.target.value })} placeholder="선택 입력" autoComplete="off" />
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
      <Metric label="현재가" value={fmt(summary.close)} accent={(summary.change ?? 0) >= 0 ? "up" : "down"} />
      <Metric label="등락률" value={summary.change_rate == null ? "-" : `${summary.change_rate > 0 ? "+" : ""}${summary.change_rate}%`} accent={(summary.change ?? 0) >= 0 ? "up" : "down"} />
      <Metric label="거래량" value={fmt(summary.volume)} />
      <Metric label="거래대금" value={money(summary.trading_value)} />
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
        <span>{timeframeLabel(timeframe)} 차트 · MA 5/10/20/60/120 · 과거 {dashboard.ohlcv.length}개</span>
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
          <i className="ma5" />5 <i className="ma10" />10 <i className="ma20" />20 <i className="ma60" />60 <i className="ma120" />120
        </span>
      </div>
      <TradingChart dashboard={dashboard} />
    </section>
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
        scaleMargins: { top: 0.08, bottom: 0.28 },
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
        priceFormatter: (price: number) => price.toLocaleString("ko-KR"),
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
      priceFormat: { type: "volume" },
      priceScaleId: "",
      color: "#7f97b0",
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.78, bottom: 0 },
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
        <span>시 ${fmt(candle.open)} · 고 ${fmt(candle.high)} · 저 ${fmt(candle.low)} · 종 ${fmt(candle.close)}</span>
        <span>거래량 ${fmt(volume?.value)} · 거래대금 ${money(rowByDate(rows, date)?.trading_value)}</span>
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
            <th>종가</th>
            <th>거래량</th>
            <th>거래대금</th>
            <th>회전률</th>
          </tr>
        </thead>
        <tbody>
          {dashboard.ohlcv.slice().reverse().map((row) => (
            <tr key={row.date}>
              <td>{row.date}</td>
              <td>{fmt(row.close)}</td>
              <td>{fmt(row.volume)}</td>
              <td>{money(row.trading_value)}</td>
              <td>{listedShares ? `${((row.volume / listedShares) * 100).toFixed(4)}%` : "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ThemePanel({ dashboard }: { dashboard: Dashboard }) {
  return (
    <section className="panel theme-panel">
      <div className="panel-title">종목 설명 · 테마</div>
      <p className="theme-description">{dashboard.summary.description}</p>
      <div className="theme-list">
        {dashboard.themes && dashboard.themes.length > 0
          ? dashboard.themes.slice(0, 8).map((theme) => <span key={theme.code}>{theme.name}</span>)
          : <span>테마 정보 없음</span>}
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
            <th>외국인 수량</th>
            <th>외국인 금액</th>
            <th>비율</th>
            <th>기관 수량</th>
            <th>기관 금액</th>
            <th>비율</th>
          </tr>
        </thead>
        <tbody>
          {periods.map((period) => {
            const row = dashboard.investor_summary?.periods?.[period] ?? emptyPeriodFlow();
            return (
              <tr key={period}>
                <td>{period}일</td>
                <td className={row.foreign_qty >= 0 ? "up" : "down"}>{fmt(row.foreign_qty)}</td>
                <td className={row.foreign_value >= 0 ? "up" : "down"}>{money(row.foreign_value)}</td>
                <td>{row.foreign_ratio}%</td>
                <td className={row.institution_qty >= 0 ? "up" : "down"}>{fmt(row.institution_qty)}</td>
                <td className={row.institution_value >= 0 ? "up" : "down"}>{money(row.institution_value)}</td>
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
          <span key={period}>{period}일 {fmt(dashboard.program_summary[period]?.net_amount_m)}백만</span>
        ))}
      </div>
      <table>
        <thead>
          <tr>
            <th>일자</th>
            <th>현재가</th>
            <th>등락률</th>
            <th>거래량</th>
            <th>매도</th>
            <th>매수</th>
            <th>순매수</th>
          </tr>
        </thead>
        <tbody>
          {dashboard.program_trading.slice(-18).reverse().map((row) => (
            <tr key={row.date}>
              <td>{row.date.slice(5)}</td>
              <td>{fmt(row.close)}</td>
              <td className={(row.change_rate ?? 0) >= 0 ? "up" : "down"}>{row.change_rate == null ? "-" : `${row.change_rate}%`}</td>
              <td>{fmt(row.volume)}</td>
              <td>{fmt(row.sell_amount_m)}</td>
              <td>{fmt(row.buy_amount_m)}</td>
              <td className={row.net_amount_m >= 0 ? "up" : "down"}>{fmt(row.net_amount_m)}</td>
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

function money(value: number | null | undefined) {
  if (value == null) return "-";
  if (Math.abs(value) >= 100_000_000) return `${(value / 100_000_000).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}억`;
  return fmt(value);
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
