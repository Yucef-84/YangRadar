from __future__ import annotations

import math
from unittest import TestCase
from unittest.mock import Mock, patch

from backend.app.config import Settings
from backend.app.services import data_provider as data_provider_module
from backend.app.services.data_provider import KiwoomApiError, KiwoomRestProvider, _ratio


def _provider(response: dict) -> KiwoomRestProvider:
    provider = KiwoomRestProvider(
        Settings(
            kiwoom_app_key="app",
            kiwoom_secret_key="secret",
            kiwoom_account_no="account",
            kiwoom_env="mock",
            kiwoom_base_url="https://mockapi.kiwoom.com",
        )
    )
    provider._post = lambda *args, **kwargs: response  # type: ignore[method-assign]
    return provider


def _investor_row(date: str, foreign: str = "10", institution: str = "5", **extra: str) -> dict[str, str]:
    return {"dt": date, "frgnr_invsr": foreign, "orgn": institution, **extra}


class PriceChartTradingValueUnitTests(TestCase):
    def _chart_response(self, **row_overrides: str) -> dict:
        row = {
            "dt": "20260826",
            "cur_prc": "100000",
            "trde_qty": "10000",
            **row_overrides,
        }
        return {"stk_dt_pole_chart_qry": [row]}

    def test_api_trading_value_is_preserved_in_million_won(self) -> None:
        provider = _provider(self._chart_response(trde_prica="1234"))

        rows = provider._get_price_chart("005930", 10, "daily")

        self.assertEqual(rows[0]["trading_value"], 1234)

    def test_missing_trading_value_falls_back_to_million_won(self) -> None:
        provider = _provider(self._chart_response())

        rows = provider._get_price_chart("005930", 10, "daily")

        self.assertEqual(rows[0]["trading_value"], 1000)

    def test_explicit_zero_trading_value_does_not_use_fallback(self) -> None:
        provider = _provider(self._chart_response(trde_prica="0"))

        rows = provider._get_price_chart("005930", 10, "daily")

        self.assertEqual(rows[0]["trading_value"], 0)


class InvestorDateSelectionTests(TestCase):
    def test_exact_date_is_selected(self) -> None:
        provider = _provider(
            {
                "stk_invsr_orgn_chart": [
                    _investor_row("20260822"),
                    _investor_row("20260825", "20", "15"),
                    _investor_row("20260826", "30", "25"),
                ]
            }
        )
        result = provider._get_investor_day("005930", "2026-08-25")
        self.assertIsNotNone(result)
        self.assertEqual(result["date"], "2026-08-25")
        self.assertEqual(result["foreign_qty"], 20)

    def test_previous_date_is_used_when_target_is_a_holiday(self) -> None:
        provider = _provider(
            {"stk_invsr_orgn_chart": [_investor_row("20260822"), _investor_row("20260826")]}
        )
        result = provider._get_investor_day("005930", "2026-08-25")
        self.assertIsNotNone(result)
        self.assertEqual(result["date"], "2026-08-22")

    def test_future_only_response_is_rejected(self) -> None:
        provider = _provider({"stk_invsr_orgn_chart": [_investor_row("20260826")]})
        self.assertIsNone(provider._get_investor_day("005930", "2026-08-25"))

    def test_no_eligible_date_is_rejected(self) -> None:
        provider = _provider({"stk_invsr_orgn_chart": []})
        self.assertIsNone(provider._get_investor_day("005930", "2026-08-25"))


