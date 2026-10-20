"""Manual import of Hard Rock Bet selections and slip quotes (docs/ARCHITECTURE.md section 5, "providers/manual.py").

Three text formats are accepted by ``parse_pasted_selections``:

(a) a JSON list of ``ManualSelectionInput`` dicts;
(b) pipe format, one leg per line: ``game | market | side | line | subject | odds`` (optional 7th ``book`` and
    8th ``observed_at_utc`` columns), for example
    ``BOS@DET | SPREAD | HOME | 3.5 | | -110`` or ``PHI@NYK | PLAYER_POINTS | OVER | 24.5 | Jalen Brunson | -115``.
    The subject column is the player for a player prop and the team for a TEAM_TOTAL leg
    (``PHI@NYK | TEAM_TOTAL | OVER | 115.5 | NYK | -110``);
(c) CSV with header ``game,market,side,line,player_name,team,odds_american,odds_decimal,book,observed_at_utc``
    (``team`` is optional in the header; only ``game``, ``market`` and ``side`` are required columns).

A UTF-8 byte-order mark (Excel's "CSV UTF-8") is tolerated at the start of pasted text and files.

American odds typed as text MUST carry a sign: ``110`` is rejected with QUOTE_SIGN_AMBIGUOUS because a
missing minus is the most common slip-reading error and the two readings price very differently. Decimal
odds are recognised by a decimal point (``1.91``). Nothing here infers a sign, a line, a player, or a team.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import Clock
from hardrock_nba_parlay.errors import InvalidInput
from hardrock_nba_parlay.normalization import build_selections, canonical_player, canonical_team, match_event

__all__ = [
    "CSV_HEADER",
    "load_csv",
    "load_json",
    "parse_american_odds_text",
    "parse_pasted_selections",
    "selections_from_inputs",
    "slip_fields_from_extraction",
]

CSV_HEADER: tuple[str, ...] = (
    "game",
    "market",
    "side",
    "line",
    "player_name",
    "team",
    "odds_american",
    "odds_decimal",
    "book",
    "observed_at_utc",
)

_BOM = "﻿"

_MARKET_ALIASES: dict[str, S.MarketType] = {
    "moneyline": S.MarketType.MONEYLINE,
    "ml": S.MarketType.MONEYLINE,
    "h2h": S.MarketType.MONEYLINE,
    "money line": S.MarketType.MONEYLINE,
    "spread": S.MarketType.SPREAD,
    "spreads": S.MarketType.SPREAD,
    "ats": S.MarketType.SPREAD,
    "handicap": S.MarketType.SPREAD,
    "total": S.MarketType.TOTAL,
    "totals": S.MarketType.TOTAL,
    "ou": S.MarketType.TOTAL,
    "o u": S.MarketType.TOTAL,
    "over under": S.MarketType.TOTAL,
    "team total": S.MarketType.TEAM_TOTAL,
    "team totals": S.MarketType.TEAM_TOTAL,
    "points": S.MarketType.PLAYER_POINTS,
    "pts": S.MarketType.PLAYER_POINTS,
    "player points": S.MarketType.PLAYER_POINTS,
    "rebounds": S.MarketType.PLAYER_REBOUNDS,
    "reb": S.MarketType.PLAYER_REBOUNDS,
    "player rebounds": S.MarketType.PLAYER_REBOUNDS,
    "assists": S.MarketType.PLAYER_ASSISTS,
    "ast": S.MarketType.PLAYER_ASSISTS,
    "player assists": S.MarketType.PLAYER_ASSISTS,
    "threes": S.MarketType.PLAYER_THREES,
    "3pm": S.MarketType.PLAYER_THREES,
    "3s": S.MarketType.PLAYER_THREES,
    "three pointers": S.MarketType.PLAYER_THREES,
    "player threes": S.MarketType.PLAYER_THREES,
}
_SIDE_ALIASES: dict[str, S.Side] = {
    "home": S.Side.HOME,
    "h": S.Side.HOME,
    "away": S.Side.AWAY,
    "a": S.Side.AWAY,
    "over": S.Side.OVER,
    "o": S.Side.OVER,
    "under": S.Side.UNDER,
    "u": S.Side.UNDER,
}

_SIGNED_AMERICAN = re.compile(r"^[+-]\d{3,4}$")
_UNSIGNED_INTEGER = re.compile(r"^\d+$")
_DECIMAL_ODDS = re.compile(r"^\d+\.\d+$")


def _norm_token(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _parse_market(text: str) -> S.MarketType:
    raw = (text or "").strip()
    try:
        return S.MarketType(raw.upper())
    except ValueError:
        pass
    market = _MARKET_ALIASES.get(_norm_token(raw))
    if market is None:
        raise InvalidInput(f"unknown market {raw!r}", ["INVALID_INPUT"])
    return market


def _parse_side(text: str) -> S.Side:
    raw = (text or "").strip()
    try:
        return S.Side(raw.upper())
    except ValueError:
        pass
    side = _SIDE_ALIASES.get(_norm_token(raw))
    if side is None:
        raise InvalidInput(f"unknown side {raw!r}", ["INVALID_INPUT"])
    return side


def _parse_line(text: str | None) -> Decimal | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise InvalidInput(f"line {raw!r} is not a number", ["INVALID_INPUT"]) from None


def parse_american_odds_text(text: str) -> int:
    """Parse american odds typed as text; an unsigned number raises QUOTE_SIGN_AMBIGUOUS."""
    raw = (text or "").strip().replace(" ", "")
    if _SIGNED_AMERICAN.match(raw):
        value = int(raw)
        if abs(value) < 100:
            raise InvalidInput(f"american odds {raw} must be <= -100 or >= +100", ["INVALID_INPUT"])
        return value
    if _UNSIGNED_INTEGER.match(raw):
        raise InvalidInput(
            f"odds {raw!r} has no sign: type +{raw} or -{raw} (a missing minus is never inferred)",
            ["QUOTE_SIGN_AMBIGUOUS"],
        )
    raise InvalidInput(f"odds {raw!r} is not american odds", ["INVALID_INPUT"])


def _parse_odds_token(text: str) -> tuple[int | None, Decimal | None]:
    """ "-110" -> (-110, None); "1.91" -> (None, 1.91); "110" -> QUOTE_SIGN_AMBIGUOUS."""
    raw = (text or "").strip().replace(" ", "")
    if not raw:
        raise InvalidInput("odds are required", ["QUOTE_FIELDS_MISSING"])
    if _DECIMAL_ODDS.match(raw):
        value = Decimal(raw)
        if value <= 1:
            raise InvalidInput(f"decimal odds {raw} must be > 1", ["INVALID_INPUT"])
        return None, value
    return parse_american_odds_text(raw), None


def _parse_ts(text: str | None) -> datetime | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidInput(f"observed_at_utc {raw!r} is not ISO-8601", ["INVALID_INPUT"]) from None
    if dt.tzinfo is None:
        raise InvalidInput("observed_at_utc must carry a timezone (use Z)", ["INVALID_INPUT"])
    return dt.astimezone(UTC)


def _parse_decimal_text(text: str | None) -> Decimal | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if not _DECIMAL_ODDS.match(raw) and not _UNSIGNED_INTEGER.match(raw):
        raise InvalidInput(f"odds_decimal {raw!r} is not a decimal price", ["INVALID_INPUT"])
    return Decimal(raw)


def _build_input(
    *,
    game: str,
    market: str,
    side: str,
    line: str | None,
    player: str | None,
    american: int | None,
    decimal_odds: Decimal | None,
    book: str | None,
    observed_at: str | None,
    where: str,
    team: str | None = None,
) -> S.ManualSelectionInput:
    try:
        if american is None and decimal_odds is None:
            raise InvalidInput("provide odds_american or odds_decimal", ["QUOTE_FIELDS_MISSING"])
        market_type = _parse_market(market)
        player_text = (player or "").strip() or None
        team_text = (team or "").strip() or None
        if market_type == S.MarketType.TEAM_TOTAL and team_text is None and player_text is not None:
            # Pipe format has one subject column: for a team total it names the team, not a player.
            team_text, player_text = player_text, None
        return S.ManualSelectionInput(
            game=game.strip(),
            market=market_type,
            side=_parse_side(side),
            line=_parse_line(line),
            player_name=player_text,
            team=team_text,
            odds_american=american,
            odds_decimal=decimal_odds,
            book=(book or "").strip() or "hardrockbet_fl",
            observed_at_utc=_parse_ts(observed_at),
        )
    except InvalidInput as exc:
        raise InvalidInput(f"{where}: {exc.message}", exc.reason_codes, exc.detail) from None
    except ValueError as exc:
        codes = ["QUOTE_SIGN_AMBIGUOUS"] if "QUOTE_SIGN_AMBIGUOUS" in str(exc) else ["INVALID_INPUT"]
        raise InvalidInput(f"{where}: {exc}", codes) from None


def _parse_pipe_line(line: str, lineno: int) -> S.ManualSelectionInput:
    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 6:
        raise InvalidInput(
            f"line {lineno}: expected 'game | market | side | line | player | odds' (6 fields), got {len(parts)}",
            ["INVALID_INPUT"],
        )
    game, market, side, line_text, player, odds = parts[:6]
    book = parts[6] if len(parts) > 6 else None
    observed = parts[7] if len(parts) > 7 else None
    try:
        american, dec = _parse_odds_token(odds)
    except InvalidInput as exc:
        raise InvalidInput(f"line {lineno}: {exc.message}", exc.reason_codes) from None
    return _build_input(
        game=game,
        market=market,
        side=side,
        line=line_text,
        player=player,
        american=american,
        decimal_odds=dec,
        book=book,
        observed_at=observed,
        where=f"line {lineno}",
    )


def _from_json_items(items: Any, where: str) -> list[S.ManualSelectionInput]:
    if isinstance(items, dict) and "selections" in items:
        items = items["selections"]
    if not isinstance(items, list):
        raise InvalidInput(f"{where}: expected a JSON list of selections", ["INVALID_INPUT"])
    out: list[S.ManualSelectionInput] = []
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise InvalidInput(f"{where}: selection {i} is not an object", ["INVALID_INPUT"])
        data = dict(item)
        if "player" in data and "player_name" not in data:
            data["player_name"] = data.pop("player")
        for key in ("odds_american",):
            if isinstance(data.get(key), str):
                data[key] = parse_american_odds_text(data[key])
        try:
            out.append(S.ManualSelectionInput.model_validate(data))
        except ValueError as exc:
            text = str(exc)
            code = (
                "QUOTE_SIGN_AMBIGUOUS"
                if "QUOTE_SIGN_AMBIGUOUS" in text
                else "QUOTE_FIELDS_MISSING"
                if "QUOTE_FIELDS_MISSING" in text
                else "INVALID_INPUT"
            )
            raise InvalidInput(f"{where}: selection {i} invalid: {text.splitlines()[0]}", [code]) from None
    return out


def _from_csv_text(text: str) -> list[S.ManualSelectionInput]:
    reader = csv.DictReader(io.StringIO(text.strip()))
    fields = [f.strip() for f in (reader.fieldnames or [])]
    missing = [c for c in ("game", "market", "side") if c not in fields]
    if missing:
        raise InvalidInput(
            f"CSV header missing columns: {', '.join(missing)} (expected {','.join(CSV_HEADER)})",
            ["INVALID_INPUT"],
        )
    out: list[S.ManualSelectionInput] = []
    for i, row in enumerate(reader, start=2):
        clean = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        if not any(clean.values()):
            continue
        where = f"row {i}"
        try:
            american = (
                parse_american_odds_text(clean["odds_american"]) if clean.get("odds_american") else None
            )
            decimal_odds = _parse_decimal_text(clean.get("odds_decimal"))
        except InvalidInput as exc:
            raise InvalidInput(f"{where}: {exc.message}", exc.reason_codes) from None
        out.append(
            _build_input(
                game=clean.get("game", ""),
                market=clean.get("market", ""),
                side=clean.get("side", ""),
                line=clean.get("line"),
                player=clean.get("player_name") or clean.get("player"),
                american=american,
                decimal_odds=decimal_odds,
                book=clean.get("book"),
                observed_at=clean.get("observed_at_utc"),
                where=where,
                team=clean.get("team"),
            )
        )
    return out


def _looks_like_csv(first_line: str) -> bool:
    cells = [c.strip().lstrip(_BOM).lower() for c in first_line.split(",")]
    return "game" in cells and "market" in cells and "side" in cells


def parse_pasted_selections(text: str) -> list[S.ManualSelectionInput]:
    """Parse pasted legs in JSON, pipe, or CSV form (see module docstring)."""
    body = (text or "").lstrip(_BOM).strip()
    if not body:
        raise InvalidInput("no selections provided", ["INVALID_INPUT"])
    if body[0] in "[{":
        try:
            return _from_json_items(json.loads(body), "json")
        except json.JSONDecodeError as exc:
            raise InvalidInput(f"invalid JSON: {exc.msg}", ["INVALID_INPUT"]) from None
    lines = [ln for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if lines and _looks_like_csv(lines[0]):
        return _from_csv_text("\n".join(lines))
    out: list[S.ManualSelectionInput] = []
    for lineno, line in enumerate(lines, start=1):
        if "|" not in line:
            raise InvalidInput(
                f"line {lineno}: not pipe format ('game | market | side | line | player | odds')",
                ["INVALID_INPUT"],
            )
        out.append(_parse_pipe_line(line, lineno))
    if not out:
        raise InvalidInput("no selections found", ["INVALID_INPUT"])
    return out


def _read_path_or_text(path_or_text: str | Path) -> str:
    """Read a file (``utf-8-sig`` so an Excel BOM is dropped) or return the pasted text without a leading BOM."""
    if isinstance(path_or_text, Path):
        return path_or_text.read_text(encoding="utf-8-sig")
    candidate = path_or_text.strip()
    if candidate and "\n" not in candidate and len(candidate) < 1024 and os.path.isfile(candidate):
        return Path(candidate).read_text(encoding="utf-8-sig")
    return path_or_text.lstrip(_BOM)


def load_csv(path_or_text: str | Path) -> list[S.ManualSelectionInput]:
    """Load selections from a CSV file path or CSV text."""
    text = _read_path_or_text(path_or_text)
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not lines or not _looks_like_csv(lines[0]):
        raise InvalidInput(f"CSV must start with the header {','.join(CSV_HEADER)}", ["INVALID_INPUT"])
    return _from_csv_text("\n".join(lines))


def load_json(path_or_text: str | Path) -> list[S.ManualSelectionInput]:
    """Load selections from a JSON file path or JSON text (a list, or an object with a "selections" list)."""
    text = _read_path_or_text(path_or_text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidInput(f"invalid JSON: {exc.msg}", ["INVALID_INPUT"]) from None
    return _from_json_items(payload, "json")


# --------------------------------------------------------------------------------------
# Inputs -> Selections
# --------------------------------------------------------------------------------------

_FOUR_DP = Decimal("0.0001")


def _american_to_decimal(a: int) -> Decimal:
    if a > 0:
        return (Decimal(1) + Decimal(a) / Decimal(100)).quantize(_FOUR_DP, rounding=ROUND_HALF_EVEN)
    return (Decimal(1) + Decimal(100) / Decimal(abs(a))).quantize(_FOUR_DP, rounding=ROUND_HALF_EVEN)


def _manual_quote(item: S.ManualSelectionInput, event: S.Event, now: datetime, index: int) -> S.MarketQuote:
    where = f"selection {index}"
    if item.period not in S.SUPPORTED_PERIODS:
        raise InvalidInput(
            f"{where}: period {item.period.value} is not supported on day one", ["PERIOD_UNSUPPORTED"]
        )
    team_id: str | None = None
    player_id: str | None = None
    player_name: str | None = None
    if item.market in S.PLAYER_MARKETS:
        if not item.player_name or not item.player_name.strip():
            raise InvalidInput(
                f"{where}: player name is required for {item.market.value}", ["PLAYER_UNMATCHED"]
            )
        if item.side not in (S.Side.OVER, S.Side.UNDER):
            raise InvalidInput(f"{where}: player props use OVER/UNDER", ["INVALID_INPUT"])
        if item.line is None:
            raise InvalidInput(
                f"{where}: a line is required for {item.market.value}", ["QUOTE_FIELDS_MISSING"]
            )
        player = canonical_player(item.player_name, None)
        player_id, player_name = player.player_id, player.name
    elif item.market in (S.MarketType.MONEYLINE, S.MarketType.SPREAD):
        if item.side not in (S.Side.HOME, S.Side.AWAY):
            raise InvalidInput(f"{where}: {item.market.value} uses HOME/AWAY", ["INVALID_INPUT"])
        team_id = event.home_team.team_id if item.side == S.Side.HOME else event.away_team.team_id
        if item.market == S.MarketType.SPREAD and item.line is None:
            raise InvalidInput(f"{where}: a signed handicap is required for SPREAD", ["QUOTE_FIELDS_MISSING"])
        if item.market == S.MarketType.MONEYLINE and item.line is not None:
            raise InvalidInput(f"{where}: MONEYLINE has no line", ["INVALID_INPUT"])
    else:  # TOTAL / TEAM_TOTAL
        if item.side not in (S.Side.OVER, S.Side.UNDER):
            raise InvalidInput(f"{where}: {item.market.value} uses OVER/UNDER", ["INVALID_INPUT"])
        if item.line is None:
            raise InvalidInput(
                f"{where}: a line is required for {item.market.value}", ["QUOTE_FIELDS_MISSING"]
            )
        if item.market == S.MarketType.TEAM_TOTAL:
            # A team total belongs to one side; the user must name it (never inferred from OVER/UNDER).
            if not item.team:
                raise InvalidInput(
                    f"{where}: TEAM_TOTAL needs a team (name or abbreviation) naming whose total it is",
                    ["TEAM_UNMATCHED"],
                )
            try:
                team = canonical_team(item.team)
            except InvalidInput as exc:
                raise InvalidInput(f"{where}: {exc.message}", exc.reason_codes) from None
            if team.team_id not in (event.home_team.team_id, event.away_team.team_id):
                raise InvalidInput(
                    f"{where}: team {item.team!r} ({team.team_id}) is not playing in {event.short_name}",
                    ["TEAM_UNMATCHED"],
                )
            team_id = team.team_id
    odds_decimal = (
        item.odds_decimal if item.odds_decimal is not None else _american_to_decimal(item.odds_american or 0)
    )
    subject = player_id or team_id or ""
    line_text = format(item.line.normalize(), "f") if item.line is not None else ""
    quote_id = (
        f"manual:{event.event_id}:{item.book}:{item.market.value}:{item.side.value}:{line_text}:{subject}"
    )
    stamp = S.SourceStamp(
        source="user",
        source_url=None,
        source_record_id=None,
        source_timestamp_utc=item.observed_at_utc,
        received_at_utc=now,
        data_mode=S.DataMode.MANUAL_INPUT,
    )
    try:
        return S.MarketQuote(
            quote_id=quote_id,
            event_id=event.event_id,
            book=item.book,
            jurisdiction="US-FL" if item.book == "hardrockbet_fl" else None,
            market_type=item.market,
            period=item.period,
            is_alternate=item.is_alternate,
            side=item.side,
            team_id=team_id,
            player_id=player_id,
            player_name_raw=player_name,
            line=item.line,
            odds_american=item.odds_american,
            odds_decimal=odds_decimal,
            stamp=stamp,
        )
    except ValueError as exc:
        raise InvalidInput(f"{where}: {str(exc).splitlines()[0]}", ["INVALID_INPUT"]) from None


def selections_from_inputs(
    inputs: Sequence[S.ManualSelectionInput],
    slate: Sequence[S.Event],
    clock: Clock,
    *,
    target_book: str = "hardrockbet_fl",
) -> list[S.Selection]:
    """Turn pasted legs into ``Selection`` objects with MANUAL_INPUT stamps.

    Raises ``InvalidInput`` with EVENT_UNMATCHED, PLAYER_UNMATCHED, WRONG_BOOK, PERIOD_UNSUPPORTED or
    QUOTE_SIGN_AMBIGUOUS as appropriate. ``target_book`` defaults to ``hardrockbet_fl``.
    """
    now = clock.now_utc()
    quotes: list[S.MarketQuote] = []
    events: dict[str, S.Event] = {}
    for index, item in enumerate(inputs, start=1):
        if item.book != target_book:
            raise InvalidInput(
                f"selection {index}: book {item.book!r} is not the target book {target_book!r}; other books are reference only",
                ["WRONG_BOOK"],
            )
        try:
            event = match_event(item.game, slate)
        except InvalidInput as exc:
            raise InvalidInput(f"selection {index}: {exc.message}", exc.reason_codes) from None
        quotes.append(_manual_quote(item, event, now, index))
        events[event.event_id] = event
    return build_selections(quotes, events, strict=True)


# --------------------------------------------------------------------------------------
# Screenshot / receipt extraction -> reviewable structure
# --------------------------------------------------------------------------------------


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _money(value: Any) -> Decimal | None:
    raw = _text(value).replace("$", "").replace(",", "")
    if not raw:
        return None
    try:
        d = Decimal(raw)
    except InvalidOperation:
        return None
    return d if d >= 0 else None


def _odds_from_extracted(value: Any) -> tuple[int | None, Decimal | None, bool]:
    """(american, decimal, ambiguous). Ambiguous when an integer has no sign or the text is unreadable."""
    raw = _text(value).replace(" ", "")
    if not raw:
        return None, None, True
    if _DECIMAL_ODDS.match(raw):
        d = Decimal(raw)
        return (None, d, False) if d > 1 else (None, None, True)
    if _SIGNED_AMERICAN.match(raw):
        a = int(raw)
        return (a, None, False) if abs(a) >= 100 else (None, None, True)
    return None, None, True


def slip_fields_from_extraction(
    fields: dict[str, Any],
) -> tuple[S.ManualQuoteInput, list[S.ManualSelectionInput], list[str]]:
    """Turn fields read off a bet-slip screenshot/receipt into a reviewable structure.

    ``fields`` keys (all optional, all raw text as read): ``legs`` (list of dicts with ``game``, ``market``, ``side``,
    ``line``, ``player``, ``team``, ``odds``, ``text``), ``combined_odds``, ``stake``, ``payout``,
    ``payout_includes_stake``, ``captured_at_utc``, ``source`` ("SCREENSHOT_EXTRACTED" or "RECEIPT"), ``book``.

    Nothing is inferred: an unsigned odds number, a missing line for a market that needs one, a missing player on
    a prop, a missing team on a team total, a missing stake, an unreadable combined price, an unknown payout
    convention, and a capture time that is not ISO-8601 are all listed in ``unresolved`` by field name. This
    function never raises for readable-but-odd text. Only fully resolved legs become ``ManualSelectionInput``;
    every leg's raw text is kept in ``legs_as_shown``. ``user_confirmed`` stays False until the caller confirms
    with the user.
    """
    unresolved: list[str] = []
    legs_raw = fields.get("legs") or []
    legs_as_shown: list[str] = []
    selections: list[S.ManualSelectionInput] = []
    book = _text(fields.get("book")) or "hardrockbet_fl"
    captured: datetime | None = None
    captured_unresolved = False
    captured_text = _text(fields.get("captured_at_utc"))
    if captured_text:
        try:
            captured = _parse_ts(captured_text)
        except InvalidInput:
            # e.g. "10/20/2026 2:55 PM" read off a screenshot: ask, never guess the zone or the format.
            captured_unresolved = True
    for i, leg in enumerate(legs_raw):
        prefix = f"legs[{i}]"
        if not isinstance(leg, dict):
            legs_as_shown.append(_text(leg))
            unresolved.append(f"{prefix}.text")
            continue
        shown = _text(leg.get("text")) or " | ".join(
            _text(leg.get(k))
            for k in ("game", "market", "side", "line", "player", "odds")
            if _text(leg.get(k))
        )
        legs_as_shown.append(shown)
        leg_ok = True
        market: S.MarketType | None = None
        side: S.Side | None = None
        try:
            market = _parse_market(_text(leg.get("market")))
        except InvalidInput:
            unresolved.append(f"{prefix}.market")
            leg_ok = False
        try:
            side = _parse_side(_text(leg.get("side")))
        except InvalidInput:
            unresolved.append(f"{prefix}.side")
            leg_ok = False
        if not _text(leg.get("game")):
            unresolved.append(f"{prefix}.game")
            leg_ok = False
        line: Decimal | None = None
        try:
            line = _parse_line(_text(leg.get("line")))
        except InvalidInput:
            unresolved.append(f"{prefix}.line")
            leg_ok = False
        if (
            market is not None
            and market != S.MarketType.MONEYLINE
            and line is None
            and f"{prefix}.line" not in unresolved
        ):
            unresolved.append(f"{prefix}.line")
            leg_ok = False
        player = _text(leg.get("player")) or None
        if market is not None and market in S.PLAYER_MARKETS and not player:
            unresolved.append(f"{prefix}.player")
            leg_ok = False
        team = _text(leg.get("team")) or None
        if market == S.MarketType.TEAM_TOTAL and not team:
            unresolved.append(f"{prefix}.team")
            leg_ok = False
        american, dec, ambiguous = _odds_from_extracted(leg.get("odds"))
        if ambiguous:
            unresolved.append(f"{prefix}.odds_sign")
            leg_ok = False
        if leg_ok and market is not None and side is not None:
            try:
                selections.append(
                    S.ManualSelectionInput(
                        game=_text(leg.get("game")),
                        market=market,
                        side=side,
                        line=line,
                        player_name=player,
                        team=team,
                        odds_american=american,
                        odds_decimal=dec,
                        book=book,
                        observed_at_utc=captured,
                    )
                )
            except (ValueError, InvalidInput):
                unresolved.append(f"{prefix}.odds")
    combined_american, combined_decimal, combined_ambiguous = _odds_from_extracted(
        fields.get("combined_odds")
    )
    if combined_ambiguous:
        unresolved.append("combined_odds")
    stake = _money(fields.get("stake"))
    if stake is None:
        unresolved.append("stake")
    payout = _money(fields.get("payout"))
    includes = fields.get("payout_includes_stake")
    if not isinstance(includes, bool):
        includes = None
        unresolved.append("payout_includes_stake")
    source_text = _text(fields.get("source")).upper()
    source = S.QuoteSource.RECEIPT if source_text == "RECEIPT" else S.QuoteSource.SCREENSHOT_EXTRACTED
    if captured_unresolved:
        unresolved.append("captured_at_utc")
    quote = S.ManualQuoteInput(
        combined_decimal=combined_decimal,
        combined_american=combined_american,
        stake_shown_usd=stake,
        payout_shown_usd=payout,
        payout_includes_stake=includes,
        legs_as_shown=legs_as_shown,
        source=source,
        captured_at_utc=captured,
        user_confirmed=False,
    )
    return quote, selections, list(dict.fromkeys(unresolved))


def inputs_from_iterable(items: Iterable[dict[str, Any]]) -> list[S.ManualSelectionInput]:
    """Validate an iterable of selection dicts (the MCP tool argument shape)."""
    return _from_json_items(list(items), "selections")
