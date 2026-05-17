from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


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
    load_dotenv()
    env = os.getenv("KIWOOM_ENV", "real").strip().lower()
    default_base_url = "https://mockapi.kiwoom.com" if env == "mock" else "https://api.kiwoom.com"
    return Settings(
        kiwoom_app_key=os.getenv("KIWOOM_APP_KEY", "").strip(),
        kiwoom_secret_key=os.getenv("KIWOOM_SECRET_KEY", "").strip(),
        kiwoom_account_no=os.getenv("KIWOOM_ACCOUNT_NO", "").strip(),
        kiwoom_env=env,
        kiwoom_base_url=os.getenv("KIWOOM_BASE_URL", default_base_url).strip().rstrip("/"),
    )