class InvestorReadinessTests(TestCase):
    def _response(self, date: str) -> dict:
        return {"stk_invsr_orgn_chart": [_investor_row(date)]}

    def test_two_of_three_exact_dates_are_ready(self) -> None:
        provider = _provider({})
        provider._post = Mock(
            side_effect=[
                self._response("20260825"),
                self._response("20260825"),
                self._response("20260824"),
            ]
        )

        result = provider.check_investor_readiness("2026-08-25")

        self.assertTrue(result["ready"])
        self.assertTrue(result["checked"])
        self.assertEqual(result["ready_count"], 2)
        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(provider._post.call_count, 3)
        self.assertTrue(all(call.args[1] == "ka10060" for call in provider._post.call_args_list))
        self.assertTrue(all(call.args[2]["amt_qty_tp"] == "2" for call in provider._post.call_args_list))

    def test_one_sample_error_does_not_block_two_exact_dates(self) -> None:
        provider = _provider({})
        provider._post = Mock(
            side_effect=[
                KiwoomApiError("network_error", "temporary"),
                self._response("20260825"),
                self._response("20260825"),
            ]
        )

        result = provider.check_investor_readiness("2026-08-25")

        self.assertTrue(result["ready"])
        self.assertEqual(result["ready_count"], 2)
        self.assertEqual(result["samples"][0]["status"], "error")
        self.assertEqual(result["samples"][0]["error_code"], "network_error")
        self.assertEqual(result["samples"][0]["error"], "network_error")

    def test_prior_date_fallback_is_not_ready(self) -> None:
        provider = _provider({})
        provider._post = Mock(
            side_effect=[
                self._response("20260824"),
                self._response("20260824"),
                self._response("20260824"),
            ]
        )

        result = provider.check_investor_readiness("2026-08-25")

        self.assertFalse(result["ready"])
        self.assertEqual(result["ready_count"], 0)
        self.assertTrue(all(sample["status"] == "stale" for sample in result["samples"]))
        self.assertEqual(result["status"], "waiting_data")

    def test_all_sample_api_errors_have_error_status(self) -> None:
        provider = _provider({})
        provider._post = Mock(
            side_effect=[
                KiwoomApiError("network_error", "temporary"),
                KiwoomApiError("rate_limited", "temporary"),
                KiwoomApiError("api_error", "temporary"),
            ]
        )

        result = provider.check_investor_readiness("2026-08-25")

        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_count"], 3)
        self.assertEqual(result["ready_count"], 0)

    def test_readiness_does_not_enumerate_universe_or_request_supplementary_data(self) -> None:
        provider = _provider({})
        provider._post = Mock(
            side_effect=[self._response("20260825")] * len(data_provider_module.INVESTOR_READINESS_SAMPLE_CODES)
        )
        provider.list_stocks = Mock()  # type: ignore[method-assign]
        provider._get_quote = Mock()  # type: ignore[method-assign]
        provider._get_foreign_holding = Mock()  # type: ignore[method-assign]

        provider.check_investor_readiness("2026-08-25")

        provider.list_stocks.assert_not_called()
        provider._get_quote.assert_not_called()
        provider._get_foreign_holding.assert_not_called()
        self.assertEqual(provider._post.call_count, 3)


class ForeignHoldingDateSelectionTests(TestCase):
    def test_previous_holding_date_is_used(self) -> None:
        provider = _provider(
            {
                "stk_frgnr": [
                    {"dt": "20260822", "poss_stkcnt": "100", "wght": "1.2"},
                    {"dt": "20260826", "poss_stkcnt": "200", "wght": "2.4"},
                ]
            }
        )
        result = provider._get_foreign_holding("005930", "2026-08-25")
        self.assertIsNotNone(result)
        self.assertEqual(result["date"], "2026-08-22")

    def test_future_only_holding_response_is_rejected(self) -> None:
        provider = _provider(
            {"stk_frgnr": [{"dt": "20260826", "poss_stkcnt": "200", "wght": "2.4"}]}
        )
        self.assertIsNone(provider._get_foreign_holding("005930", "2026-08-25"))


class InvestorFieldParsingTests(TestCase):
    def test_explicit_zero_is_retained(self) -> None:
        provider = _provider({})
        rows = provider._parse_investor_rows(
            {"stk_invsr_orgn_chart": [_investor_row("20260825", "0", "-0")]}
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["foreign_qty"], 0)
        self.assertEqual(rows[0]["institution_qty"], 0)

    def test_missing_empty_and_invalid_required_fields_are_excluded(self) -> None:
        provider = _provider({})
        rows = provider._parse_investor_rows(
            {
                "stk_invsr_orgn_chart": [
                    {"dt": "20260825", "frgnr_invsr": "10"},
                    _investor_row("20260825", "", "5"),
                    _investor_row("20260825", "not-a-number", "5"),
                    _investor_row("20260825", "10", ""),
                ]
            }
        )
        self.assertEqual(rows, [])

    def test_non_finite_required_fields_are_excluded(self) -> None:
        provider = _provider({})
        rows = provider._parse_investor_rows(
            {
                "stk_invsr_orgn_chart": [
                    _investor_row("20260825", "NaN", "5"),
                    _investor_row("20260825", "5", "Infinity"),
                    _investor_row("20260825", "-inf", "5"),
                    _investor_row("20260825", "INF", "5"),
                    _investor_row("20260825", "-Infinity", "5"),
                ]
            }
        )
        self.assertEqual(rows, [])

    def test_normal_values_and_ratios_are_finite(self) -> None:
        provider = _provider({})
        rows = provider._parse_investor_rows(
            {"stk_invsr_orgn_chart": [_investor_row("20260825", "-10", "+20")]}
        )
        self.assertEqual(len(rows), 1)
        self.assertTrue(math.isfinite(rows[0]["foreign_qty"]))
        self.assertTrue(math.isfinite(rows[0]["institution_qty"]))
        self.assertTrue(math.isfinite(_ratio(rows[0]["foreign_qty"], 1000)))
        self.assertTrue(math.isfinite(_ratio(rows[0]["institution_qty"], 1000)))

    def test_optional_amount_fields_remain_missing(self) -> None:
        provider = _provider({})
        rows = provider._parse_investor_rows(
            {"stk_invsr_orgn_chart": [_investor_row("20260825", "10", "5")]}
        )
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["foreign_value"])
        self.assertIsNone(rows[0]["institution_value"])


