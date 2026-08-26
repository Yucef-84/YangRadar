from __future__ import annotations

import math
from unittest import TestCase
from unittest.mock import Mock

from backend.app.config import Settings
from backend.app.services.data_provider import KiwoomRestProvider, _ratio


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
