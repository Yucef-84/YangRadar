from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from backend.app.config import Settings, normalize_kiwoom_base_url, public_kiwoom_settings, save_kiwoom_settings


class ConfigSecurityTests(TestCase):
    def test_account_number_is_masked_in_public_settings(self) -> None:
        settings = Settings(
            kiwoom_app_key="app-key-value",
            kiwoom_secret_key="secret-key-value",
            kiwoom_account_no="1234567890",
            kiwoom_env="real",
            kiwoom_base_url="https://api.kiwoom.com",
        )
        with patch("backend.app.config.get_settings", return_value=settings):
            public = public_kiwoom_settings()
        self.assertNotEqual(public["account_no"], settings.kiwoom_account_no)
        self.assertEqual(public["account_no"], "1234**7890")
        self.assertNotIn(settings.kiwoom_secret_key, public.values())

    def test_only_official_environment_host_is_allowed(self) -> None:
        self.assertEqual(normalize_kiwoom_base_url("real", ""), "https://api.kiwoom.com")
        self.assertEqual(normalize_kiwoom_base_url("mock", "https://mockapi.kiwoom.com/"), "https://mockapi.kiwoom.com")
        with self.assertRaises(ValueError):
            normalize_kiwoom_base_url("real", "https://example.invalid")
        with self.assertRaises(ValueError):
            normalize_kiwoom_base_url("mock", "https://api.kiwoom.com")

    def test_saved_settings_normalize_the_base_url(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            save_kiwoom_settings(
                app_key="app",
                secret_key="secret",
                account_no="account",
                env="mock",
                base_url="",
                path=path,
            )
            self.assertIn("KIWOOM_BASE_URL=https://mockapi.kiwoom.com", path.read_text(encoding="utf-8"))
