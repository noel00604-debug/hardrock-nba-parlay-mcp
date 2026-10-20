"""Official NBA injury report: slot URLs, fetching, PDF/text parsing (docs/research/nba-schedule-injuries.md).

Facts from the research note that this module encodes:

- PDFs are published at ``https://ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_HH_MM{AM,PM}.pdf``
  in 15-minute slots on a zero-padded 12-hour clock (``_12_00AM``, ``_06_45PM``); the date is the report's ET date.
- Missing slots answer HTTP 403 on that host (404 is handled the same way).
- The PDF header reads ``Injury Report: MM/DD/YY HH:MM AM/PM`` (ET). Columns: Game Date, Game Time, Matchup
  (AWAY@HOME), Team, Player Name ("Last, First"), Current Status, Reason. The team label prints only on a team's
  first row, long reasons wrap onto a following line, and a team that has not filed shows ``NOT YET SUBMITTED``.
- Status vocabulary in use: Out, Doubtful, Questionable, Probable, Available.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import Clock, local_date, tz
from hardrock_nba_parlay.errors import InvalidInput, ProviderError
from hardrock_nba_parlay.normalization import canonical_player, try_canonical_team
from hardrock_nba_parlay.providers.base import ProviderResult, empty_quota, validate_local_date

__all__ = [
    "BASE_URL",
    "NbaInjuryReportProvider",
    "ParsedInjuryReport",
    "fetch_injury_report",
    "fetch_latest_report",
    "manual_injury_entries",
    "parse_injury_report_pdf",
    "parse_injury_report_text",
    "report_slots",
    "slot_url",
]

logger = logging.getLogger(__name__)

BASE_URL = "https://ak-static.cms.nba.com/referee/injury/"
SOURCE_NAME = "nba-official-injury-report"
NOT_YET_SUBMITTED = "NOT YET SUBMITTED"
SLOT_MINUTES = 15
DEFAULT_MAX_CONSECUTIVE_MISSES = 8
ET = "America/New_York"

_STATUS_WORDS: dict[str, S.InjuryDesignation] = {
    "out": S.InjuryDesignation.OUT,
    "doubtful": S.InjuryDesignation.DOUBTFUL,
    "questionable": S.InjuryDesignation.QUESTIONABLE,
    "probable": S.InjuryDesignation.PROBABLE,
    "available": S.InjuryDesignation.AVAILABLE,
}
_HEADER_RE = re.compile(
    r"Injury Report:\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s+(\d{1,2}):(\d{2})\s*(AM|PM)", re.IGNORECASE
)
_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}\s*\(ET\)$", re.IGNORECASE)
_MATCHUP_RE = re.compile(r"^([A-Z]{2,4})@([A-Z]{2,4})$")
_PAGE_RE = re.compile(r"^Page \d+ of \d+$", re.IGNORECASE)
_SPLIT_RE = re.compile(r"\s{2,}")


# --------------------------------------------------------------------------------------
# Slot URLs
# --------------------------------------------------------------------------------------


def slot_url(slot_et: datetime) -> str:
    """URL for one 15-minute slot given an ET-aware datetime (zero-padded 12-hour clock)."""
    hour12 = slot_et.hour % 12 or 12
    ampm = "AM" if slot_et.hour < 12 else "PM"
    return f"{BASE_URL}Injury-Report_{slot_et:%Y-%m-%d}_{hour12:02d}_{slot_et.minute:02d}{ampm}.pdf"


def report_slots(date_local_et: str, now: datetime, lookback_hours: int = 36) -> list[str]:
    """Candidate report URLs, newest first, for the slate date ``date_local_et``.

    Slots start at the latest 15-minute boundary not after ``now`` (and not after the end of the slate's ET day
    when looking back at a past date) and run back ``lookback_hours``. Example: 19:07 ET on 2026-10-19 gives
    ``..._2026-10-19_07_00PM.pdf`` first. A malformed ``date_local_et`` raises ``InvalidInput`` (INVALID_INPUT).
    """
    if now.tzinfo is None:
        raise InvalidInput("now must be timezone-aware", ["INVALID_INPUT"])
    zone = tz(ET)
    now_et = now.astimezone(zone)
    slate_day = date.fromisoformat(validate_local_date(date_local_et))
    day = datetime(slate_day.year, slate_day.month, slate_day.day, tzinfo=zone)
    end_of_day = (day + timedelta(days=1)).replace(tzinfo=None)
    end_of_day = datetime(end_of_day.year, end_of_day.month, end_of_day.day, tzinfo=zone) - timedelta(
        minutes=SLOT_MINUTES
    )
    latest = min(now_et, end_of_day)
    floored_minute = (latest.minute // SLOT_MINUTES) * SLOT_MINUTES
    slot = latest.replace(minute=floored_minute, second=0, microsecond=0)
    stop = slot - timedelta(hours=lookback_hours)
    urls: list[str] = []
    while slot > stop:
        urls.append(slot_url(slot))
        # step in UTC so the DST fall-back hour does not loop; re-localise for the filename
        slot = (slot.astimezone(UTC) - timedelta(minutes=SLOT_MINUTES)).astimezone(zone)
    # The filename carries no UTC offset, so the repeated 1 AM hour on the DST fall-back day yields the
    # same name twice; keep the first (newest) occurrence only.
    return list(dict.fromkeys(urls))


# --------------------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------------------


class ParsedInjuryReport:
    """Rows parsed from one report plus its header timestamp."""

    def __init__(
        self, report_timestamp_utc: datetime | None, rows: list[dict[str, Any]], warnings: list[str]
    ) -> None:
        self.report_timestamp_utc = report_timestamp_utc
        self.rows = rows
        self.warnings = warnings


def _header_timestamp(line: str) -> datetime | None:
    m = _HEADER_RE.search(line)
    if not m:
        return None
    month, day, year, hour, minute, ampm = m.groups()
    y = int(year)
    if y < 100:
        y += 2000
    h = int(hour) % 12 + (12 if ampm.upper() == "PM" else 0)
    local = datetime(y, int(month), int(day), h, int(minute), tzinfo=tz(ET))
    return local.astimezone(UTC)


def _is_team_label(token: str) -> bool:
    team = try_canonical_team(token)
    if team is None:
        return False
    # Only full franchise names count as a team label; nicknames alone could be a wrapped reason word.
    return token.strip().lower() == team.name.lower()


def _parse_rows(text: str) -> ParsedInjuryReport:
    report_ts: datetime | None = None
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    game_date: str | None = None
    game_time: str | None = None
    matchup: str | None = None
    team: str | None = None
    last_row: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or _PAGE_RE.match(line):
            continue
        if report_ts is None:
            ts = _header_timestamp(line)
            if ts is not None:
                report_ts = ts
                continue
        elif _HEADER_RE.search(line):
            continue
        if line.startswith("Game Date") or (line.startswith("Game") and "Player Name" in line):
            continue
        tokens = [t.strip() for t in _SPLIT_RE.split(line) if t.strip()]
        player: str | None = None
        status: S.InjuryDesignation | None = None
        reason_parts: list[str] = []
        recognised = False
        idx = 0
        while idx < len(tokens):
            tok = tokens[idx]
            if status is not None:
                reason_parts.append(tok)
            elif _DATE_RE.match(tok):
                game_date, recognised = tok, True
            elif _TIME_RE.match(tok):
                game_time, recognised = tok, True
            elif _MATCHUP_RE.match(tok):
                matchup, recognised = tok, True
            elif tok.upper() == NOT_YET_SUBMITTED:
                player, recognised = NOT_YET_SUBMITTED, True
            elif tok.lower() in _STATUS_WORDS and player is not None:
                status, recognised = _STATUS_WORDS[tok.lower()], True
            elif "," in tok and player is None:
                player, recognised = tok, True
            elif _is_team_label(tok):
                team, recognised = tok, True
            elif player is not None and status is None and tok.lower() in _STATUS_WORDS:
                status, recognised = _STATUS_WORDS[tok.lower()], True
            elif not recognised and last_row is not None and player is None:
                # wrapped reason continuation
                last_row["reason"] = f"{last_row['reason']} {tok}".strip() if last_row.get("reason") else tok
                recognised = True
            else:
                reason_parts.append(tok)
            idx += 1
        if player is None:
            continue
        if player != NOT_YET_SUBMITTED and status is None:
            warnings.append(f"row for {player!r} has no recognised status; recorded as UNKNOWN")
        row = {
            "game_date": game_date,
            "game_time": game_time,
            "matchup": matchup,
            "team": team,
            "player": player,
            "status": status,
            "reason": " ".join(reason_parts).strip() or None,
        }
        rows.append(row)
        last_row = row
    return ParsedInjuryReport(report_ts, rows, warnings)


def _match_event(matchup: str | None, game_date: str | None, slate: list[S.Event] | None) -> str:
    unmatched = f"unmatched:{matchup or 'unknown'}"
    if not matchup or not slate:
        return unmatched
    m = _MATCHUP_RE.match(matchup)
    if not m:
        return unmatched
    away = try_canonical_team(m.group(1))
    home = try_canonical_team(m.group(2))
    if away is None or home is None:
        return unmatched
    date_iso: str | None = None
    if game_date:
        try:
            date_iso = datetime.strptime(game_date, "%m/%d/%Y").date().isoformat()
        except ValueError:
            date_iso = None
    for event in slate:
        if event.home_team.team_id != home.team_id or event.away_team.team_id != away.team_id:
            continue
        if date_iso is not None and local_date(event.commence_time_utc, ET) != date_iso:
            continue
        return event.event_id
    return unmatched


def _rows_to_context(
    parsed: ParsedInjuryReport,
    now: datetime,
    slate: list[S.Event] | None,
    source_url: str | None,
    data_mode: S.DataMode = S.DataMode.LIVE_PROVIDER,
    source: str = SOURCE_NAME,
) -> list[S.InjuryContext]:
    out: list[S.InjuryContext] = []
    for row in parsed.rows:
        team = try_canonical_team(row["team"]) if row.get("team") else None
        event_id = _match_event(row.get("matchup"), row.get("game_date"), slate)
        stamp = S.SourceStamp(
            source=source,
            source_url=source_url,
            source_record_id=None,
            source_timestamp_utc=parsed.report_timestamp_utc,
            received_at_utc=now,
            data_mode=data_mode,
        )
        if row["player"] == NOT_YET_SUBMITTED:
            out.append(
                S.InjuryContext(
                    event_id=event_id,
                    team_id=team.team_id if team else None,
                    player_id=None,
                    player_name_raw=NOT_YET_SUBMITTED,
                    designation=S.InjuryDesignation.UNKNOWN,
                    reason=None,
                    report_timestamp_utc=parsed.report_timestamp_utc,
                    stamp=stamp,
                    note=f"{row.get('team') or 'team'} had not submitted its report at this timestamp",
                )
            )
            continue
        player = canonical_player(row["player"], team)
        designation = row["status"] or S.InjuryDesignation.UNKNOWN
        out.append(
            S.InjuryContext(
                event_id=event_id,
                team_id=team.team_id if team else None,
                player_id=player.player_id,
                player_name_raw=player.name,
                designation=designation,
                reason=row.get("reason"),
                report_timestamp_utc=parsed.report_timestamp_utc,
                stamp=stamp,
                note=None if row["status"] is not None else "status text not recognised",
            )
        )
    return out


def parse_injury_report_text(
    text: str,
    now: datetime,
    slate: list[S.Event] | None = None,
    source_url: str | None = None,
) -> list[S.InjuryContext]:
    """Parse the layout text of an injury report (as produced by ``pdftotext -layout`` or pypdf layout mode)."""
    parsed = _parse_rows(text)
    if parsed.report_timestamp_utc is None:
        logger.warning("injury report text has no 'Injury Report: MM/DD/YY HH:MM AM/PM' header")
    for w in parsed.warnings:
        logger.warning("injury report: %s", w)
    return _rows_to_context(parsed, now, slate, source_url)


def parse_injury_report_pdf(
    pdf_bytes: bytes,
    now: datetime,
    slate: list[S.Event] | None = None,
    source_url: str | None = None,
) -> list[S.InjuryContext]:
    """Extract layout text from the PDF with pypdf and parse it."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - pypdf is a declared dependency
        raise ProviderError("pypdf is required to parse injury PDFs", ["PROVIDER_ERROR"]) from exc
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages: list[str] = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text(extraction_mode="layout") or "")
            except TypeError:  # older pypdf without extraction_mode
                pages.append(page.extract_text() or "")
    except Exception as exc:
        raise ProviderError(
            f"could not read injury report PDF: {type(exc).__name__}", ["PROVIDER_ERROR"]
        ) from None
    return parse_injury_report_text("\n".join(pages), now, slate, source_url)


