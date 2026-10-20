"""Settings, clock, time-zone helpers, secret lookup, and log redaction (docs/ARCHITECTURE.md section 2)."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

try:
    from importlib.metadata import version as _pkg_version

    APP_VERSION = _pkg_version("hardrock-nba-parlay-mcp")
except Exception:  # pragma: no cover - source checkout without install
    APP_VERSION = "0.1.0"

DEFAULT_DATA_DIR = Path.home() / ".hardrock-nba-parlay"
DEFAULT_TZ = "America/New_York"
KEYCHAIN_SERVICE = "hardrock-nba-parlay"


class Settings(BaseSettings):
    """All runtime configuration. Environment variables use the HRNBA_ prefix (e.g. HRNBA_ODDS_API_KEY)."""

    model_config = SettingsConfigDict(
        env_prefix="HRNBA_",
        env_file=(str(DEFAULT_DATA_DIR / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "hardrock-nba-parlay-mcp"
    version: str = APP_VERSION
    data_dir: Path = DEFAULT_DATA_DIR
    database_url: str | None = Field(default=None, description="SQLAlchemy URL; default sqlite in data_dir")
    display_tz: str = DEFAULT_TZ
    local_user_id: str = Field(
        default="local-owner", description="Used only when auth_mode == none (stdio/CLI)"
    )
    auth_mode: Literal["none", "builtin_oauth", "external_jwt"] = "none"
    data_mode: Literal["live", "fixture"] = Field(
        default="live",
        description="fixture = offline demo slate clearly labelled FIXTURE; never writes to a real ledger",
    )
    public_url: str | None = Field(
        default=None, description="https base URL of the hosted server (issuer + resource)"
    )
    secret_key: SecretStr | None = Field(
        default=None, description="Cookie/session signing and per-user key encryption (hosted)"
    )
    odds_api_key: SecretStr | None = Field(
        default=None, description="Server-wide The Odds API key; per-user keys override"
    )
    odds_api_base_url: str = "https://api.the-odds-api.com/v4"
    target_book: str = "hardrockbet_fl"
    target_jurisdiction: str = "US-FL"
    reference_books: list[str] = Field(default_factory=lambda: ["pinnacle"])
    prop_reference_books: list[str] = Field(default_factory=lambda: ["pinnacle", "draftkings", "fanduel"])
    daily_cap_usd_default: Decimal = Decimal("10.00")
    max_odds_age_seconds: int = 180
    max_reference_skew_seconds: int = 60
    injury_report_max_age_seconds: int = 6 * 3600
    reservation_ttl_seconds: int = 2 * 3600
    http_timeout_seconds: float = 15.0
    http_max_retries: int = 3
    provider_cache_ttl_seconds: int = 60
    daily_provider_credit_budget: int = Field(
        default=60,
        description="App-wide guard on The Odds API credits per ET day; the free Starter plan is 500/month (about 16/day), the 20K plan about 650/day",
    )
    per_user_daily_credit_quota: int = Field(
        default=30,
        description="Hosted mode: max provider credits one user may consume per ET day on the server-wide key",
    )
    injury_auto_fetch: bool = Field(
        default=True,
        description="Fetch the official NBA injury-report PDF automatically; manual entry always remains available",
    )
    http_json_response: bool = Field(
        default=False,
        description="Streamable HTTP: answer each POST with a single JSON body instead of SSE (needed behind tunnels that cannot stream)",
    )
    review_window_start: date = date(2026, 10, 20)
    review_window_end: date = date(2026, 11, 18)
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    allow_fixture_ledger: bool = Field(
        default=False, description="Tests only: permit FIXTURE-mode records in the ledger"
    )

    @field_validator("daily_cap_usd_default")
    @classmethod
    def _cap_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("daily cap must be positive")
        return value.quantize(Decimal("0.01"))

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(self.data_dir / 'local.db').resolve()}"

    @property
    def database_kind(self) -> str:
        url = self.effective_database_url
        return (
            "postgresql" if url.startswith("postgres") else "sqlite" if url.startswith("sqlite") else "other"
        )

    def odds_api_key_value(self) -> str | None:
        if self.odds_api_key is not None and self.odds_api_key.get_secret_value():
            return self.odds_api_key.get_secret_value()
        return get_secret("ODDS_API_KEY")

    def secret_values(self) -> list[str]:
        values: list[str] = []
        for s in (self.odds_api_key, self.secret_key):
            if s is not None and s.get_secret_value():
                values.append(s.get_secret_value())
        return values


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()


# --------------------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------------------


class Clock(Protocol):
    def now_utc(self) -> datetime: ...


class SystemClock:
    def now_utc(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """Deterministic clock for tests; `advance` moves it forward."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FixedClock requires an aware datetime")
        self._at = at.astimezone(UTC)

    def now_utc(self) -> datetime:
        return self._at

    def set(self, at: datetime) -> None:
        self._at = at.astimezone(UTC)

    def advance(self, seconds: float) -> None:
        self._at = self._at + timedelta(seconds=seconds)


