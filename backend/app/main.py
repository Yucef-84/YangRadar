from __future__ import annotations

from datetime import datetime, time as datetime_time, timedelta
import ipaddress
import re
import time as time_module
from threading import Lock, Thread
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import get_settings, normalize_kiwoom_base_url, public_kiwoom_settings, save_kiwoom_settings
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
_LOCAL_API_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
)
_auto_scheduler_started = False
_KST = ZoneInfo("Asia/Seoul")
_AUTO_COLLECTION_TIME = datetime_time(15, 40)
_AUTO_READINESS_INTERVAL = timedelta(minutes=10)
_AUTO_SCHEDULER_TICK_SECONDS = 60
_auto_scheduler_state_lock = Lock()
_auto_scheduler_state: dict[str, Any] = {
    "state": "idle",
    "target_date": None,
    "last_checked_at": None,
    "next_check_at": None,
    "ready_count": None,
    "sample_count": None,
    "message": None,
}


class KiwoomSettingsPayload(BaseModel):
    app_key: str = Field(default="")
    secret_key: str = Field(default="")
    account_no: str = ""
    env: str = "real"
    base_url: str = ""


def _require_local_settings_request(request: Request) -> None:
    """Keep credential-management endpoints available only to the local app."""
    host = (request.client.host if request.client else "") or ""
    headers = getattr(request, "headers", {})
    if headers.get("x-forwarded-for") or headers.get("forwarded"):
        raise HTTPException(status_code=403, detail="프록시를 통한 키움 설정 요청은 허용하지 않습니다.")
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = host.lower() == "localhost"
    if not is_loopback:
        raise HTTPException(status_code=403, detail="키움 설정은 YangRadar를 실행한 PC에서만 변경할 수 있습니다.")


app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_LOCAL_API_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_local_api_browser_request(request: Request) -> None:
    """Reject browser-originated cross-site calls to the local API.

    CORS controls whether a browser may read a response, but it does not stop
    the request from reaching a loopback server.  Keep native clients (which
    normally omit both headers) working while requiring browser origins to be
    one of the local YangRadar frontend origins.
    """
    headers = getattr(request, "headers", {})
    origin = (headers.get("origin") or "").strip()
    if origin:
        if origin not in _LOCAL_API_ORIGINS:
            raise HTTPException(status_code=403, detail="허용되지 않은 브라우저 Origin입니다.")
        return

    fetch_site = (headers.get("sec-fetch-site") or "").strip().lower()
    if fetch_site == "cross-site":
        raise HTTPException(status_code=403, detail="외부 사이트에서의 API 요청은 허용되지 않습니다.")


@app.middleware("http")
async def local_api_browser_origin_guard(request: Request, call_next):
    path = request.url.path
    if path == "/api" or path.startswith("/api/"):
        try:
            _require_local_api_browser_request(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


@app.on_event("startup")
def startup() -> None:
    global _auto_scheduler_started
    init_db()
    stocks, quality = provider.list_stocks()
    upsert_stocks(stocks, datetime.now().isoformat(timespec="seconds"), complete=quality.get("complete") is True)
    _auto_scheduler_tick()
    if not _auto_scheduler_started:
        _auto_scheduler_started = True
        Thread(target=_auto_collect_loop, daemon=True, name="yangradar-ranking-scheduler").start()


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "provider": provider.status()}


@app.get("/api/settings/kiwoom")
def get_kiwoom_settings(request: Request) -> dict[str, Any]:
    _require_local_settings_request(request)
    return public_kiwoom_settings()


