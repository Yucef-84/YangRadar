from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"
KIWOOM_ENV_KEYS = [
    "KIWOOM_APP_KEY",
    "KIWOOM_SECRET_KEY",
    "KIWOOM_ACCOUNT_NO",
    "KIWOOM_ENV",
    "KIWOOM_BASE_URL",
]

KIWOOM_BASE_URLS = {
    "real": "https://api.kiwoom.com",
    "mock": "https://mockapi.kiwoom.com",
}


def read_dotenv(path: Path | None = None) -> dict[str, str]:
    env_path = path or ENV_PATH
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_dotenv(path: Path | None = None) -> None:
    for key, value in read_dotenv(path).items():
        os.environ.setdefault(key, value)


def save_kiwoom_settings(
    *,
    app_key: str,
    secret_key: str,
    account_no: str = "",
    env: str = "real",
    base_url: str = "",
    path: Path | None = None,
) -> None:
    env_path = path or ENV_PATH
    normalized_env = env.strip().lower() or "real"
    normalized_base_url = normalize_kiwoom_base_url(normalized_env, base_url)
    existing = read_dotenv(env_path)
    existing.update(
        {
            "KIWOOM_APP_KEY": app_key.strip(),
            "KIWOOM_SECRET_KEY": secret_key.strip(),
            "KIWOOM_ACCOUNT_NO": account_no.strip(),
            "KIWOOM_ENV": normalized_env,
        }
    )
    existing["KIWOOM_BASE_URL"] = normalized_base_url

    lines = [
        "# Kiwoom REST API settings.",
        "# Saved locally by YangRadar. Do not commit this file.",
    ]
    for key in KIWOOM_ENV_KEYS:
        if key in existing:
            lines.append(f"{key}={existing[key]}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class Settings:
    kiwoom_app_key: str
    kiwoom_secret_key: str
    kiwoom_account_no: str
    kiwoom_env: str
    kiwoom_base_url: str

    @property
    def kiwoom_configured(self) -> bool:
        return bool(self.kiwoom_app_key and self.kiwoom_secret_key)


def get_settings() -> Settings:
    file_values = read_dotenv()

    def value(key: str, default: str = "") -> str:
        return os.getenv(key, file_values.get(key, default)).strip()

    env = value("KIWOOM_ENV", "real").lower()
    if env not in KIWOOM_BASE_URLS:
        env = "real"
    default_base_url = KIWOOM_BASE_URLS[env]
    configured_base_url = value("KIWOOM_BASE_URL")
    try:
        safe_base_url = normalize_kiwoom_base_url(env, configured_base_url or default_base_url)
    except ValueError:
        safe_base_url = default_base_url
    return Settings(
        kiwoom_app_key=value("KIWOOM_APP_KEY"),
        kiwoom_secret_key=value("KIWOOM_SECRET_KEY"),
        kiwoom_account_no=value("KIWOOM_ACCOUNT_NO"),
        kiwoom_env=env,
        kiwoom_base_url=safe_base_url,
    )


def normalize_kiwoom_base_url(env: str, base_url: str = "") -> str:
    """Return only an official Kiwoom host for the selected environment."""
    normalized_env = env.strip().lower() or "real"
    if normalized_env not in KIWOOM_BASE_URLS:
        raise ValueError("KIWOOM_ENV는 real 또는 mock이어야 합니다.")
    candidate = base_url.strip().rstrip("/")
    if not candidate:
        return KIWOOM_BASE_URLS[normalized_env]
    if candidate != KIWOOM_BASE_URLS[normalized_env]:
        raise ValueError("KIWOOM_BASE_URL은 선택한 환경의 공식 Kiwoom 주소만 사용할 수 있습니다.")
    return candidate


def public_kiwoom_settings() -> dict[str, str | bool]:
    settings = get_settings()
    return {
        "configured": settings.kiwoom_configured,
        "app_key_masked": _mask(settings.kiwoom_app_key),
        "secret_key_masked": _mask(settings.kiwoom_secret_key),
        "account_no": _mask(settings.kiwoom_account_no),
        "env": settings.kiwoom_env,
        "base_url": settings.kiwoom_base_url,
        "stored_locally": ENV_PATH.exists(),
    }


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"

