import type { Dashboard, KiwoomAuthTest, KiwoomSettings, KiwoomSettingsPayload, SearchResponse } from "./types";

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

export async function getDashboard(code: string): Promise<Dashboard> {
  const response = await fetch(`${API_BASE}/api/stocks/${code}/dashboard?lookback=180`);
  if (!response.ok) throw new Error("대시보드 데이터를 불러오지 못했습니다.");
  return response.json();
}

export async function getKiwoomSettings(): Promise<KiwoomSettings> {
  const response = await fetch(`${API_BASE}/api/settings/kiwoom`);
  if (!response.ok) throw new Error("키움 설정을 불러오지 못했습니다.");
  return response.json();
}

export async function saveKiwoomSettings(payload: KiwoomSettingsPayload): Promise<KiwoomSettings> {
  const response = await fetch(`${API_BASE}/api/settings/kiwoom`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail ?? "키움 설정 저장에 실패했습니다.");
  return body.settings;
}

export async function testKiwoomAuth(): Promise<KiwoomAuthTest> {
  const response = await fetch(`${API_BASE}/api/settings/kiwoom/test-auth`, { method: "POST" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail ?? "키움 REST 인증 테스트에 실패했습니다.");
  return body;
}
