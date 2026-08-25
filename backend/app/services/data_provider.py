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

    def test_auth(self) -> dict[str, Any]:
        if not self.configured:
            return {
                "ok": False,
                "status": "api_not_configured",
                "message": "Kiwoom REST API credentials are not saved.",
                "provider": self.status(),
            }
        self._token = None
        self._token_expires_at = None
        try:
            data = self._request_token()
        except KiwoomApiError as exc:
            return {"ok": False, "status": exc.code, "message": exc.message, "provider": self.status()}
        return {
            "ok": True,
            "status": "ok",
            "message": data.get("return_msg") or "Kiwoom REST authentication succeeded.",
            "token_type": data.get("token_type"),
            "expires_dt": data.get("expires_dt"),
            "provider": self.status(),
        }

    def list_stocks(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not self.configured:
            return [dict(stock, security_type="STOCK") for stock in LOCAL_STOCKS], self._quality("stock_list", "api_not_configured", "키움 REST API 키가 설정되지 않아 로컬 종목 목록만 사용합니다.")
        # ka10099 uses 0=KOSPI, 10=KOSDAQ, and 8=ETF.
        market_requests = [("0", "KOSPI"), ("10", "KOSDAQ"), ("8", "ETF")]
        stocks: list[dict[str, Any]] = []
        messages: list[str] = []
        try:
            for market_code, fallback_market in market_requests:
                try:
                    data = self._post("/api/dostk/stkinfo", "ka10099", {"mrkt_tp": market_code})
                    stocks.extend(self._parse_stock_list(data, fallback_market))
                except KiwoomApiError as exc:
                    messages.append(f"{fallback_market}: {exc.message}")

            deduped: dict[str, dict[str, Any]] = {}
            for stock in stocks:
                existing = deduped.get(stock["code"])
                if existing and existing.get("security_type") == "ETF" and stock.get("security_type") != "ETF":
                    continue
                deduped[stock["code"]] = stock
            stocks = sorted(deduped.values(), key=lambda item: (item["market"], item["name"], item["code"]))
            if stocks:
                quality = self._quality("stock_list", "ok" if not messages else "partial", "키움 REST 종목 목록을 수신했습니다.")
                if messages:
                    quality["message"] += " 일부 시장은 실패했습니다: " + " / ".join(messages)
                return stocks, quality
            return [dict(stock, security_type="STOCK") for stock in LOCAL_STOCKS], self._quality("stock_list", "unavailable", "키움 종목 목록 응답을 해석하지 못해 로컬 목록을 사용합니다.")
        except KiwoomApiError as exc:
            return [dict(stock, security_type="STOCK") for stock in LOCAL_STOCKS], self._quality("stock_list", exc.code, exc.message)

    def collect_investor_daily(
        self,
        stocks: list[dict[str, Any]],
        target_date: str,
        progress: Any | None = None,
        batch_callback: Any | None = None,
        *,
        include_values: bool = False,
        include_holdings: bool = True,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not self.configured:
            return [], self._quality("investor_daily", "api_not_configured", "키움 REST API 키가 설정되지 않아 전체 수급을 수집할 수 없습니다.")

        rows: list[dict[str, Any]] = []
        batch: list[dict[str, Any]] = []
        failures: list[str] = []
        total = len(stocks)
        for index, stock in enumerate(stocks, start=1):
            code = str(stock.get("code") or "").zfill(6)
            try:
                close = _to_abs_number(stock.get("last_price"))
                listed_shares = int(_to_abs_number(stock.get("listed_shares")) or 0)
                if not close or not listed_shares:
                    quote = self._get_quote(code)
                    close = quote.get("close")
                    listed_shares = int(quote.get("listed_shares") or listed_shares or 0)
                if not close or not listed_shares:
                    raise KiwoomApiError("missing_data", "종가 또는 상장주식수가 없습니다.")
                investor = self._get_investor_day(code, target_date, include_values=include_values)
                if not investor:
                    raise KiwoomApiError("missing_data", "해당 거래일 투자자 데이터가 없습니다.")
                holding: dict[str, Any] = {}
                if include_holdings:
                    try:
                        holding = self._get_foreign_holding(code, target_date) or {}
                    except KiwoomApiError:
                        # Holding-rate data is supplementary; daily flow can still be ranked.
                        holding = {}
                foreign_qty = float(investor.get("foreign_qty") or 0)
                institution_qty = float(investor.get("institution_qty") or 0)
                market_cap = float(close) * listed_shares
                row = {
                    "trade_date": investor["date"],
                    "code": code,
                    "close": close,
                    "listed_shares": listed_shares,
                    "market_cap": market_cap,
                    "foreign_net_qty": foreign_qty,
                    "foreign_net_value": investor.get("foreign_value") or 0,
                    "institution_net_qty": institution_qty,
                    "institution_net_value": investor.get("institution_value") or 0,
                    "foreign_change_ratio": _ratio(foreign_qty, listed_shares),
                    "institution_change_ratio": _ratio(institution_qty, listed_shares),
                    "combined_change_ratio": _ratio(foreign_qty + institution_qty, listed_shares),
                    "foreign_holding_qty": (
                        holding.get("holding_qty")
                        if holding.get("holding_qty") is not None
                        else investor.get("foreign_holding_qty")
                    ),
                    "foreign_holding_ratio": (
                        holding.get("holding_ratio")
                        if holding.get("holding_ratio") is not None
                        else investor.get("foreign_holding_ratio")
                    ),
                    "data_status": "ok",
                }
                rows.append(row)
                batch.append(row)
                if batch_callback and len(batch) >= 50:
                    batch_callback(batch)
                    batch = []
            except KiwoomApiError as exc:
                failures.append(f"{code}: {exc.message}")
            except (TypeError, ValueError) as exc:
                failures.append(f"{code}: 데이터 변환 실패({exc})")
            if progress:
                progress(index, total, len(rows), len(failures))

        if batch_callback and batch:
            batch_callback(batch)

        status = "ok" if rows and not failures else "partial" if rows else "unavailable"
        message = f"일별 수급 {len(rows)}개 종목을 저장할 수 있습니다."
        if failures:
            message += f" 실패 {len(failures)}개. 예: " + " / ".join(failures[:3])
        return rows, self._quality("investor_daily", status, message)

    def dashboard(self, code: str, lookback: int, timeframe: str = "daily") -> dict[str, Any]:
        stock = local_stock(code)
        data_quality = self._base_quality()
        timeframe = timeframe if timeframe in {"daily", "weekly", "monthly"} else "daily"

        if not self.configured:
            data_quality.update(
                {
                    "connection_status": "api_not_configured",
                    "price_status": "api_not_configured",
                    "chart_status": "api_not_configured",
                    "adr_status": "api_not_configured",
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
        market_adr: list[dict[str, Any]] = []

        try:
            quote = self._get_quote(code)
            if quote:
                stock = {**stock, **{k: v for k, v in quote.items() if k in {"name", "market", "sector", "listed_shares"} and v}}
                data_quality["price_status"] = "ok"
        except KiwoomApiError as exc:
            data_quality["price_status"] = exc.code
            data_quality["messages"].append(exc.message)

        try:
            ohlcv = self._get_price_chart(code, lookback, timeframe)
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
            data_quality["theme_status"] = "unavailable"

        try:
            market_adr = self._get_market_adr()
            data_quality["adr_status"] = "ok" if market_adr else "unavailable"
        except KiwoomApiError as exc:
            data_quality["adr_status"] = exc.code
            data_quality["messages"].append(exc.message)

        data_quality["connection_status"] = "ok" if any([quote, ohlcv, investors, program, themes]) else "unavailable"
        return {
            "stock": stock,
            "quote": quote,
            "ohlcv": ohlcv,
            "investors": investors,
            "program_trading": program,
            "market_adr": market_adr,
            "themes": themes,
            "timeframe": timeframe,
            "data_quality": data_quality,
        }

    def _get_quote(self, code: str) -> dict[str, Any]:
        data = self._post("/api/dostk/stkinfo", "ka10001", {"stk_cd": code})
        return {
            "name": _first(data, ["stk_nm", "isu_nm", "name"]),
            "close": _to_abs_number(_first(data, ["cur_prc", "close_pric", "now_pric", "prpr"])),
            "change": _to_number(_first(data, ["pred_pre", "change", "prdy_vrss"])),
            "change_rate": _to_number(_first(data, ["flu_rt", "chg_rt", "prdy_ctrt"])),
            "volume": _to_abs_number(_first(data, ["trde_qty", "acc_trdvol", "volume"])),
            "trading_value": _to_abs_number(_first(data, ["trde_prica", "acc_trdval", "trading_value"])),
            "listed_shares": _to_abs_number(_first(data, ["flo_stkcnt", "lst_stkcnt", "listed_shares"])),
        }

    def _get_price_chart(self, code: str, lookback: int, timeframe: str) -> list[dict[str, Any]]:
        api_id, row_keys = {
            "daily": ("ka10081", ["stk_dt_pole_chart_qry", "stk_daily_chart_qry", "output", "list"]),
            "weekly": ("ka10082", ["stk_stk_pole_chart_qry", "stk_week_chart_qry", "output", "list"]),
            "monthly": ("ka10083", ["stk_mth_pole_chart_qry", "stk_month_chart_qry", "output", "list"]),
        }[timeframe]
        data = self._post(
            "/api/dostk/chart",
            api_id,
            {"stk_cd": code, "base_dt": datetime.now().strftime("%Y%m%d"), "upd_stkpc_tp": "1"},
        )
        rows = _find_first_list(data, row_keys)
        parsed: list[dict[str, Any]] = []
        for row in rows:
            date = _format_date(_first(row, ["dt", "date", "stck_bsop_date"]))
            close = _to_abs_number(_first(row, ["cur_prc", "close_pric", "stck_clpr", "close"]))
            volume = _to_abs_number(_first(row, ["trde_qty", "acml_vol", "volume"])) or 0
            if not date or close is None:
                continue
            parsed.append(
                {
                    "date": date,
                    "open": _to_abs_number(_first(row, ["open_pric", "stck_oprc", "open"])) or close,
                    "high": _to_abs_number(_first(row, ["high_pric", "stck_hgpr", "high"])) or close,
                    "low": _to_abs_number(_first(row, ["low_pric", "stck_lwpr", "low"])) or close,
                    "close": close,
                    "volume": volume,
                    "trading_value": _to_abs_number(_first(row, ["trde_prica", "acml_tr_pbmn", "trading_value"])) or close * volume,
                }
            )
        parsed.sort(key=lambda item: item["date"])
        return parsed[-lookback:]

    def _get_investor_chart(self, code: str) -> list[dict[str, Any]]:
        qty_data = self._post(
            "/api/dostk/chart",
            "ka10060",
            {"dt": datetime.now().strftime("%Y%m%d"), "stk_cd": code, "amt_qty_tp": "2", "trde_tp": "0", "unit_tp": "1"},
        )
        qty_rows = self._parse_investor_rows(qty_data)
        value_rows: list[dict[str, Any]] = []
        try:
            value_data = self._post(
                "/api/dostk/chart",
                "ka10060",
                {"dt": datetime.now().strftime("%Y%m%d"), "stk_cd": code, "amt_qty_tp": "1", "trde_tp": "0", "unit_tp": "1"},
            )
            value_rows = self._parse_investor_rows(value_data)
        except KiwoomApiError:
            value_rows = []

        by_date = {row["date"]: row for row in qty_rows}
        for row in value_rows:
            target = by_date.setdefault(
                row["date"],
                {"date": row["date"], "foreign_qty": 0, "foreign_value": 0, "institution_qty": 0, "institution_value": 0},
            )
            target["foreign_value"] = row["foreign_qty"] or row["foreign_value"]
            target["institution_value"] = row["institution_qty"] or row["institution_value"]

        parsed = list(by_date.values())
        parsed.sort(key=lambda item: item["date"])
        return parsed

    def _get_investor_day(self, code: str, target_date: str, *, include_values: bool = False) -> dict[str, Any] | None:
        data = self._post(
            "/api/dostk/chart",
            "ka10060",
            {"dt": target_date.replace("-", ""), "stk_cd": code, "amt_qty_tp": "2", "trde_tp": "0", "unit_tp": "1"},
        )
        qty_rows = self._parse_investor_rows(data)
        if not qty_rows:
            return None
        target = next((row for row in qty_rows if row["date"] == target_date), None)
        if target is None:
            eligible = [row for row in qty_rows if row["date"] <= target_date]
            target = eligible[-1] if eligible else qty_rows[-1]
        if include_values:
            try:
                value_data = self._post(
                    "/api/dostk/chart",
                    "ka10060",
                    {"dt": target_date.replace("-", ""), "stk_cd": code, "amt_qty_tp": "1", "trde_tp": "0", "unit_tp": "1"},
                )
                value_rows = self._parse_investor_rows(value_data)
                value = next((row for row in value_rows if row["date"] == target["date"]), None)
                if value:
                    target = {
                        **target,
                        "foreign_value": value.get("foreign_qty") or value.get("foreign_value") or 0,
                        "institution_value": value.get("institution_qty") or value.get("institution_value") or 0,
                    }
            except KiwoomApiError:
                pass
        return target

    def _get_foreign_holding(self, code: str, target_date: str) -> dict[str, Any] | None:
        data = self._post("/api/dostk/frgnistt", "ka10008", {"stk_cd": code})
        rows = _find_first_list(data, ["stk_frgnr", "output", "list"])
        parsed: list[dict[str, Any]] = []
        for row in rows:
            date = _format_date(_first(row, ["dt", "date"]))
            if not date:
                continue
            parsed.append(
                {
                    "date": date,
                    "holding_qty": _to_abs_number(_first(row, ["poss_stkcnt", "foreign_holding_qty"])),
                    "holding_ratio": _to_number(_first(row, ["wght", "foreign_holding_ratio"])),
                }
            )
        if not parsed:
            return None
        parsed.sort(key=lambda item: item["date"])
        return next((row for row in parsed if row["date"] == target_date), parsed[-1])

    def _parse_investor_rows(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        rows = _find_first_list(data, ["stk_invsr_orgn_chart", "output", "list"])
        parsed: list[dict[str, Any]] = []
        for row in rows:
            date = _format_date(_first(row, ["dt", "date"]))
            if not date:
                continue
            parsed.append(
                {
                    "date": date,
                    "foreign_qty": _to_number(
                        _first(
                            row,
                            ["frgnr_invsr", "frgnr_netprps_qty", "for_netprps_qty", "frgnr", "frgn", "frgnr_trde_qty", "foreign_qty"],
                        )
                    )
                    or 0,
                    "foreign_value": _to_number(
                        _first(row, ["frgnr_netprps_amt", "frgnr_trde_amt", "for_netprps_amt", "frgn_amt", "foreign_value"])
                    )
                    or 0,
                    "institution_qty": _to_number(
                        _first(row, ["orgn", "orgn_netprps_qty", "inst_netprps_qty", "inst", "orgn_trde_qty", "institution_qty"])
                    )
                    or 0,
                    "institution_value": _to_number(
                        _first(row, ["orgn_netprps_amt", "inst_netprps_amt", "orgn_trde_amt", "inst_amt", "institution_value"])
                    )
                    or 0,
                    "foreign_holding_qty": _to_abs_number(
                        _first(row, ["poss_stkcnt", "foreign_holding_qty", "frgnr_poss_stkcnt"])
                    ),
                    "foreign_holding_ratio": _to_number(
                        _first(row, ["wght", "foreign_holding_ratio", "frgnr_wght"])
                    ),
                }
            )
        parsed.sort(key=lambda item: item["date"])
        return parsed

    def _get_program_trading(self, code: str) -> list[dict[str, Any]]:
        today = datetime.now().strftime("%Y%m%d")
        attempts = [
            ("/api/dostk/mrkcond", "ka90013", {"stk_cd": code, "date": today, "amt_qty_tp": "1"}),
            ("/api/dostk/mrkcond", "ka90013", {"stk_cd": code, "date": today, "amt_qty_tp": "2"}),
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
        rows = _find_first_list(data, ["stk_daly_prm_trde_trnsn", "stk_day_progrm_trde_trnsn", "stk_progrm_trde", "output", "list"])
        parsed: list[dict[str, Any]] = []
        for row in rows:
            date = _format_date(_first(row, ["dt", "date"]))
            if not date:
                continue
            buy = _to_number(_first(row, ["buy_amt", "buy_amount_m", "prm_buy_amt", "nprft_buy_amt", "non_arbitrage_buy_amt"])) or 0
            sell = _to_number(_first(row, ["sell_amt", "sell_amount_m", "prm_sell_amt", "nprft_sell_amt", "non_arbitrage_sell_amt"])) or 0
            net = _to_number(_first(row, ["netprps_amt", "net_amount_m", "prm_netprps_amt", "nprft_netprps_amt", "non_arbitrage_net_amount"])) or buy - sell
            parsed.append(
                {
                    "date": date,
                    "close": _to_abs_number(_first(row, ["cur_prc", "close_pric", "close"])) or 0,
                    "change_rate": _to_number(_first(row, ["flu_rt", "change_rate"])),
                    "volume": _to_abs_number(_first(row, ["trde_qty", "volume"])) or 0,
                    "sell_amount_m": sell,
                    "buy_amount_m": buy,
                    "net_amount_m": net,
                }
            )
        parsed.sort(key=lambda item: item["date"])
        return parsed

    def _get_themes_for_stock(self, code: str) -> list[dict[str, Any]]:
        # ka90001 supports direct stock-theme lookup (qry_tp=2).  The previous
        # implementation fetched every theme and then called ka90002 once per
        # theme, which was both slow and incompatible with the current response
        # key (thema_grp).
        data = self._post(
            "/api/dostk/thme",
            "ka90001",
            {
                "qry_tp": "2",
                "stk_cd": code,
                "date_tp": "10",
                "thema_nm": "",
                "flu_pl_amt_tp": "1",
                "stex_tp": "1",
            },
        )
        rows = _find_first_list(data, ["thema_grp", "theme_group", "thme_group", "output", "list"])
        themes: list[dict[str, Any]] = []
        for row in rows:
            theme_code = _first(row, ["thema_grp_cd", "theme_cd", "thme_cd", "code"])
            theme_name = _first(row, ["thema_nm", "theme_nm", "thme_nm", "name"])
            if not theme_code or not theme_name:
                continue
            themes.append(
                {
                    "code": str(theme_code),
                    "name": str(theme_name),
                    "stock_count": _to_abs_number(_first(row, ["stk_num", "stock_count"])),
                    "change_rate": _to_number(_first(row, ["flu_rt", "change_rate"])),
                    "period_return": _to_number(_first(row, ["dt_prft_rt", "period_return"])),
                    "rising_count": _to_abs_number(_first(row, ["rising_stk_num", "rising_count"])),
                    "falling_count": _to_abs_number(_first(row, ["fall_stk_num", "falling_count"])),
                    "main_stock": _first(row, ["main_stk", "main_stock"]),
                }
            )
            if len(themes) >= 8:
                break
        return themes

    def _get_market_adr(self) -> list[dict[str, Any]]:
        attempts = [
            ("/api/dostk/sect", "ka20003", {"mrkt_tp": "0", "inds_cd": "001"}),
            ("/api/dostk/sect", "ka20003", {"mrkt_tp": "0", "inds_cd": "101"}),
            ("/api/dostk/sect", "ka20001", {"mrkt_tp": "0", "upjong_cd": "001", "inds_cd": "001"}),
        ]
        last_error: KiwoomApiError | None = None
        for endpoint, api_id, body in attempts:
            try:
                data = self._post(endpoint, api_id, body)
                parsed = self._parse_adr_rows(data)
                if parsed:
                    return parsed[-120:]
            except KiwoomApiError as exc:
                last_error = exc
        if last_error:
            raise last_error
        return []

    def _parse_adr_rows(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        rows = _find_first_list(data, ["all_inds_idex", "upjong_stkpc", "upjong_pric", "output", "list"])
        if not rows:
            rows = [data]
        parsed: list[dict[str, Any]] = []
        for idx, row in enumerate(rows):
            advances = _to_abs_number(_first(row, ["rising", "rise_stk_cnt", "up_stk_cnt", "stk_cnt_up", "advances", "up_cnt"]))
            declines = _to_abs_number(_first(row, ["fall", "fall_stk_cnt", "down_stk_cnt", "stk_cnt_down", "declines", "down_cnt"]))
            if advances is None or declines is None or declines == 0:
                continue
            date = _format_date(_first(row, ["dt", "date", "base_dt"])) or datetime.now().strftime("%Y-%m-%d")
            parsed.append(
                {
                    "date": date if len(rows) > 1 else f"{date}-{idx}",
                    "advances": advances,
                    "declines": declines,
                    "adr": round(advances / declines * 100, 2),
                }
            )
        return parsed

    def _request_token(self) -> dict[str, Any]:
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
            raise KiwoomApiError("network_error", f"Kiwoom token request failed: {exc}") from exc
        data = _response_json(response)
        if response.status_code >= 400 or str(data.get("return_code", "0")) not in {"0", ""}:
            return_code = data.get("return_code")
            return_msg = data.get("return_msg") or data.get("message")
            details = [f"HTTP {response.status_code}"]
            if return_code not in (None, ""):
                details.append(f"return_code={return_code}")
            if return_msg:
                details.append(str(return_msg))
            raise KiwoomApiError("auth_failed", " / ".join(details))
        return data

    def _token_value(self) -> str:
        if self._token and self._token_expires_at and self._token_expires_at > datetime.now() + timedelta(minutes=5):
            return self._token
        data = self._request_token()
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

    def _parse_stock_list(self, data: dict[str, Any], fallback_market: str = "KRX") -> list[dict[str, Any]]:
        rows = _find_first_list(data, ["list", "stk_info", "result_list", "output", "items"])
        stocks: list[dict[str, Any]] = []
        for row in rows:
            code = _stock_code(_first(row, ["stk_cd", "code", "isu_cd"]))
            name = _first(row, ["stk_nm", "name", "isu_nm"])
            if not code or not name:
                continue
            stocks.append(
                {
                    "code": code.zfill(6),
                    "name": str(name),
                    "market": _market_name(row, fallback_market),
                    "sector": _first(row, ["upName", "upSizeName", "upjong_nm", "sector"]),
                    "listed_shares": _to_abs_number(_first(row, ["listCount", "list_stock_cnt", "listed_shares"])),
                    "last_price": _to_abs_number(_first(row, ["cur_prc", "close_pric", "now_pric", "prpr", "last_price"])),
                    "security_type": "ETF" if fallback_market == "ETF" else _security_type(row, name),
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
            "adr_status": "unknown",
            "investor_status": "unknown",
            "program_status": "unknown",
            "theme_status": "unknown",
            "messages": [],
        }

    def _quality(self, scope: str, status: str, message: str) -> dict[str, Any]:
        return {"source": "kiwoom_rest", "scope": scope, "status": status, "message": message}

    def _empty_dashboard(self, stock: dict[str, Any], data_quality: dict[str, Any]) -> dict[str, Any]:
        return {
            "stock": stock,
            "quote": {},
            "ohlcv": [],
            "investors": [],
            "program_trading": [],
            "market_adr": [],
            "themes": [],
            "timeframe": "daily",
            "data_quality": data_quality,
        }


class DataProvider:
    def __init__(self):
        self.kiwoom = KiwoomRestProvider()

    def list_stocks(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return self.kiwoom.list_stocks()

    def build_dashboard(self, code: str, lookback: int, timeframe: str = "daily") -> dict[str, Any]:
        return self.kiwoom.dashboard(code, lookback, timeframe)

    def collect_investor_daily(
        self,
        stocks: list[dict[str, Any]],
        target_date: str,
        progress: Any | None = None,
        batch_callback: Any | None = None,
        *,
        include_values: bool = False,
        include_holdings: bool = True,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return self.kiwoom.collect_investor_daily(
            stocks,
            target_date,
            progress,
            batch_callback,
            include_values=include_values,
            include_holdings=include_holdings,
        )

    def status(self) -> dict[str, Any]:
        return self.kiwoom.status()

    def test_auth(self) -> dict[str, Any]:
        return self.kiwoom.test_auth()


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


def _to_abs_number(value: Any) -> float | None:
    number = _to_number(value)
    return abs(number) if number is not None else None


def _digits(value: Any) -> str | None:
    if value in (None, ""):
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits or None


def _stock_code(value: Any) -> str | None:
    if value in (None, ""):
        return None
    code = str(value).strip()
    return code if code.isdigit() and len(code) == 6 else None


def _format_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    digits = _digits(value)
    if not digits or len(digits) < 8:
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def _ratio(value: float, denominator: int) -> float:
    if not denominator:
        return 0.0
    return round(value / denominator * 100, 6)


def _market_name(row: dict[str, Any], fallback: str) -> str:
    market_code = str(_first(row, ["marketCode", "market_code", "mrkt_cd"]) or "").strip()
    by_code = {
        "0": "KOSPI",
        "001": "KOSPI",
        "10": "KOSDAQ",
        "101": "KOSDAQ",
    }
    if market_code in by_code:
        return by_code[market_code]
    raw = str(_first(row, ["marketName", "mrkt_nm", "market"]) or "").strip()
    normalized = raw.upper()
    if "KOSPI" in normalized or "코스피" in raw:
        return "KOSPI"
    if "KOSDAQ" in normalized or "코스닥" in raw:
        return "KOSDAQ"
    return raw or fallback


def _security_type(row: dict[str, Any], name: Any) -> str:
    etf_flag = str(_first(row, ["etf_yn", "etfYn", "is_etf"]) or "").strip().upper()
    if etf_flag in {"Y", "YES", "TRUE", "1", "ETF"}:
        return "ETF"
    etn_flag = str(_first(row, ["etn_yn", "etnYn", "is_etn"]) or "").strip().upper()
    if etn_flag in {"Y", "YES", "TRUE", "1", "ETN"}:
        return "ETN"
    values = [
        str(_first(row, ["security_type", "stk_kind", "secu_tp", "etf_yn", "etfYn", "asset_type"]) or ""),
        str(_first(row, ["marketName", "mrkt_nm", "market"]) or ""),
        str(name or ""),
    ]
    joined = " ".join(values).upper()
    if "ETN" in joined:
        return "ETN"
    if "ELW" in joined:
        return "ELW"
    if "ETF" in joined:
        return "ETF"
    if any(token in joined for token in ["우선", "PREFERRED"]):
        return "PREFERRED"
    if "스팩" in joined or "SPAC" in joined:
        return "SPAC"
    if "리츠" in joined or "REIT" in joined:
        return "REIT"
    return "STOCK"


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