class StockListQualityTests(TestCase):
    def test_partial_market_response_is_not_marked_complete(self) -> None:
        provider = _provider({})
        from backend.app.services.data_provider import KiwoomApiError

        provider._post = Mock(side_effect=[
            {"list": [{"stk_cd": "000001", "stk_nm": "코스피 종목"}]},
            {"list": [{"stk_cd": "000002", "stk_nm": "코스닥 종목"}]},
            KiwoomApiError("network_error", "ETF unavailable"),
        ])
        stocks, quality = provider.list_stocks()
        self.assertEqual(len(stocks), 2)
        self.assertEqual(quality["status"], "partial")
        self.assertFalse(quality["complete"])

    def test_empty_successful_market_response_is_not_complete(self) -> None:
        provider = _provider({})
        provider._post = Mock(
            side_effect=[
                {"list": [{"stk_cd": "000001", "stk_nm": "코스피 종목"}]},
                {"list": [{"stk_cd": "000002", "stk_nm": "코스닥 종목"}]},
                {"list": []},
            ]
        )
        stocks, quality = provider.list_stocks()
        self.assertEqual(len(stocks), 2)
        self.assertEqual(quality["status"], "partial")
        self.assertFalse(quality["complete"])


class InvestorHoldingConsistencyTests(TestCase):
    def test_holding_from_another_date_is_not_combined(self) -> None:
        provider = _provider({})
        provider._get_investor_day = lambda *args, **kwargs: {  # type: ignore[method-assign]
            "date": "2026-08-22",
            "foreign_qty": 10,
            "foreign_value": None,
            "institution_qty": 5,
            "institution_value": None,
        }
        provider._get_foreign_holding = lambda *args, **kwargs: {  # type: ignore[method-assign]
            "date": "2026-08-20",
            "holding_qty": 100,
            "holding_ratio": 1.2,
        }
        rows, quality = provider.collect_investor_daily(
            [{"code": "005930", "last_price": 100, "listed_shares": 1000}],
            "2026-08-25",
        )
        self.assertEqual(quality["status"], "ok")
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["foreign_holding_qty"])
        self.assertIsNone(rows[0]["foreign_holding_ratio"])


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleep_calls: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.now += seconds


def _http_response(status_code: int, payload: dict | None = None) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.text = ""
    response.json.return_value = payload or {"return_code": "0"}
    return response


