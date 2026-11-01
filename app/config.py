"""Runtime configuration, read from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    v = os.environ.get(name)
    try:
        return int(v) if v not in (None, "") else default
    except ValueError:
        return default


@dataclass
class Settings:
    web_dir: str = field(default_factory=lambda: os.environ.get(
        "WEB_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")))
    data_dir: str = field(default_factory=lambda: os.environ.get("DATA_DIR", "/data"))
    track17_api_key: str = field(default_factory=lambda: os.environ.get("TRACK17_API_KEY", "").strip())
    track17_base_url: str = field(default_factory=lambda: os.environ.get("TRACK17_BASE_URL", "https://api.17track.net/track/v2.2/"))
    admin_username: str = field(default_factory=lambda: os.environ.get("ADMIN_USERNAME", "").strip())
    admin_password: str = field(default_factory=lambda: os.environ.get("ADMIN_PASSWORD", ""))
    poll_interval_minutes: int = field(default_factory=lambda: max(5, _int("POLL_INTERVAL_MINUTES", 60)))
    allow_signup: bool = field(default_factory=lambda: _bool("ALLOW_SIGNUP", False))
    # Defaults for settings an admin can also change at runtime (stored in the DB).
    auto_archive_days: int = field(default_factory=lambda: _int("AUTO_ARCHIVE_DAYS", 7))
    require_approval: bool = field(default_factory=lambda: _bool("REQUIRE_APPROVAL", False))
    monthly_new_limit: int = field(default_factory=lambda: _int("MONTHLY_NEW_NUMBERS_PER_USER", 0))  # 0 = unlimited
    retry_unsupported_hours: int = field(default_factory=lambda: _int("RETRY_UNSUPPORTED_HOURS", 24))
    session_days: int = field(default_factory=lambda: _int("SESSION_DAYS", 30))
    refresh_cooldown_seconds: int = field(default_factory=lambda: _int("REFRESH_COOLDOWN_SECONDS", 60))
    # Safety switch: never call 17TRACK "register" (no quota can be used at all).
    disable_registration: bool = field(default_factory=lambda: _bool("DISABLE_REGISTRATION", False))
    enable_poller: bool = field(default_factory=lambda: _bool("ENABLE_POLLER", True))

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "packagebuddy.sqlite3")


settings = Settings()


def reload_settings() -> Settings:
    global settings
    settings = Settings()
    return settings
