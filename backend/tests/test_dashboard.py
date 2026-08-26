from __future__ import annotations

from unittest import TestCase

from backend.app.services.dashboard import _description


class DescriptionTests(TestCase):
    def test_normal_market_sector_and_themes_are_explicit(self) -> None:
        result = _description(
            {"market": "KOSPI", "sector": "전기전자"},
            [{"name": "반도체"}, {"name": "HBM"}, {"name": "AI"}],
        )

        self.assertEqual(
            result,
            "KOSPI 상장 종목 · 업종 전기전자 · 키움 관련 테마: 반도체, HBM, AI.",
        )

    def test_description_limits_themes_to_first_three_in_api_order(self) -> None:
        result = _description(
            {"market": "KOSPI", "sector": "전기전자"},
            [{"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "D"}],
        )

        self.assertIn("키움 관련 테마: A, B, C.", result)
        self.assertNotIn("D", result)

    def test_description_removes_blank_and_duplicate_theme_names(self) -> None:
        result = _description(
            {"market": "KOSPI", "sector": "전기전자"},
            [{"name": "AI"}, {"name": ""}, {"name": " AI "}, {"name": "반도체"}],
        )

        self.assertEqual(
            result,
            "KOSPI 상장 종목 · 업종 전기전자 · 키움 관련 테마: AI, 반도체.",
        )

    def test_description_uses_clear_fallbacks_for_missing_metadata(self) -> None:
        result = _description(
            {"market": "UNKNOWN", "sector": "정보 없음"},
            [],
        )

        self.assertEqual(
            result,
            "상장시장 정보 없음 · 업종 정보 없음 · 관련 테마 정보 없음.",
        )