class KiwoomRateLimitTests(TestCase):
    def setUp(self) -> None:
        self.previous_last_request_at = data_provider_module._kiwoom_last_request_at
        data_provider_module._kiwoom_last_request_at = None
        self.addCleanup(self._restore_rate_limiter)

    def _restore_rate_limiter(self) -> None:
        data_provider_module._kiwoom_last_request_at = self.previous_last_request_at

    def _provider(
        self,
        *,
        request_interval: float = 0.0,
        rate_limit_retries: int = 3,
        rate_limit_backoff: tuple[float, ...] = (1.0, 2.0, 4.0),
    ) -> KiwoomRestProvider:
        return KiwoomRestProvider(
            Settings(
                kiwoom_app_key="app",
                kiwoom_secret_key="secret",
                kiwoom_account_no="account",
                kiwoom_env="mock",
                kiwoom_base_url="https://mockapi.kiwoom.com",
            ),
            request_interval=request_interval,
            rate_limit_retries=rate_limit_retries,
            rate_limit_backoff=rate_limit_backoff,
        )

    def test_common_limiter_enforces_configured_interval_without_real_sleep(self) -> None:
        clock = _FakeClock()
        with patch.object(data_provider_module.time, "monotonic", side_effect=clock.monotonic), patch.object(
            data_provider_module.time, "sleep", side_effect=clock.sleep
        ):
            data_provider_module._wait_for_kiwoom_request_slot(0.275)
            data_provider_module._wait_for_kiwoom_request_slot(0.275)
            data_provider_module._wait_for_kiwoom_request_slot(0.275)

        self.assertEqual(clock.sleep_calls, [0.275, 0.275])

    def test_different_provider_instances_and_trs_share_limiter(self) -> None:
        clock = _FakeClock()
        provider_a = self._provider(request_interval=0.275)
        provider_b = self._provider(request_interval=0.275)
        responses = [_http_response(200), _http_response(200), _http_response(200)]
        with patch.object(data_provider_module.time, "monotonic", side_effect=clock.monotonic), patch.object(
            data_provider_module.time, "sleep", side_effect=clock.sleep
        ), patch.object(provider_a, "_token_value", return_value="token"), patch.object(
            provider_b, "_token_value", return_value="token"
        ), patch.object(data_provider_module.requests, "post", side_effect=responses) as post:
            provider_a._post("/api/dostk/frgnistt", "ka10060", {"stk_cd": "005930"})
            provider_b._post("/api/dostk/frgnistt", "ka10008", {"stk_cd": "005930"})
            provider_a._post("/api/dostk/stkinfo", "ka10001", {"stk_cd": "005930"})

        self.assertEqual(post.call_count, 3)
        self.assertEqual(clock.sleep_calls, [0.275, 0.275])

    def test_429_retries_then_returns_success(self) -> None:
        clock = _FakeClock()
        provider = self._provider(rate_limit_backoff=(1.0, 2.0, 4.0))
        with patch.object(data_provider_module.time, "monotonic", side_effect=clock.monotonic), patch.object(
            data_provider_module.time, "sleep", side_effect=clock.sleep
        ), patch.object(provider, "_token_value", return_value="token"), patch.object(
            data_provider_module.requests, "post", side_effect=[_http_response(429), _http_response(200)]
        ) as post:
            result = provider._post("/api/dostk/frgnistt", "ka10060", {"stk_cd": "005930"})

        self.assertEqual(result, {"return_code": "0"})
        self.assertEqual(post.call_count, 2)
        self.assertEqual(clock.sleep_calls, [1.0])

    def test_multiple_429_responses_use_exponential_backoff(self) -> None:
        clock = _FakeClock()
        provider = self._provider()
        with patch.object(data_provider_module.time, "monotonic", side_effect=clock.monotonic), patch.object(
            data_provider_module.time, "sleep", side_effect=clock.sleep
        ), patch.object(provider, "_token_value", return_value="token"), patch.object(
            data_provider_module.requests, "post", side_effect=[_http_response(429), _http_response(429), _http_response(200)]
        ) as post:
            result = provider._post("/api/dostk/frgnistt", "ka10008", {"stk_cd": "005930"})

        self.assertEqual(result, {"return_code": "0"})
        self.assertEqual(post.call_count, 3)
        self.assertEqual(clock.sleep_calls, [1.0, 2.0])

    def test_rate_limited_error_is_preserved_after_retry_budget(self) -> None:
        clock = _FakeClock()
        provider = self._provider()
        with patch.object(data_provider_module.time, "monotonic", side_effect=clock.monotonic), patch.object(
            data_provider_module.time, "sleep", side_effect=clock.sleep
        ), patch.object(provider, "_token_value", return_value="token"), patch.object(
            data_provider_module.requests,
            "post",
            side_effect=[_http_response(429), _http_response(429), _http_response(429), _http_response(429)],
        ) as post:
            with self.assertRaises(KiwoomApiError) as context:
                provider._post("/api/dostk/frgnistt", "ka10060", {"stk_cd": "005930"})

        self.assertEqual(context.exception.code, "rate_limited")
        self.assertEqual(context.exception.message, "키움 요청 제한에 걸렸습니다.")
        self.assertEqual(post.call_count, 4)
        self.assertEqual(clock.sleep_calls, [1.0, 2.0, 4.0])

    def test_non_429_error_is_not_retried(self) -> None:
        clock = _FakeClock()
        provider = self._provider()
        with patch.object(data_provider_module.time, "monotonic", side_effect=clock.monotonic), patch.object(
            data_provider_module.time, "sleep", side_effect=clock.sleep
        ), patch.object(provider, "_token_value", return_value="token"), patch.object(
            data_provider_module.requests, "post", return_value=_http_response(500, {"return_msg": "server error"})
        ) as post:
            with self.assertRaises(KiwoomApiError) as context:
                provider._post("/api/dostk/frgnistt", "ka10060", {"stk_cd": "005930"})

        self.assertEqual(context.exception.code, "api_error")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(clock.sleep_calls, [])

    def test_401_behavior_remains_token_expired_without_retry(self) -> None:
        clock = _FakeClock()
        provider = self._provider()
        provider._token = "cached-token"
        with patch.object(data_provider_module.time, "monotonic", side_effect=clock.monotonic), patch.object(
            data_provider_module.time, "sleep", side_effect=clock.sleep
        ), patch.object(provider, "_token_value", return_value="token"), patch.object(
            data_provider_module.requests, "post", return_value=_http_response(401)
        ) as post:
            with self.assertRaises(KiwoomApiError) as context:
                provider._post("/api/dostk/frgnistt", "ka10060", {"stk_cd": "005930"})

        self.assertEqual(context.exception.code, "token_expired")
        self.assertIsNone(provider._token)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(clock.sleep_calls, [])
