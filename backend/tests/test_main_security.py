from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from fastapi import HTTPException

from backend.app import main
from backend.app.config import Settings
from backend.app.main import _require_local_settings_request


class ASGITestClient:
    """Small dependency-free ASGI client for security route integration tests."""

    def __init__(self, application):
        self.application = application

    def request(
        self,
        method: str,
        path: str,
        *,
        client_host: str,
        headers: dict[str, str] | None = None,
        json_body: dict | None = None,
    ) -> tuple[int, bytes]:
        response_start: dict = {}
        response_body: list[bytes] = []
        body = json.dumps(json_body).encode("utf-8") if json_body is not None else b""
        request_sent = False

        async def receive() -> dict:
            nonlocal request_sent
            if request_sent:
                return {"type": "http.disconnect"}
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message: dict) -> None:
            if message["type"] == "http.response.start":
                response_start.update(message)
            elif message["type"] == "http.response.body":
                response_body.append(message.get("body", b""))

        request_headers = {"content-type": "application/json"} if json_body is not None else {}
        request_headers.update(headers or {})
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [(key.lower().encode("ascii"), value.encode("latin-1")) for key, value in request_headers.items()],
            "client": (client_host, 4567),
            "server": ("testserver", 8000),
            "root_path": "",
        }
        asyncio.run(self.application(scope, receive, send))
        return response_start["status"], b"".join(response_body)


