import type { ChartTimeframe, Dashboard, SearchResponse } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8001";

export async function searchStocks(query: string): Promise<SearchResponse> {
  const response = await fetch(`${API_BASE}/api/search?q=${encodeURIComponent(query)}`);
  if (!response.ok) throw new Error("검색에 실패했습니다.");
  return response.json();
}

export async function refreshStock(code: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/stocks/${code}/refresh`, { method: "POST" });
  if (!response.ok) throw new Error("데이터 갱신에 실패했습니다.");
}

export async function getDashboard(code: string, timeframe: ChartTimeframe = "daily", lookback = 300): Promise<Dashboard> {
  const params = new URLSearchParams({ timeframe, lookback: String(lookback) });
  const response = await fetch(`${API_BASE}/api/stocks/${code}/dashboard?${params.toString()}`);
  if (!response.ok) throw new Error("대시보드 데이터를 불러오지 못했습니다.");
  return response.json();
}