# --------------------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------------------


def _slate_date(slate: list[S.Event] | None, now: datetime) -> str:
    if slate:
        return max(local_date(e.commence_time_utc, ET) for e in slate)
    return local_date(now, ET)


def fetch_latest_report(
    now: datetime,
    slate: list[S.Event] | None,
    http: httpx.Client,
    clock: Clock | None = None,
    *,
    lookback_hours: int = 36,
    max_consecutive_misses: int = DEFAULT_MAX_CONSECUTIVE_MISSES,
    date_local_et: str | None = None,
) -> ProviderResult[list[S.InjuryContext]]:
    """Probe report slots newest-first (HEAD, then GET on 200) and parse the first one that exists.

    A 403 or 404 is a missing slot. Probing stops after ``max_consecutive_misses`` misses in a row or when the
    lookback window is exhausted; the result then carries ``INJURY_REPORT_MISSING``.
    """
    received_at = clock.now_utc() if clock is not None else now
    date_local = date_local_et or _slate_date(slate, now)
    urls = report_slots(date_local, now, lookback_hours)
    warnings: list[str] = []
    misses = 0
    probed = 0
    for url in urls:
        probed += 1
        try:
            head = http.head(url)
            status = head.status_code
            if status == 405:
                get = http.get(url)
                status = get.status_code
                body = get.content if status == 200 else b""
            elif status == 200:
                get = http.get(url)
                status = get.status_code
                body = get.content if status == 200 else b""
            else:
                body = b""
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"network error probing injury report: {type(exc).__name__}", ["PROVIDER_ERROR"]
            ) from None
        if status == 200 and body:
            entries = parse_injury_report_pdf(body, received_at, slate, url)
            report_ts = next((e.report_timestamp_utc for e in entries if e.report_timestamp_utc), None)
            stamp = S.SourceStamp(
                source=SOURCE_NAME,
                source_url=url,
                source_record_id=None,
                source_timestamp_utc=report_ts,
                received_at_utc=received_at,
                data_mode=S.DataMode.LIVE_PROVIDER,
            )
            if misses:
                warnings.append(f"{misses} newer slot(s) were missing before {url}")
            return ProviderResult(
                data=entries, stamp=stamp, credits_cost=None, quota=empty_quota(), warnings=warnings
            )
        if status in (403, 404):
            misses += 1
            if misses >= max_consecutive_misses:
                warnings.append(f"stopped after {misses} consecutive missing slots (last probed {url})")
                break
            continue
        if status == 429 or status >= 500:
            raise ProviderError(
                f"injury report host answered {status}", ["PROVIDER_ERROR"], status_code=status
            )
        misses += 1
        warnings.append(f"unexpected status {status} for {url}")
        if misses >= max_consecutive_misses:
            break
    stamp = S.SourceStamp(
        source=SOURCE_NAME,
        source_url=None,
        source_record_id=None,
        source_timestamp_utc=None,
        received_at_utc=received_at,
        data_mode=S.DataMode.LIVE_PROVIDER,
    )
    warnings.append(f"no injury report found in the last {lookback_hours} h ({probed} slot(s) probed)")
    return ProviderResult(
        data=[],
        stamp=stamp,
        credits_cost=None,
        quota=empty_quota(),
        warnings=warnings,
        reason_codes=["INJURY_REPORT_MISSING"],
    )


