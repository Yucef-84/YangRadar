import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { RefreshCw, Search } from "lucide-react";
import { getDashboard, refreshStock, searchStocks } from "./api";
import type { Dashboard, DataQuality, Stock } from "./types";
import "./styles.css";

const periods = ["5", "20", "60", "120"];

function App() {
  const [query, setQuery] = useState("삼성전자");
  const [results, setResults] = useState<Stock[]>([]);
  const [selected, setSelected] = useState("005930");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [searchQuality, setSearchQuality] = useState<DataQuality | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void loadDashboard(selected);
  }, [selected]);

  async function runSearch() {
    setError("");
    try {
      const response = await searchStocks(query);
      setResults(response.items);
      setSearchQuality(response.data_quality);
      if (response.items[0]) setSelected(response.items[0].code);
    } catch (err) {
      setError(err instanceof Error ? err.message : "검색 중 오류가 발생했습니다.");
    }
  }

  async function loadDashboard(code: string) {
    setLoading(true);
    setError("");
    try {
      setDashboard(await getDashboard(code));
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
      setDashboard(await getDashboard(dashboard.stock.code));
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
        <StatusBadge quality={dashboard?.data_quality ?? searchQuality} />
      </header>

      {results.length > 0 && (
        <div className="result-strip">
          {results.map((stock) => (
            <button key={stock.code} onClick={() => setSelected(stock.code)} className={selected === stock.code ? "active" : ""}>
              {stock.name} <span>{stock.code}</span>
            </button>
          ))}
        </div>
      )}

      {error && <div className="error">{error}</div>}
      {dashboard && <DashboardView dashboard={dashboard} loading={loading} />}
    </main>
  );
}

