from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .database import get_cached_dashboard, get_cached_stock, init_db, save_dashboard, search_cached_stocks, upsert_stocks
from .services.dashboard import enrich_dashboard
from .services.data_provider import DataProvider


app = FastAPI(title="YangRadar API", version="0.2.0")
provider = DataProvider()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()
    stocks, _quality = provider.list_stocks()
    upsert_stocks(stocks, datetime.now().isoformat(timespec="seconds"))


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "provider": provider.status()}


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


def _max_lookback(timeframe: str) -> int:
    if timeframe == "daily":
        return 600
    if timeframe == "weekly":
        return 300
    return 240