@app.post("/api/settings/kiwoom")
def update_kiwoom_settings(payload: KiwoomSettingsPayload, request: Request) -> dict[str, Any]:
    global provider, ranking_service
    _require_local_settings_request(request)
    env = payload.env.strip().lower() or "real"
    if env not in {"real", "mock"}:
        raise HTTPException(status_code=400, detail="KIWOOM_ENV는 real 또는 mock이어야 합니다.")
    if not payload.app_key.strip() or not payload.secret_key.strip():
        raise HTTPException(status_code=400, detail="앱키와 시크릿키를 모두 입력해야 합니다.")
    try:
        base_url = normalize_kiwoom_base_url(env, payload.base_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    current = get_settings()
    save_kiwoom_settings(
        app_key=payload.app_key,
        secret_key=payload.secret_key,
        account_no=payload.account_no.strip() or current.kiwoom_account_no,
        env=env,
        base_url=base_url,
    )
    provider = DataProvider()
    ranking_service = InvestorRankingService(provider)
    return {"ok": True, "settings": public_kiwoom_settings(), "provider": provider.status()}


@app.post("/api/settings/kiwoom/test-auth")
def test_kiwoom_auth(request: Request) -> dict[str, Any]:
    _require_local_settings_request(request)
    return provider.test_auth()


@app.get("/api/search")
def search(q: str = "") -> dict[str, Any]:
    query = q.strip()
    if not query:
        return {"items": [], "data_quality": {"status": "empty_query", "message": "검색어를 입력하세요."}}
    stocks, quality = provider.list_stocks()
    upsert_stocks(stocks, datetime.now().isoformat(timespec="seconds"), complete=quality.get("complete") is True)
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
    return {
        "job": get_ranking_job(),
        "dates": get_investor_dates(),
        "provider": provider.status(),
        "auto_scheduler": _auto_scheduler_snapshot(),
    }


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


def _now_kst() -> datetime:
    return datetime.now(_KST)


def _as_kst(value: datetime) -> datetime:
    """Treat naive test values as KST and normalize aware values to KST."""
    if value.tzinfo is None:
        return value.replace(tzinfo=_KST)
    return value.astimezone(_KST)


def _iso_kst(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _as_kst(value).isoformat(timespec="seconds")


def _today_kst(value: datetime) -> str:
    return _as_kst(value).date().isoformat()


def _collection_start_at(value: datetime) -> datetime:
    current = _as_kst(value)
    return datetime.combine(current.date(), _AUTO_COLLECTION_TIME, tzinfo=_KST)


def _next_weekday_collection_start(value: datetime) -> datetime:
    current = _as_kst(value)
    candidate = current.date() + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return datetime.combine(candidate, _AUTO_COLLECTION_TIME, tzinfo=_KST)


def _auto_scheduler_snapshot() -> dict[str, Any]:
    with _auto_scheduler_state_lock:
        return dict(_auto_scheduler_state)


def _set_auto_scheduler_state(**values: Any) -> dict[str, Any]:
    with _auto_scheduler_state_lock:
        _auto_scheduler_state.update(values)
        return dict(_auto_scheduler_state)


def _reset_auto_scheduler_state() -> None:
    """Reset process-local scheduler state for deterministic tests."""
    _set_auto_scheduler_state(
        state="idle",
        target_date=None,
        last_checked_at=None,
        next_check_at=None,
        ready_count=None,
        sample_count=None,
        message=None,
    )


def _next_check_datetime(snapshot: dict[str, Any]) -> datetime | None:
    value = snapshot.get("next_check_at")
    if not value:
        return None
    if isinstance(value, datetime):
        return _as_kst(value)
    try:
        return _as_kst(datetime.fromisoformat(str(value)))
    except (TypeError, ValueError):
        return None


def _ranking_job_snapshot() -> dict[str, Any]:
    try:
        snapshot = get_ranking_job()
        return snapshot if isinstance(snapshot, dict) else {}
    except Exception:
        return {}


def _ranking_job_is_running(target_date: str, snapshot: dict[str, Any] | None = None) -> bool:
    job = snapshot if snapshot is not None else _ranking_job_snapshot()
    return str(job.get("status") or "").lower() == "running"


def _ranking_job_has_incomplete_rows(target_date: str, snapshot: dict[str, Any]) -> bool:
    """Identify a current-date job that can still be resumed.

    InvestorRankingService may persist some rows before a process/network
    failure.  A latest-date row therefore does not by itself mean that the
    whole universe is complete.
    """
    if str(snapshot.get("target_date") or "") != target_date:
        return False
    status = str(snapshot.get("status") or "").lower()
    if status in {"failed", "error"}:
        return True
    if status != "completed":
        return False
    try:
        failed = int(snapshot.get("failed") or 0)
    except (TypeError, ValueError):
        failed = 0
    try:
        total = int(snapshot.get("total") or 0)
    except (TypeError, ValueError):
        total = 0
    try:
        saved = int(snapshot.get("saved") or 0)
    except (TypeError, ValueError):
        saved = 0
    return failed > 0 or (total > 0 and saved < total)


def _should_auto_collect_rankings(now: datetime | None = None) -> bool:
    """Return whether today's full collection is eligible to be considered.

    The readiness probe and its ten-minute schedule are handled by
    ``_auto_scheduler_tick``; this compatibility helper only performs the
    inexpensive KST/date/job gates.
    """
    current = _as_kst(now or _now_kst())
    target_date = _today_kst(current)
    if current.weekday() >= 5 or current < _collection_start_at(current):
        return False
    if not provider.status().get("configured"):
        return False
    if get_latest_investor_date() == target_date:
        return False
    if _ranking_job_is_running(target_date):
        return False
    return True


def _auto_scheduler_tick(now: datetime | None = None) -> dict[str, Any]:
    """Advance the in-process KST readiness/collection scheduler once."""
    current = _as_kst(now or _now_kst())
    target_date = _today_kst(current)
    snapshot = _auto_scheduler_snapshot()

    # A new KST date starts with a clean readiness window.  No historical
    # backfill is attempted: only the current KST trading date is considered.
    if snapshot.get("target_date") != target_date:
        _set_auto_scheduler_state(
            state="idle",
            target_date=target_date,
            last_checked_at=None,
            next_check_at=None,
            ready_count=None,
            sample_count=None,
            message=None,
        )

    if current.weekday() >= 5:
        return _set_auto_scheduler_state(
            state="weekend",
            target_date=target_date,
            next_check_at=_iso_kst(_next_weekday_collection_start(current)),
            message="주말에는 수급 준비상태를 확인하지 않습니다.",
        )

    collection_start = _collection_start_at(current)
    if current < collection_start:
        return _set_auto_scheduler_state(
            state="waiting_time",
            target_date=target_date,
            next_check_at=_iso_kst(collection_start),
            message="15:40 KST 이후 장 마감 수급 준비상태를 확인합니다.",
        )

    try:
        configured = bool(provider.status().get("configured"))
    except Exception:
        configured = False
    if not configured:
        return _set_auto_scheduler_state(
            state="disabled",
            target_date=target_date,
            next_check_at=_iso_kst(current + _AUTO_READINESS_INTERVAL),
            message="키움 REST API가 설정되지 않아 자동 수집을 대기 중입니다.",
        )

    job_snapshot = _ranking_job_snapshot()
    if _ranking_job_is_running(target_date, job_snapshot):
        snapshot = _auto_scheduler_snapshot()
        scheduled_retry = _next_check_datetime(snapshot)
        retry_at = scheduled_retry if scheduled_retry is not None and current < scheduled_retry else current + _AUTO_READINESS_INTERVAL
        return _set_auto_scheduler_state(
            state="running",
            target_date=target_date,
            next_check_at=_iso_kst(retry_at),
            message="전체 수급 수집이 진행 중입니다.",
        )

    try:
        latest_date = get_latest_investor_date()
    except Exception as exc:
        return _set_auto_scheduler_state(
            state="error",
            target_date=target_date,
            last_checked_at=_iso_kst(current),
            next_check_at=_iso_kst(current + _AUTO_READINESS_INTERVAL),
            message=f"최근 수급 기준일 확인 실패: {type(exc).__name__}",
        )
    if latest_date == target_date and not _ranking_job_has_incomplete_rows(target_date, job_snapshot):
        return _set_auto_scheduler_state(
            state="completed",
            target_date=target_date,
            next_check_at=_iso_kst(_next_weekday_collection_start(current)),
            message="오늘 수급 데이터가 이미 저장되어 있습니다.",
        )

    # Do not probe again until the scheduled readiness time.  Database/status
    # checks above are intentionally cheap and do not call Kiwoom.
    snapshot = _auto_scheduler_snapshot()
    next_check = _next_check_datetime(snapshot)
    if next_check is not None and current < next_check:
        return snapshot

    try:
        readiness = provider.check_investor_readiness(target_date)
    except Exception as exc:
        return _set_auto_scheduler_state(
            state="error",
            target_date=target_date,
            last_checked_at=_iso_kst(current),
            next_check_at=_iso_kst(current + _AUTO_READINESS_INTERVAL),
            ready_count=0,
            sample_count=None,
            message=f"수급 준비상태 확인 실패: {type(exc).__name__}",
        )

    ready_count = readiness.get("ready_count")
    sample_count = readiness.get("sample_count")
    readiness_status = str(readiness.get("status") or "").lower()
    if readiness_status == "error":
        return _set_auto_scheduler_state(
            state="error",
            target_date=target_date,
            last_checked_at=_iso_kst(current),
            next_check_at=_iso_kst(current + _AUTO_READINESS_INTERVAL),
            ready_count=ready_count,
            sample_count=sample_count,
            message="수급 준비상태 표본 API 확인에 실패했습니다.",
        )
    is_ready = readiness.get("ready") is True or (
        isinstance(ready_count, int) and ready_count >= 2
    )
    if not is_ready:
        actual_target = readiness.get("target_date") or target_date
        return _set_auto_scheduler_state(
            state="waiting_data",
            target_date=target_date,
            last_checked_at=_iso_kst(current),
            next_check_at=_iso_kst(current + _AUTO_READINESS_INTERVAL),
            ready_count=ready_count,
            sample_count=sample_count,
            message=f"{actual_target} 수급 데이터가 아직 준비되지 않았습니다.",
        )

    try:
        result = ranking_service.start(target_date)
    except Exception as exc:
        return _set_auto_scheduler_state(
            state="error",
            target_date=target_date,
            last_checked_at=_iso_kst(current),
            next_check_at=_iso_kst(current + _AUTO_READINESS_INTERVAL),
            ready_count=ready_count,
            sample_count=sample_count,
            message=f"전체 수급 수집 시작 실패: {type(exc).__name__}",
        )
    # Give the worker time to publish its persisted `running` row.  Keeping a
    # short retry window also prevents a startup tick race from calling
    # readiness/start twice, while a failed job can be retried later.
    retry_at = _iso_kst(current + _AUTO_READINESS_INTERVAL)
    if result.get("started") is True:
        return _set_auto_scheduler_state(
            state="running",
            target_date=target_date,
            last_checked_at=_iso_kst(current),
            next_check_at=retry_at,
            ready_count=ready_count,
            sample_count=sample_count,
            message=result.get("message") or "전체 수급 수집을 시작했습니다.",
        )
    return _set_auto_scheduler_state(
        state="running",
        target_date=target_date,
        last_checked_at=_iso_kst(current),
        next_check_at=retry_at,
        ready_count=ready_count,
        sample_count=sample_count,
        message=result.get("message") or "전체 수급 수집이 이미 진행 중입니다.",
    )


def _auto_collect_loop() -> None:
    while True:
        try:
            _auto_scheduler_tick()
        except Exception as exc:
            # Keep the manual refresh endpoint available if the scheduler
            # encounters an unexpected process-local failure.
            current = _now_kst()
            _set_auto_scheduler_state(
                state="error",
                target_date=_today_kst(current),
                last_checked_at=_iso_kst(current),
                next_check_at=_iso_kst(current + _AUTO_READINESS_INTERVAL),
                message=f"자동 수집 스케줄러 오류: {type(exc).__name__}",
            )
        time_module.sleep(_AUTO_SCHEDULER_TICK_SECONDS)


def _max_lookback(timeframe: str) -> int:
    if timeframe == "daily":
        return 600
    if timeframe == "weekly":
        return 300
    return 240
