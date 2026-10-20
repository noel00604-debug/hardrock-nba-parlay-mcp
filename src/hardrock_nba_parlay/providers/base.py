"""Provider protocols and the shared result envelope (docs/ARCHITECTURE.md section 5, "providers").

Every provider returns a ``ProviderResult`` so callers always see the provenance stamp, the credit cost,
the quota headers, and any warnings next to the data. ``ProviderError`` is re-exported from
``errors.py`` so provider callers can import everything they need from this module.

Two small helpers shared by the providers also live here: ``validate_local_date`` (so a malformed
``date_local`` becomes ``InvalidInput`` instead of a raw ``ValueError``) and ``install_http_log_redaction``
(so the ``httpx``/``httpcore`` request logs never carry an ``apiKey`` query parameter; ARCHITECTURE section 0:
"HTTP client logs must strip apiKey").
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import redact
from hardrock_nba_parlay.errors import InvalidInput, ProviderError

__all__ = [
    "HTTP_CLIENT_LOGGERS",
    "ApiKeyLogFilter",
    "GameResultsProvider",
    "InjuryProvider",
    "OddsProvider",
    "ProviderError",
    "ProviderResult",
    "empty_quota",
    "install_http_log_redaction",
    "strip_api_key",
    "validate_local_date",
]

# Loggers used by the HTTP client library. httpx logs "HTTP Request: GET <full url> ..." at INFO on "httpx";
# httpcore logs connection traces at DEBUG on "httpcore" and its children.
HTTP_CLIENT_LOGGERS: tuple[str, ...] = (
    "httpx",
    "httpcore",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.connection",
    "httpcore.proxy",
)

_API_KEY_PARAM = re.compile(r"([?&])apiKey=[^&\s\"'>]*(&?)", re.IGNORECASE)


def empty_quota() -> dict[str, int | None]:
    """The quota dictionary shape used everywhere (None means the provider did not say)."""
    return {"requests_remaining": None, "requests_used": None, "requests_last": None}


def validate_local_date(date_local: str) -> str:
    """Return ``date_local`` when it is a real ``YYYY-MM-DD`` calendar date; raise ``InvalidInput`` otherwise.

    ``schemas.LocalDate`` only checks the digit pattern, so "2026-13-45" or "2026-02-30" can reach a provider.
    """
    text = (date_local or "").strip()
    try:
        parsed = date.fromisoformat(text)
    except (TypeError, ValueError):
        raise InvalidInput(
            f"date_local {date_local!r} is not a valid YYYY-MM-DD date", ["INVALID_INPUT"]
        ) from None
    if parsed.isoformat() != text:
        raise InvalidInput(f"date_local {date_local!r} must be written as YYYY-MM-DD", ["INVALID_INPUT"])
    return text


def strip_api_key(text: str, secrets: list[str] | None = None) -> str:
    """Remove every ``apiKey=<value>`` query parameter from ``text`` and mask any known secret values."""
    out = _API_KEY_PARAM.sub(lambda m: m.group(1) if m.group(2) else "", text)
    return redact(out, [s for s in (secrets or []) if s])


class ApiKeyLogFilter(logging.Filter):
    """Rewrites a log record in place so the formatted message carries no ``apiKey`` parameter or known key.

    Installed on the HTTP client loggers by ``install_http_log_redaction``; it rewrites ``record.msg`` and clears
    ``record.args`` so every handler (including ``caplog`` in tests) sees the stripped text.
    """

    def __init__(self) -> None:
        super().__init__(name="")
        self._secrets: set[str] = set()

    def add_secret(self, value: str | None) -> None:
        if value and len(value) >= 6:
            self._secrets.add(value)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed record; never let logging raise
            message = str(record.msg)
        record.msg = strip_api_key(message, sorted(self._secrets))
        record.args = ()
        return True


def install_http_log_redaction(secret: str | None = None) -> ApiKeyLogFilter:
    """Ensure one ``ApiKeyLogFilter`` is attached to each HTTP client logger and register ``secret`` with it.

    Idempotent: repeated calls (one per provider instance) reuse the same filter and only add the key value.
    """
    existing: ApiKeyLogFilter | None = None
    for name in HTTP_CLIENT_LOGGERS:
        for f in logging.getLogger(name).filters:
            if isinstance(f, ApiKeyLogFilter):
                existing = f
                break
        if existing is not None:
            break
    shared = existing or ApiKeyLogFilter()
    for name in HTTP_CLIENT_LOGGERS:
        target = logging.getLogger(name)
        if not any(isinstance(f, ApiKeyLogFilter) for f in target.filters):
            target.addFilter(shared)
    shared.add_secret(secret)
    return shared


@dataclass(slots=True)
class ProviderResult[T]:
    """Data plus provenance for one provider call.

    ``credits_cost`` is the documented usage-credit cost of the call (0 for free endpoints, 0 again when the
    data was served from the in-process cache and no request was made, None when the provider has no credit
    concept). ``warnings`` are human-readable notes; ``reason_codes`` carry the machine-readable codes from
    docs/ARCHITECTURE.md section 7 (for example ``BOOK_NOT_AVAILABLE``). ``cached`` is True when the data came
    from the in-process cache; the stamps then keep the receipt time of the original request.
    """

    data: T
    stamp: S.SourceStamp
    credits_cost: int | None = None
    quota: dict[str, int | None] = field(default_factory=empty_quota)
    warnings: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    cached: bool = False

    @property
    def data_mode(self) -> S.DataMode:
        return self.stamp.data_mode


@runtime_checkable
class OddsProvider(Protocol):
    """Pre-match odds for NBA events from one upstream source."""

    name: str

    def list_events(self, date_local: str) -> ProviderResult[list[S.Event]]: ...

    def fetch_featured_odds(
        self, date_local: str, books: list[str], markets: list[S.MarketType]
    ) -> ProviderResult[list[S.MarketQuote]]: ...

    def fetch_event_props(
        self, event_id: str, books: list[str], markets: list[S.MarketType], include_alternates: bool
    ) -> ProviderResult[list[S.MarketQuote]]: ...

    def fetch_scores(self, days_from: int | None) -> ProviderResult[list[S.GameResult]]: ...

    def probe(self, spend_credits: bool = False) -> S.ProviderProbe: ...


@runtime_checkable
class GameResultsProvider(Protocol):
    """Final team scores for settlement of team legs."""

    name: str

    def fetch_scores(self, days_from: int | None) -> ProviderResult[list[S.GameResult]]: ...


@runtime_checkable
class InjuryProvider(Protocol):
    """Official participation/injury designations for a slate."""

    name: str

    def fetch_latest_report(
        self, now: datetime, slate: list[S.Event]
    ) -> ProviderResult[list[S.InjuryContext]]: ...
