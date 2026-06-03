from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import public_kiwoom_settings, save_kiwoom_settings
from .database import get_cached_dashboard, init_db, save_dashboard, search_cached_stocks, upsert_stocks
from .services.dashboard import enrich_dashboard
from .services.data_provider import DataProvider


app = FastAPI(title="YangRadar API", version="0.3.0")
provider = DataProvider()


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


@app.get("/api/settings/kiwoom")
def get_kiwoom_settings() -> dict[str, Any]:
    return public_kiwoom_settings()


@app.post("/api/settings/kiwoom")
def update_kiwoom_settings(payload: KiwoomSettingsPayload) -> dict[str, Any]:
    global provider
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
    return {"ok": True, "settings": public_kiwoom_settings(), "provider": provider.status()}


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
    raw = provider.build_dashboard(normalized, 180)
    payload = enrich_dashboard(raw, 180)
    save_dashboard(normalized, payload, datetime.now().isoformat(timespec="seconds"))
    return {"ok": True, "code": normalized, "data_quality": payload["data_quality"]}


@app.get("/api/stocks/{code}/dashboard")
def dashboard(code: str, lookback: int = 180, cache: bool = False) -> dict[str, Any]:
    normalized = _normalize_code(code)
    lookback = max(30, min(lookback, 260))
    if cache:
        cached = get_cached_dashboard(normalized)
        if cached:
            cached["ohlcv"] = cached["ohlcv"][-lookback:]
            return cached
    raw = provider.build_dashboard(normalized, lookback)
    payload = enrich_dashboard(raw, lookback)
    save_dashboard(normalized, payload, datetime.now().isoformat(timespec="seconds"))
    return payload


def _normalize_code(code: str) -> str:
    normalized = code.strip()
    if not normalized.isdigit() or len(normalized) != 6:
        raise HTTPException(status_code=400, detail="종목코드는 6자리 숫자여야 합니다.")
    return normalized