function DashboardView({ dashboard, loading }: { dashboard: Dashboard; loading: boolean }) {
  return (
    <section className={loading ? "dashboard busy" : "dashboard"}>
      <Summary dashboard={dashboard} />
      <div className="grid">
        <div className="left-pane">
          <PriceChart dashboard={dashboard} />
          <IndicatorPanel dashboard={dashboard} />
        </div>
        <aside className="right-pane">
          <ThemePanel dashboard={dashboard} />
          <InvestorPanel dashboard={dashboard} />
          <ProgramPanel dashboard={dashboard} />
        </aside>
      </div>
    </section>
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

function StatusBadge({ quality }: { quality: DataQuality | null | undefined }) {
  const status = quality?.connection_status ?? quality?.status;
  const label = statusText(quality);
  return <div className={status === "ok" ? "status ok" : "status warn"}>{label}</div>;
}

function PriceChart({ dashboard }: { dashboard: Dashboard }) {
  if (dashboard.ohlcv.length === 0) {
    return <EmptyPanel title="일봉 차트" message={panelMessage(dashboard.data_quality, "chart_status")} />;
  }
  const max = Math.max(...dashboard.ohlcv.map((row) => row.high));
  const min = Math.min(...dashboard.ohlcv.map((row) => row.low));
  const candles = dashboard.ohlcv.slice(-90);
  return (
    <section className="panel chart-panel">
      <div className="panel-title">일봉 차트 · MA 5/10/20/60/120</div>
      <div className="candles">
        {candles.map((row, idx) => {
          const top = scale(row.high, min, max);
          const bottom = scale(row.low, min, max);
          const open = scale(row.open, min, max);
          const close = scale(row.close, min, max);
          const up = row.close >= row.open;
          return (
            <div className="candle-slot" key={row.date} title={`${row.date} ${fmt(row.close)}`}>
              <span className="wick" style={{ top: `${100 - top}%`, height: `${Math.max(top - bottom, 1)}%` }} />
              <span
                className={up ? "body up-bg" : "body down-bg"}
                style={{ top: `${100 - Math.max(open, close)}%`, height: `${Math.max(Math.abs(open - close), 1.5)}%` }}
              />
              {idx % 15 === 0 && <em>{row.date.slice(5)}</em>}
            </div>
          );
        })}
      </div>
      <VolumeBars rows={candles} />
    </section>
  );
}

function VolumeBars({ rows }: { rows: Dashboard["ohlcv"] }) {
  const max = Math.max(...rows.map((row) => row.volume), 1);
  return (
    <div className="volumes">
      {rows.map((row) => (
        <span
          key={row.date}
          className={row.close >= row.open ? "up-bg" : "down-bg"}
          style={{ height: `${Math.max((row.volume / max) * 100, 2)}%` }}
          title={`${row.date} ${fmt(row.volume)}`}
        />
      ))}
    </div>
  );
}

function IndicatorPanel({ dashboard }: { dashboard: Dashboard }) {
  if (dashboard.ohlcv.length === 0) {
    return (
      <section className="indicator-stack">
        <EmptyPanel title="OBV" message="일봉 실데이터가 없어 계산하지 않았습니다." />
        <EmptyPanel title="RSI 14" message="일봉 실데이터가 없어 계산하지 않았습니다." />
        <EmptyPanel title="심리도 10" message="일봉 실데이터가 없어 계산하지 않았습니다." />
      </section>
    );
  }
  return (
    <section className="indicator-stack">
      <Spark title="OBV" values={dashboard.indicators.obv} />
      <Spark title="RSI 14" values={dashboard.indicators.rsi14} guide={50} />
      <Spark title="심리도 10" values={dashboard.indicators.sentiment10} guide={50} />
    </section>
  );
}

function Spark({ title, values, guide }: { title: string; values: Array<number | null>; guide?: number }) {
  const valid = values.filter((value): value is number => value != null).slice(-90);
  const points = useMemo(() => sparkPoints(valid), [valid]);
  return (
    <div className="spark panel">
      <div className="panel-title">{title}</div>
      <svg viewBox="0 0 900 90" preserveAspectRatio="none" role="img">
        {guide != null && <line x1="0" x2="900" y1="45" y2="45" className="guide" />}
        <polyline points={points} />
      </svg>
    </div>
  );
}

function ThemePanel({ dashboard }: { dashboard: Dashboard }) {
  if (!dashboard.themes || dashboard.themes.length === 0) {
    return <EmptyPanel title="종목 테마" message={panelMessage(dashboard.data_quality, "theme_status")} />;
  }
  return (
    <section className="panel theme-panel">
      <div className="panel-title">종목 테마</div>
      <div className="theme-list">
        {dashboard.themes.map((theme) => <span key={theme.code}>{theme.name}</span>)}
      </div>
    </section>
  );
}

function InvestorPanel({ dashboard }: { dashboard: Dashboard }) {
  if (dashboard.investors.length === 0) {
    return <EmptyPanel title="외국인/기관 누적 수급" message={panelMessage(dashboard.data_quality, "investor_status")} />;
  }
  return (
    <section className="panel">
      <div className="panel-title">외국인/기관 누적 수급</div>
      <table>
        <thead>
          <tr>
            <th>기간</th>
            <th>외국인</th>
            <th>비율</th>
            <th>기관</th>
            <th>비율</th>
          </tr>
        </thead>
        <tbody>
          {periods.map((period) => {
            const row = dashboard.investor_summary.periods[period];
            return (
              <tr key={period}>
                <td>{period}일</td>
                <td className={row.foreign_qty >= 0 ? "up" : "down"}>{fmt(row.foreign_qty)}</td>
                <td>{row.foreign_ratio}%</td>
                <td className={row.institution_qty >= 0 ? "up" : "down"}>{fmt(row.institution_qty)}</td>
                <td>{row.institution_ratio}%</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="mini-note">
        최근 5일 이탈률: 외국인 {dashboard.investor_summary.recent_outflow_5d.foreign_ratio}% · 기관 {dashboard.investor_summary.recent_outflow_5d.institution_ratio}%
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
          <span key={period}>{period}일 {fmt(dashboard.program_summary[period].net_amount_m)}백만</span>
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
  if (status === "api_not_configured") return "키움 REST API 키가 없어 실데이터를 요청하지 않았습니다.";
  if (status === "auth_failed") return "키움 REST 인증에 실패했습니다. .env의 앱키/시크릿키를 확인하세요.";
  if (status === "token_expired") return "키움 접근토큰이 만료되었습니다. 다시 갱신해 주세요.";
  if (status === "network_error") return "키움 REST 서버에 연결하지 못했습니다.";
  if (status === "rate_limited") return "키움 REST 요청 제한에 걸렸습니다.";
  if (status === "unavailable") return "키움 REST 응답에서 이 항목을 가져오지 못했습니다.";
  return quality.messages?.[0] ?? "실데이터가 수신되지 않았습니다.";
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

createRoot(document.getElementById("root")!).render(<App />);