class SettingsEndpointSecurityTests(TestCase):
    def setUp(self) -> None:
        self.client = ASGITestClient(main.app)

    def test_evil_origin_health_request_is_rejected(self) -> None:
        status, _body = self.client.request(
            "GET",
            "/api/health",
            client_host="127.0.0.1",
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(status, 403)

    def test_evil_origin_ranking_refresh_is_rejected_before_start(self) -> None:
        fake_service = Mock()
        with patch.object(main, "ranking_service", fake_service):
            status, _body = self.client.request(
                "POST",
                "/api/rankings/investor/refresh",
                client_host="127.0.0.1",
                headers={"Origin": "https://evil.example"},
            )
        self.assertEqual(status, 403)
        fake_service.start.assert_not_called()

    def test_originless_cross_site_dashboard_is_rejected_before_provider_call(self) -> None:
        fake_provider = Mock()
        with patch.object(main, "provider", fake_provider):
            status, _body = self.client.request(
                "GET",
                "/api/stocks/005930/dashboard",
                client_host="127.0.0.1",
                headers={"Sec-Fetch-Site": "cross-site"},
            )
        self.assertEqual(status, 403)
        fake_provider.build_dashboard.assert_not_called()

    def test_allowed_local_origins_are_accepted(self) -> None:
        for origin in ("http://127.0.0.1:4173", "http://localhost:4173"):
            status, _body = self.client.request(
                "GET",
                "/api/health",
                client_host="127.0.0.1",
                headers={"Origin": origin},
            )
            self.assertEqual(status, 200, origin)

    def test_originless_native_request_is_accepted(self) -> None:
        status, _body = self.client.request(
            "GET",
            "/api/health",
            client_host="127.0.0.1",
        )
        self.assertEqual(status, 200)

    def test_loopback_request_is_allowed(self) -> None:
        _require_local_settings_request(SimpleNamespace(client=SimpleNamespace(host="127.0.0.1")))
        _require_local_settings_request(SimpleNamespace(client=SimpleNamespace(host="::1")))

    def test_remote_request_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as context:
            _require_local_settings_request(SimpleNamespace(client=SimpleNamespace(host="203.0.113.10")))
        self.assertEqual(context.exception.status_code, 403)

    def test_forwarded_request_is_rejected_even_when_proxy_is_local(self) -> None:
        request = SimpleNamespace(
            client=SimpleNamespace(host="127.0.0.1"),
            headers={"x-forwarded-for": "203.0.113.10"},
        )
        with self.assertRaises(HTTPException) as context:
            _require_local_settings_request(request)
        self.assertEqual(context.exception.status_code, 403)

    def test_loopback_get_settings_uses_real_fastapi_route(self) -> None:
        public_settings = {
            "configured": True,
            "app_key_masked": "app*****alue",
            "secret_key_masked": "************",
            "account_no": "1234**7890",
            "env": "real",
            "base_url": "https://api.kiwoom.com",
            "stored_locally": True,
        }
        with patch.object(main, "public_kiwoom_settings", return_value=public_settings):
            status, body = self.client.request("GET", "/api/settings/kiwoom", client_host="127.0.0.1")
        self.assertEqual(status, 200)
        self.assertIn(b"1234**7890", body)
        self.assertNotIn(b"1234567890", body)

    def test_loopback_post_settings_uses_real_fastapi_route(self) -> None:
        saved = Mock()
        fake_provider = Mock(status=Mock(return_value={"provider": "test"}))
        fake_service = object()
        payload = {
            "app_key": "test-app-key",
            "secret_key": "test-secret-key",
            "account_no": "",
            "env": "mock",
            "base_url": "https://mockapi.kiwoom.com/",
        }
        current = Settings("old-app", "old-secret", "1234567890", "mock", "https://mockapi.kiwoom.com")
        with (
            patch.object(main, "get_settings", return_value=current),
            patch.object(main, "save_kiwoom_settings", saved),
            patch.object(main, "DataProvider", return_value=fake_provider),
            patch.object(main, "InvestorRankingService", return_value=fake_service),
            patch.object(main, "public_kiwoom_settings", return_value={"account_no": "1234**7890"}),
        ):
            status, body = self.client.request(
                "POST",
                "/api/settings/kiwoom",
                client_host="::1",
                json_body=payload,
            )
        self.assertEqual(status, 200)
        self.assertEqual(body, b'{"ok":true,"settings":{"account_no":"1234**7890"},"provider":{"provider":"test"}}')
        saved.assert_called_once()
        self.assertEqual(saved.call_args.kwargs["account_no"], "1234567890")
        self.assertEqual(saved.call_args.kwargs["base_url"], "https://mockapi.kiwoom.com")

    def test_loopback_test_auth_uses_real_fastapi_route(self) -> None:
        fake_provider = Mock(test_auth=Mock(return_value={"ok": True, "status": "ok", "message": "test"}))
        with patch.object(main, "provider", fake_provider):
            status, body = self.client.request("POST", "/api/settings/kiwoom/test-auth", client_host="127.0.0.1")
        self.assertEqual(status, 200)
        self.assertIn(b'"ok":true', body)
        fake_provider.test_auth.assert_called_once_with()

    def test_remote_settings_routes_return_403(self) -> None:
        payload = {"app_key": "a", "secret_key": "b", "env": "real", "account_no": ""}
        for method, path, json_body in [
            ("GET", "/api/settings/kiwoom", None),
            ("POST", "/api/settings/kiwoom", payload),
            ("POST", "/api/settings/kiwoom/test-auth", None),
        ]:
            status, _body = self.client.request(method, path, client_host="203.0.113.10", json_body=json_body)
            self.assertEqual(status, 403, path)

    def test_forwarded_settings_routes_return_403(self) -> None:
        payload = {"app_key": "a", "secret_key": "b", "env": "real", "account_no": ""}
        for forwarded_header in ("x-forwarded-for", "forwarded"):
            for method, path, json_body in [
                ("GET", "/api/settings/kiwoom", None),
                ("POST", "/api/settings/kiwoom", payload),
                ("POST", "/api/settings/kiwoom/test-auth", None),
            ]:
                status, _body = self.client.request(
                    method,
                    path,
                    client_host="127.0.0.1",
                    headers={forwarded_header: "203.0.113.10"},
                    json_body=json_body,
                )
                self.assertEqual(status, 403, f"{forwarded_header} {path}")
