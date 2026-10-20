"""Quote age, reference skew, and game-state checks (docs/ARCHITECTURE.md section 5, "freshness.py").

Thresholds are inclusive: a quote exactly ``max_age_s`` seconds old is still fresh, and a reference exactly
``max_skew_s`` seconds apart from the target is still comparable. Source timestamps are the provider's own
update times; the local ``received_at_utc`` is never used as a substitute, so a quote without a source
timestamp reports ``SOURCE_TIMESTAMP_UNKNOWN`` rather than pretending to be fresh.
"""

from __future__ import annotations

from datetime import datetime

from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import Settings

__all__ = [
    "BLOCKING_REASON_CODES",
    "WAIT_REASON_CODES",
    "check_event_not_started",
    "check_quote_age",
    "check_reference_skew",
    "decision_for",
    "is_usable",
    "revalidation_reasons",
]

# Codes that make a leg unusable right now (docs/ARCHITECTURE.md section 7).
BLOCKING_REASON_CODES: frozenset[str] = frozenset(
    {
        "QUOTE_STALE",
        "GAME_STARTED",
        "GAME_POSTPONED",
        "GAME_CANCELLED",
        "MARKET_SUSPENDED",
        "INJURY_OUT",
        "INJURY_DOUBTFUL",
        "PERIOD_UNSUPPORTED",
        "WRONG_BOOK",
        "WRONG_LEAGUE",
        "WRONG_JURISDICTION",
        "EVENT_UNMATCHED",
        "PLAYER_UNMATCHED",
        "TEAM_UNMATCHED",
        "BOOK_NOT_AVAILABLE",
        "MARKET_NOT_OFFERED",
        "NOT_THREE_LEGS",
        "DUPLICATE_SELECTION",
        "CONTRADICTORY_SELECTION",
        "NESTED_SELECTION",
        "MUTUALLY_EXCLUSIVE_SELECTION",
    }
)

# Codes that mean "not yet": the leg may become usable after a refresh.
WAIT_REASON_CODES: frozenset[str] = frozenset({"INJURY_QUESTIONABLE_MATERIAL", "WAIT_FOR_UPDATE"})


def _ensure_aware(dt: datetime, label: str) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{label} must be timezone-aware")
    return dt


def check_quote_age(quote: S.MarketQuote, now: datetime, max_age_s: int) -> list[str]:
    """``[QUOTE_STALE]`` when the source timestamp is older than ``max_age_s``; ``[SOURCE_TIMESTAMP_UNKNOWN]`` when absent."""
    _ensure_aware(now, "now")
    ts = quote.stamp.source_timestamp_utc
    if ts is None:
        return ["SOURCE_TIMESTAMP_UNKNOWN"]
    age = (now - ts).total_seconds()
    return ["QUOTE_STALE"] if age > max_age_s else []


def check_reference_skew(target: S.MarketQuote, ref: S.ReferenceTwoWay, max_skew_s: int) -> list[str]:
    """``[TIMESTAMP_SKEW]`` when target and reference source timestamps differ by more than ``max_skew_s``."""
    t_ts = target.stamp.source_timestamp_utc
    r_ts = ref.stamp.source_timestamp_utc
    if t_ts is None or r_ts is None:
        return ["SOURCE_TIMESTAMP_UNKNOWN"]
    skew = abs((t_ts - r_ts).total_seconds())
    return ["TIMESTAMP_SKEW"] if skew > max_skew_s else []


def check_event_not_started(event: S.Event, now: datetime) -> list[str]:
    """``[GAME_POSTPONED]`` / ``[GAME_CANCELLED]`` by status, ``[GAME_STARTED]`` once tip-off has passed (or status says so)."""
    _ensure_aware(now, "now")
    if event.status == S.EventStatus.POSTPONED:
        return ["GAME_POSTPONED"]
    if event.status == S.EventStatus.CANCELLED:
        return ["GAME_CANCELLED"]
    if event.status in (S.EventStatus.LIVE, S.EventStatus.FINAL) or event.commence_time_utc <= now:
        return ["GAME_STARTED"]
    return []


def revalidation_reasons(
    selection: S.Selection,
    ref: S.ReferenceTwoWay | None,
    now: datetime,
    settings: Settings,
) -> list[str]:
    """Every freshness/game-state reason for a leg at ``now`` (deduplicated, stable order).

    Includes REFERENCE_MISSING when no reference pair was supplied so callers can see the comparison gap.
    """
    codes: list[str] = []
    codes += check_event_not_started(selection.event, now)
    codes += check_quote_age(selection.quote, now, settings.max_odds_age_seconds)
    if ref is None:
        codes.append("REFERENCE_MISSING")
    else:
        codes += check_reference_skew(selection.quote, ref, settings.max_reference_skew_seconds)
        ref_ts = ref.stamp.source_timestamp_utc
        if ref_ts is not None and (now - ref_ts).total_seconds() > settings.max_odds_age_seconds:
            codes.append("QUOTE_STALE")
    seen: set[str] = set()
    ordered: list[str] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            ordered.append(code)
    return ordered


def is_usable(reason_codes: list[str]) -> bool:
    """True when no blocking and no wait-for-update code is present."""
    return not any(code in BLOCKING_REASON_CODES or code in WAIT_REASON_CODES for code in reason_codes)


def decision_for(reason_codes: list[str]) -> S.LegDecision:
    """Map reason codes to a leg decision: blocking -> UNUSABLE, wait codes -> WAIT_FOR_UPDATE, else USABLE."""
    if any(code in BLOCKING_REASON_CODES for code in reason_codes):
        return S.LegDecision.UNUSABLE
    if any(code in WAIT_REASON_CODES for code in reason_codes):
        return S.LegDecision.WAIT_FOR_UPDATE
    return S.LegDecision.USABLE
