from __future__ import annotations

from datetime import datetime
import re
import time
from threading import Thread
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import public_kiwoom_settings, save_kiwoom_settings
from .database import (
    get_cached_dashboard,
    get_cached_stock,
    get_investor_dates,
    get_investor_ranking,
    get_latest_investor_date,
    get_ranking_job,
    init_db,
    save_dashboard,
    search_cached_stocks,
    upsert_stocks,
)
from .services.dashboard import enrich_dashboard
from .services.data_provider import DataProvider
from .services.ranking_service import InvestorRankingService


app = FastAPI(title="YangRadar API", version="0.4.0")
provider = DataProvider()
ranking_service = InvestorRankingService(provider)
_auto_scheduler_started = False


class KiwoomSettingsPayload(BaseModel):
    app_key: str = Field(default="")
    secret_key: str = Field(default="")
    account_no: str = ""
    env: str = "real"
    base_url: str = ""


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    global _auto_scheduler_started
    init_db()
    stocks, _quality = provider.list_stocks()
    upsert_stocks(stocks, datetime.now().isoformat(timespec="seconds"))
    if _should_auto_collect_rankings():
        ranking_service.start(datetime.now().date().isoformat())
    if not _auto_scheduler_started:
        _auto_scheduler_started = True
        Thread(target=_auto_collect_loop, daemon=True, name="yangradar-ranking-scheduler").start()


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "provider": provider.status()}


@app.get("/api/settings/kiwoom")
def get_kiwoom_settings() -> dict[str, Any]:
    return public_kiwoom_settings()


@app.post("/api/settings/kiwoom")
def update_kiwoom_settings(payload: KiwoomSettingsPayload) -> dict[str, Any]:
    global provider, ranking_service
    env = payload.env.strip().lower() or "real"
    if env not in {"real", "mock"}:
        raise HTTPException(status_code=400, detail="KIWOOM_ENV는 real 또는 mock이어야 합니다.")
    if not payload.app_key.strip() or not payload.secret_key.strip():
        raise HTTPException(status_code=400, detail="앱키와 시크릿키를 모두 입력해야 합니다.")
    save_kiwoom_settings(
        app_key=payload.app_key,
        secret_key=payload.secret_key,
        account_no=payload.account_no,
        env=env,
        base_url=payload.base_url,
    )
    provider = DataProvider()
    ranking_service = InvestorRankingService(provider)
    return {"ok": True, "settings": public_kiwoom_settings(), "provider": provider.status()}


@app.post("/api/settings/kiwoom/test-auth")
def test_kiwoom_auth() -> dict[str, Any]:
    return provider.test_auth()


@app.get("/api/search")
def search(q: str = "") -> dict[str, Any]:
    query = q.strip()
    if not query:
        return {"items": [], "data_quality": {"status": "empty_query", "message": "검색어를 입력하세요."}}
    stocks, quality = provider.list_stocks()
    upsert_stocks(stocks, datetime.now().isoformat(timespec="seconds"))
    return {"items": search_cached_stocks(query), "data_quality": quality}


@app.post("/api/stocks/{code}/refresh")
def refresh_stock(code: str) -> dict[str, Any]:
    normalized = _normalize_code(code)
    raw = provider.build_dashboard(normalized, 300, "daily")
    _merge_cached_stock(raw, normalized)
    payload = enrich_dashboard(raw, 300)
    save_dashboard(normalized, payload, datetime.now().isoformat(timespec="seconds"))
    return {"ok": True, "code": normalized, "data_quality": payload["data_quality"]}