def fetch_injury_report(
    date_local: str,
    clock: Clock,
    slate: list[S.Event] | None = None,
    http: httpx.Client | None = None,
) -> ProviderResult[list[S.InjuryContext]]:
    """Contract wrapper: latest report for ``date_local`` using ``clock`` (creates an httpx client when none given)."""
    client = http or httpx.Client(timeout=20.0, follow_redirects=True)
    try:
        return fetch_latest_report(clock.now_utc(), slate, client, clock, date_local_et=date_local)
    finally:
        if http is None:
            client.close()


class NbaInjuryReportProvider:
    """``InjuryProvider`` implementation over the official PDFs."""

    name = SOURCE_NAME

    def __init__(self, http: httpx.Client, clock: Clock, *, lookback_hours: int = 36) -> None:
        self.http = http
        self.clock = clock
        self.lookback_hours = lookback_hours

    def fetch_latest_report(
        self, now: datetime, slate: list[S.Event]
    ) -> ProviderResult[list[S.InjuryContext]]:
        return fetch_latest_report(now, slate, self.http, self.clock, lookback_hours=self.lookback_hours)


# --------------------------------------------------------------------------------------
# Manual entries
# --------------------------------------------------------------------------------------


def manual_injury_entries(entries: list[dict[str, Any]], now: datetime) -> list[S.InjuryContext]:
    """Build MANUAL_INPUT injury contexts from user-typed dicts.

    Keys: ``event_id`` (required), ``player`` (required unless ``status`` is "NOT YET SUBMITTED"), ``status``
    (Out/Doubtful/Questionable/Probable/Available/Not listed), ``team`` (name or abbreviation), ``reason``,
    ``report_timestamp_utc`` (ISO), ``note``.
    """
    out: list[S.InjuryContext] = []
    for i, raw in enumerate(entries, start=1):
        event_id = str(raw.get("event_id") or "").strip()
        if not event_id:
            raise InvalidInput(f"injury entry {i}: event_id is required", ["INVALID_INPUT"])
        team = try_canonical_team(str(raw.get("team") or "")) if raw.get("team") else None
        if raw.get("team") and team is None:
            raise InvalidInput(f"injury entry {i}: unknown team {raw.get('team')!r}", ["TEAM_UNMATCHED"])
        status_text = str(raw.get("status") or "").strip()
        ts_raw = raw.get("report_timestamp_utc")
        report_ts: datetime | None = None
        if ts_raw:
            try:
                report_ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            except ValueError:
                raise InvalidInput(
                    f"injury entry {i}: report_timestamp_utc is not ISO-8601", ["INVALID_INPUT"]
                ) from None
            if report_ts.tzinfo is None:
                raise InvalidInput(
                    f"injury entry {i}: report_timestamp_utc needs a timezone", ["INVALID_INPUT"]
                )
            report_ts = report_ts.astimezone(UTC)
        stamp = S.SourceStamp(
            source="user",
            source_url=None,
            source_record_id=None,
            source_timestamp_utc=report_ts,
            received_at_utc=now,
            data_mode=S.DataMode.MANUAL_INPUT,
        )
        if status_text.upper() == NOT_YET_SUBMITTED:
            out.append(
                S.InjuryContext(
                    event_id=event_id,
                    team_id=team.team_id if team else None,
                    designation=S.InjuryDesignation.UNKNOWN,
                    player_name_raw=NOT_YET_SUBMITTED,
                    report_timestamp_utc=report_ts,
                    stamp=stamp,
                    note=str(raw.get("note") or "team has not yet submitted its injury report"),
                )
            )
            continue
        player_text = str(raw.get("player") or "").strip()
        if not player_text:
            raise InvalidInput(f"injury entry {i}: player is required", ["PLAYER_UNMATCHED"])
        key = status_text.lower().replace(" ", "_")
        designation = _STATUS_WORDS.get(status_text.lower())
        if designation is None:
            try:
                designation = S.InjuryDesignation(key.upper())
            except ValueError:
                raise InvalidInput(
                    f"injury entry {i}: unknown status {status_text!r}", ["INVALID_INPUT"]
                ) from None
        player = canonical_player(player_text, team)
        out.append(
            S.InjuryContext(
                event_id=event_id,
                team_id=team.team_id if team else None,
                player_id=player.player_id,
                player_name_raw=player.name,
                designation=designation,
                reason=(str(raw.get("reason")).strip() or None) if raw.get("reason") else None,
                report_timestamp_utc=report_ts,
                stamp=stamp,
                note=(str(raw.get("note")).strip() or None) if raw.get("note") else None,
            )
        )
    return out
