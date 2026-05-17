from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import requests

from ..config import Settings, get_settings
from .stock_universe import LOCAL_STOCKS, local_stock


class KiwoomApiError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class KiwoomRestProvider:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    @property
    def configured(self) -> bool:
        return self.settings.kiwoom_configured

    def status(self) -> dict[str, Any]:
        return {
            "provider": "kiwoom_rest",
            "configured": self.configured,
            "environment": self.settings.kiwoom_env,
            "base_url": self.settings.kiwoom_base_url,
            "account_configured": bool(self.settings.kiwoom_account_no),
        }

    def list_stocks(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not self.configured:
            return LOCAL_STOCKS, self._quality("stock_list", "api_not_configured", "키움 REST API 키가 설정되지 않아 로컬 종목 목록만 사용합니다.")
        try:
            data = self._post("/api/dostk/stkinfo", "ka10099", {"mrkt_tp": "0"})
            stocks = self._parse_stock_list(data)
            if stocks:
                return stocks, self._quality("stock_list", "ok", "키움 REST 종목 목록을 수신했습니다.")
            return LOCAL_STOCKS, self._quality("stock_list", "unavailable", "키움 종목 목록 응답을 해석하지 못해 로컬 목록을 사용합니다.")
        except KiwoomApiError as exc:
            return LOCAL_STOCKS, self._quality("stock_list", exc.code, exc.message)

    def dashboard(self, code: str, lookback: int) -> dict[str, Any]:
        stock = local_stock(code)
        data_quality = self._base_quality()

        if not self.configured:
            data_quality.update(
                {
                    "connection_status": "api_not_configured",
                    "price_status": "api_not_configured",
                    "chart_status": "api_not_configured",
                    "investor_status": "api_not_configured",
                    "program_status": "api_not_configured",
                    "theme_status": "api_not_configured",
                    "message": "키움 REST API 키가 설정되지 않았습니다. .env 파일을 확인하세요.",
                }
            )
            return self._empty_dashboard(stock, data_quality)

        quote: dict[str, Any] = {}
        ohlcv: list[dict[str, Any]] = []
        investors: list[dict[str, Any]] = []
        program: list[dict[str, Any]] = []
        themes: list[dict[str, Any]] = []

        try:
            quote = self._get_quote(code)
            if quote:
                stock = {**stock, **{k: v for k, v in quote.items() if k in {"name", "market", "sector", "listed_shares"} and v}}
                data_quality["price_status"] = "ok"
        except KiwoomApiError as exc:
            data_quality["price_status"] = exc.code
            data_quality["messages"].append(exc.message)

        try:
            ohlcv = self._get_daily_chart(code, lookback)
            data_quality["chart_status"] = "ok" if ohlcv else "unavailable"
        except KiwoomApiError as exc:
            data_quality["chart_status"] = exc.code
            data_quality["messages"].append(exc.message)

        try:
            investors = self._get_investor_chart(code)
            data_quality["investor_status"] = "ok" if investors else "unavailable"
        except KiwoomApiError as exc:
            data_quality["investor_status"] = exc.code
            data_quality["messages"].append(exc.message)

        try:
            program = self._get_program_trading(code)
            data_quality["program_status"] = "ok" if program else "unavailable"
        except KiwoomApiError as exc:
            data_quality["program_status"] = exc.code
            data_quality["messages"].append(exc.message)

        try:
            themes = self._get_themes_for_stock(code)
            data_quality["theme_status"] = "ok" if themes else "unavailable"
        except KiwoomApiError as exc:
            data_quality["theme_status"] = exc.code
            data_quality["messages"].append(exc.message)

        data_quality["connection_status"] = "ok" if any([quote, ohlcv, investors, program, themes]) else "unavailable"
        return {
            "stock": stock,
            "quote": quote,
            "ohlcv": ohlcv,
            "investors": investors,
            "program_trading": program,
            "themes": themes,
            "data_quality": data_quality,
        }

    def _get_quote(self, code: str) -> dict[str, Any]:
        data = self._post("/api/dostk/stkinfo", "ka10001", {"stk_cd": code})
        return {
            "name": _first(data, ["stk_nm", "isu_nm", "name"]),
            "close": _to_number(_first(data, ["cur_prc", "close_pric", "now_pric", "prpr"])),
            "change": _to_number(_first(data, ["pred_pre", "change", "prdy_vrss"])),
            "change_rate": _to_number(_first(data, ["flu_rt", "chg_rt", "prdy_ctrt"])),
            "volume": _to_number(_first(data, ["trde_qty", "acc_trdvol", "volume"])),
            "trading_value": _to_number(_first(data, ["trde_prica", "acc_trdval", "trading_value"])),
            "listed_shares": _to_number(_first(data, ["flo_stkcnt", "lst_stkcnt", "listed_shares"])),
        }

    def _get_daily_chart(self, code: str, lookback: int) -> list[dict[str, Any]]:
        data = self._post(
            "/api/dostk/chart",
            "ka10081",
            {"stk_cd": code, "base_dt": datetime.now().strftime("%Y%m%d"), "upd_stkpc_tp": "1"},
        )
        rows = _find_first_list(data, ["stk_dt_pole_chart_qry", "stk_daily_chart_qry", "output", "list"])
        parsed: list[dict[str, Any]] = []
        for row in rows:
            date = _format_date(_first(row, ["dt", "date", "stck_bsop_date"]))
            close = _to_number(_first(row, ["cur_prc", "close_pric", "stck_clpr", "close"]))
            volume = _to_number(_first(row, ["trde_qty", "acml_vol", "volume"])) or 0
            if not date or close is None:
                continue
            parsed.append(
                {
                    "date": date,
                    "open": _to_number(_first(row, ["open_pric", "stck_oprc", "open"])) or close,
                    "high": _to_number(_first(row, ["high_pric", "stck_hgpr", "high"])) or close,
                    "low": _to_number(_first(row, ["low_pric", "stck_lwpr", "low"])) or close,
                    "close": close,
                    "volume": volume,
                    "trading_value": _to_number(_first(row, ["trde_prica", "acml_tr_pbmn", "trading_value"])) or close * volume,
                }
            )
        parsed.sort(key=lambda item: item["date"])
        return parsed[-lookback:]

    def _get_investor_chart(self, code: str) -> list[dict[str, Any]]:
        data = self._post(
            "/api/dostk/chart",
            "ka10060",
            {"dt": datetime.now().strftime("%Y%m%d"), "stk_cd": code, "amt_qty_tp": "2", "trde_tp": "0", "unit_tp": "1"},
        )
        rows = _find_first_list(data, ["stk_invsr_orgn_chart", "output", "list"])
        parsed: list[dict[str, Any]] = []
        for row in rows:
            date = _format_date(_first(row, ["dt", "date"]))
            if not date:
                continue
            parsed.append(
                {
                    "date": date,
                    "foreign_qty": _to_number(_first(row, ["frgnr_netprps_qty", "for_netprps_qty", "foreign_qty"])) or 0,
                    "foreign_value": _to_number(_first(row, ["frgnr_netprps_amt", "foreign_value"])) or 0,
                    "institution_qty": _to_number(_first(row, ["orgn_netprps_qty", "inst_netprps_qty", "institution_qty"])) or 0,
                    "institution_value": _to_number(_first(row, ["orgn_netprps_amt", "institution_value"])) or 0,
                }
            )
        parsed.sort(key=lambda item: item["date"])
        return parsed

    def _get_program_trading(self, code: str) -> list[dict[str, Any]]:
        attempts = [
            ("/api/dostk/stkinfo", "ka90013", {"stk_cd": code}),
            ("/api/dostk/stkinfo", "ka90004", {"stk_cd": code}),
        ]
        last_error: KiwoomApiError | None = None
        for endpoint, api_id, body in attempts:
            try:
                data = self._post(endpoint, api_id, body)
                parsed = self._parse_program_rows(data)
                if parsed:
                    return parsed
            except KiwoomApiError as exc:
                last_error = exc
        if last_error:
            raise last_error
        return []

    def _parse_program_rows(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        rows = _find_first_list(data, ["stk_day_progrm_trde_trnsn", "stk_progrm_trde", "output", "list"])
        parsed: list[dict[str, Any]] = []
        for row in rows:
            date = _format_date(_first(row, ["dt", "date"]))
            if not date:
                continue
            buy = _to_number(_first(row, ["buy_amt", "buy_amount_m", "prm_buy_amt"])) or 0
            sell = _to_number(_first(row, ["sell_amt", "sell_amount_m", "prm_sell_amt"])) or 0
            net = _to_number(_first(row, ["netprps_amt", "net_amount_m", "prm_netprps_amt"])) or buy - sell
            parsed.append(
                {
                    "date": date,
                    "close": _to_number(_first(row, ["cur_prc", "close_pric", "close"])) or 0,
                    "change_rate": _to_number(_first(row, ["flu_rt", "change_rate"])),
                    "volume": _to_number(_first(row, ["trde_qty", "volume"])) or 0,
                    "sell_amount_m": sell,
                    "buy_amount_m": buy,
                    "net_amount_m": net,
                }
            )
        parsed.sort(key=lambda item: item["date"])
        return parsed

    def _get_themes_for_stock(self, code: str) -> list[dict[str, Any]]:
        data = self._post("/api/dostk/thme", "ka90001", {})
        rows = _find_first_list(data, ["theme_group", "thme_group", "output", "list"])
        themes: list[dict[str, Any]] = []
        for row in rows[:200]:
            theme_code = _first(row, ["theme_cd", "thme_cd", "code"])
            theme_name = _first(row, ["theme_nm", "thme_nm", "name"])
            if not theme_code or not theme_name:
                continue
            try:
                members = self._post("/api/dostk/thme", "ka90002", {"theme_cd": theme_code})
            except KiwoomApiError:
                continue
            member_rows = _find_first_list(members, ["theme_comp_stk", "thme_comp_stk", "output", "list"])
            if any(_digits(_first(member, ["stk_cd", "code"])) == code for member in member_rows):
                themes.append({"code": str(theme_code), "name": str(theme_name)})
            if len(themes) >= 8:
                break
        return themes

    def _token_value(self) -> str:
        if self._token and self._token_expires_at and self._token_expires_at > datetime.now() + timedelta(minutes=5):
            return self._token
        try:
            response = requests.post(
                f"{self.settings.kiwoom_base_url}/oauth2/token",
                json={
                    "grant_type": "client_credentials",
                    "appkey": self.settings.kiwoom_app_key,
                    "secretkey": self.settings.kiwoom_secret_key,
                },
                headers={"Content-Type": "application/json;charset=UTF-8", "api-id": "au10001"},
                timeout=10,
            )
        except requests.RequestException as exc:
            raise KiwoomApiError("network_error", f"키움 토큰 요청 실패: {exc}") from exc
        data = _response_json(response)
        if response.status_code >= 400 or str(data.get("return_code", "0")) not in {"0", ""}:
            raise KiwoomApiError("auth_failed", data.get("return_msg") or f"키움 인증 실패 HTTP {response.status_code}")
        token = data.get("token")
        if not token:
            raise KiwoomApiError("auth_failed", "키움 토큰 응답에 token 필드가 없습니다.")
        self._token = token
        self._token_expires_at = _parse_expiry(data.get("expires_dt")) or datetime.now() + timedelta(hours=20)
        return token

    def _post(self, endpoint: str, api_id: str, body: dict[str, Any]) -> dict[str, Any]:
        token = self._token_value()
        try:
            response = requests.post(
                f"{self.settings.kiwoom_base_url}{endpoint}",
                json=body,
                headers={
                    "Content-Type": "application/json;charset=UTF-8",
                    "authorization": f"Bearer {token}",
                    "api-id": api_id,
                    "cont-yn": "N",
                    "next-key": "",
                },
                timeout=10,
            )
        except requests.RequestException as exc:
            raise KiwoomApiError("network_error", f"{api_id} 요청 실패: {exc}") from exc
        data = _response_json(response)
        if response.status_code == 401:
            self._token = None
            self._token_expires_at = None
            raise KiwoomApiError("token_expired", "키움 접근토큰이 만료되었거나 거부되었습니다.")
        if response.status_code == 429:
            raise KiwoomApiError("rate_limited", "키움 요청 제한에 걸렸습니다.")
        if response.status_code >= 400 or str(data.get("return_code", "0")) not in {"0", ""}:
            raise KiwoomApiError("api_error", data.get("return_msg") or f"{api_id} HTTP {response.status_code}")
        return data

    def _parse_stock_list(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        rows = _find_first_list(data, ["list", "stk_info", "output", "items"])
        stocks: list[dict[str, Any]] = []
        for row in rows:
            code = _digits(_first(row, ["stk_cd", "code", "isu_cd"]))
            name = _first(row, ["stk_nm", "name", "isu_nm"])
            if not code or not name:
                continue
            stocks.append(
                {
                    "code": code.zfill(6),
                    "name": str(name),
                    "market": str(_first(row, ["mrkt_nm", "market"]) or "KRX"),
                    "sector": _first(row, ["upjong_nm", "sector"]),
                    "listed_shares": _to_number(_first(row, ["list_stock_cnt", "listed_shares"])),
                }
            )
        return stocks

    def _base_quality(self) -> dict[str, Any]:
        return {
            "source": "kiwoom_rest",
            "freshness": "intraday_or_delayed",
            "last_updated_at": datetime.now().isoformat(timespec="seconds"),
            "connection_status": "unknown",
            "price_status": "unknown",
            "chart_status": "unknown",
            "investor_status": "unknown",
            "program_status": "unknown",
            "theme_status": "unknown",
            "messages": [],
        }

    def _quality(self, scope: str, status: str, message: str) -> dict[str, Any]:
        return {"source": "kiwoom_rest", "scope": scope, "status": status, "message": message}

    def _empty_dashboard(self, stock: dict[str, Any], data_quality: dict[str, Any]) -> dict[str, Any]:
        return {"stock": stock, "quote": {}, "ohlcv": [], "investors": [], "program_trading": [], "themes": [], "data_quality": data_quality}


class DataProvider:
    def __init__(self):
        self.kiwoom = KiwoomRestProvider()

    def list_stocks(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return self.kiwoom.list_stocks()

    def build_dashboard(self, code: str, lookback: int) -> dict[str, Any]:
        return self.kiwoom.dashboard(code, lookback)

    def status(self) -> dict[str, Any]:
        return self.kiwoom.status()


def _response_json(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {"return_code": str(response.status_code), "return_msg": response.text[:200]}
    return data if isinstance(data, dict) else {"data": data}


def _find_first_list(data: dict[str, Any], keys: list[str]) -> list[dict[str, Any]]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    for value in data.values():
        if isinstance(value, list) and all(isinstance(row, dict) for row in value):
            return value
    return []


def _first(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _to_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    cleaned = str(value).replace(",", "").replace("+", "").strip()
    if cleaned.startswith("--"):
        cleaned = cleaned[1:]
    try:
        return float(cleaned)
    except ValueError:
        return None


def _digits(value: Any) -> str | None:
    if value in (None, ""):
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits or None


def _format_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    digits = _digits(value)
    if not digits or len(digits) < 8:
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def _parse_expiry(value: Any) -> datetime | None:
    digits = _digits(value)
    if not digits:
        return None
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(digits[: len(datetime.now().strftime(fmt))], fmt)
        except ValueError:
            continue
    return None