# --------------------------------------------------------------------------------------
# Time helpers (store UTC, display America/New_York with offset; DST-safe via zoneinfo)
# --------------------------------------------------------------------------------------


def tz(name: str = DEFAULT_TZ) -> ZoneInfo:
    return ZoneInfo(name)


def local_date(dt_utc: datetime, tz_name: str = DEFAULT_TZ) -> str:
    if dt_utc.tzinfo is None:
        raise ValueError("naive datetime")
    return dt_utc.astimezone(tz(tz_name)).date().isoformat()


def local_day_bounds_utc(date_local: str, tz_name: str = DEFAULT_TZ) -> tuple[datetime, datetime]:
    """[start, end) of the local calendar day in UTC. Handles DST transitions (e.g. 2026-11-01 is 25 hours)."""
    d = date.fromisoformat(date_local)
    zone = tz(tz_name)
    start = datetime(d.year, d.month, d.day, tzinfo=zone)
    end = datetime.combine(d + timedelta(days=1), datetime.min.time(), tzinfo=zone)
    return start.astimezone(UTC), end.astimezone(UTC)


def to_display(dt_utc: datetime, tz_name: str = DEFAULT_TZ) -> str:
    if dt_utc.tzinfo is None:
        raise ValueError("naive datetime")
    return dt_utc.astimezone(tz(tz_name)).isoformat(timespec="seconds")


def today_local(clock: Clock, tz_name: str = DEFAULT_TZ) -> str:
    return local_date(clock.now_utc(), tz_name)


# --------------------------------------------------------------------------------------
# Secrets
# --------------------------------------------------------------------------------------


def _keychain_lookup(name: str) -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = out.stdout.strip()
    return value or None


def _dotenv_lookup(name: str) -> str | None:
    for path in (DEFAULT_DATA_DIR / ".env", Path(".env")):
        try:
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                if key in (name, f"HRNBA_{name}"):
                    val = val.strip().strip('"').strip("'")
                    if val:
                        return val
        except OSError:
            continue
    return None


def get_secret(name: str) -> str | None:
    """Resolve a secret by NAME: env HRNBA_<NAME> or <NAME> -> dotenv files -> macOS keychain. Never logs the value."""
    for env_name in (f"HRNBA_{name}", name):
        val = os.environ.get(env_name)
        if val:
            return val
    val = _dotenv_lookup(name)
    if val:
        return val
    return _keychain_lookup(name)


# --------------------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------------------

_REDACT_PATTERNS = [
    re.compile(r"(apiKey=)[^&\s'\"]+", re.IGNORECASE),
    re.compile(r"(api_key=)[^&\s'\"]+", re.IGNORECASE),
    re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
    re.compile(r"(token=)[^&\s'\"]+", re.IGNORECASE),
    re.compile(r"(client_secret=)[^&\s'\"]+", re.IGNORECASE),
    re.compile(r"(password=)[^&\s'\"]+", re.IGNORECASE),
]


def redact(text: str, extra_secrets: list[str] | None = None) -> str:
    out = text
    for pat in _REDACT_PATTERNS:
        out = pat.sub(r"\1[REDACTED]", out)
    secrets: list[str] = list(extra_secrets or [])
    try:
        secrets.extend(get_settings().secret_values())
    except Exception:
        pass
    for s in secrets:
        if s and len(s) >= 6:
            out = out.replace(s, "[REDACTED]")
    return out


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging(level: str | None = None) -> None:
    lvl = (level or get_settings().log_level).upper()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(lvl)
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def mask_user_id(user_id: str) -> str:
    if len(user_id) <= 6:
        return user_id[:2] + "***"
    return user_id[:4] + "***" + user_id[-2:]