@app.get("/api/rankings/investor")
def investor_ranking(
    date: str | None = None,
    metric: str = "foreign",
    direction: str = "inflow",
    market: str = "ALL",
    asset_type: str = "ALL",
    limit: int = 100,
) -> dict[str, Any]:
    normalized_date = _normalize_optional_date(date) or get_latest_investor_date()
    metric = metric.strip().lower()
    direction = direction.strip().lower()
    market = market.strip().upper()
    asset_type = asset_type.strip().upper()
    if metric not in {"foreign", "institution", "combined"}:
        raise HTTPException(status_code=400, detail="metric은 foreign, institution, combined 중 하나여야 합니다.")
    if direction not in {"inflow", "outflow"}:
        raise HTTPException(status_code=400, detail="direction은 inflow 또는 outflow여야 합니다.")
    if market not in {"ALL", "KOSPI", "KOSDAQ"}:
        raise HTTPException(status_code=400, detail="market은 ALL, KOSPI, KOSDAQ 중 하나여야 합니다.")
    if asset_type not in {"ALL", "STOCK", "ETF"}:
        raise HTTPException(status_code=400, detail="asset_type은 ALL, STOCK, ETF 중 하나여야 합니다.")
    if not normalized_date:
        return {
            "date": None,
            "items": [],
            "dates": get_investor_dates(),
            "data_quality": {"status": "no_data", "message": "아직 일별 전체 수급 데이터가 없습니다."},
        }
    items = get_investor_ranking(normalized_date, metric, direction, market, asset_type, max(1, min(limit, 100)))
    return {
        "date": normalized_date,
        "metric": metric,
        "direction": direction,
        "market": market,
        "asset_type": asset_type,
        "items": items,
        "dates": get_investor_dates(),
        "data_quality": {
            "status": "ok" if items else "no_data",
            "message": "일별 수급 순위를 불러왔습니다." if items else "선택한 조건의 데이터가 없습니다.",
        },
    }


@app.get("/api/rankings/investor/status")
def investor_ranking_status() -> dict[str, Any]:
    return {"job": get_ranking_job(), "dates": get_investor_dates(), "provider": provider.status()}


@app.post("/api/rankings/investor/refresh")
def refresh_investor_ranking(target_date: str | None = None) -> dict[str, Any]:
    normalized_date = _normalize_optional_date(target_date)
    result = ranking_service.start(normalized_date)
    if not result.get("started"):
        raise HTTPException(status_code=409, detail=result.get("message"))
    return {"ok": True, **result}


@app.get("/api/stocks/{code}/dashboard")
def dashboard(code: str, lookback: int = 300, timeframe: str = "daily", cache: bool = False) -> dict[str, Any]:
    normalized = _normalize_code(code)
    timeframe = _normalize_timeframe(timeframe)
    lookback = max(30, min(lookback, _max_lookback(timeframe)))
    if cache and timeframe == "daily":
        cached = get_cached_dashboard(normalized)
        if cached:
            cached["ohlcv"] = cached["ohlcv"][-lookback:]
            return cached
    raw = provider.build_dashboard(normalized, lookback, timeframe)
    _merge_cached_stock(raw, normalized)
    payload = enrich_dashboard(raw, lookback)
    if timeframe == "daily":
        save_dashboard(normalized, payload, datetime.now().isoformat(timespec="seconds"))
    return payload


def _merge_cached_stock(raw: dict[str, Any], code: str) -> None:
    cached = get_cached_stock(code)
    if not cached:
        return
    stock = raw.setdefault("stock", {})
    for key in ["name", "market", "sector"]:
        value = stock.get(key)
        if value in (None, "", "UNKNOWN", "정보 없음"):
            stock[key] = cached.get(key)
    if not stock.get("listed_shares"):
        stock["listed_shares"] = cached.get("listed_shares")


def _normalize_code(code: str) -> str:
    normalized = code.strip()
    if not normalized.isdigit() or len(normalized) != 6:
        raise HTTPException(status_code=400, detail="종목코드는 6자리 숫자여야 합니다.")
    return normalized


def _normalize_timeframe(timeframe: str) -> str:
    normalized = timeframe.strip().lower()
    if normalized not in {"daily", "weekly", "monthly"}:
        raise HTTPException(status_code=400, detail="timeframe은 daily, weekly, monthly 중 하나여야 합니다.")
    return normalized


def _normalize_optional_date(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    normalized = value.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized):
        raise HTTPException(status_code=400, detail="date는 YYYY-MM-DD 형식이어야 합니다.")
    try:
        datetime.strptime(normalized, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date는 유효한 날짜여야 합니다.") from exc
    return normalized


def _should_auto_collect_rankings() -> bool:
    now = datetime.now()
    if not provider.status().get("configured") or now.weekday() >= 5 or now.hour < 18:
        return False
    return get_latest_investor_date() != now.date().isoformat()


def _auto_collect_loop() -> None:
    while True:
        try:
            if _should_auto_collect_rankings():
                ranking_service.start(datetime.now().date().isoformat())
        except Exception:
            # The manual refresh endpoint remains available if the scheduler cannot run.
            pass
        time.sleep(60)


def _max_lookback(timeframe: str) -> int:
    if timeframe == "daily":
        return 600
    if timeframe == "weekly":
        return 300
    return 240
