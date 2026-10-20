"""Book-quote review, candidate revalidation, and user-ticket analysis (pipeline module).

- ``review_book_quote`` attaches the combined price the sportsbook actually shows. The book quote replaces
  the indicative multiplied price (QUOTE_REPLACES_INDICATIVE). Legs shown on the slip must each describe
  one candidate leg, the same bet and not merely the same game (QUOTE_CONFLICTS_WITH_LEGS otherwise: a
  spread with the opposite sign, the opponent's moneyline, or another game's total is a conflict); an
  unconfirmed quote is stored but changes nothing (QUOTE_UNCONFIRMED); a quote captured longer than
  ``max_odds_age_seconds`` ago, or whose slip payout contradicts its combined price, is stored but not
  applied (QUOTE_STALE / QUOTE_SIGN_AMBIGUOUS); a candidate whose inputs are older than
  ``max_odds_age_seconds`` stays NEEDS_BOOK_QUOTE with QUOTE_STALE until ``refresh_parlay`` runs.
- ``revalidate`` re-analyses every leg with fresh data and decides EXPIRED / REJECTED / NEEDS_BOOK_QUOTE /
  READY_FOR_USER_REVIEW. A typed (MANUAL_INPUT) leg is kept at the line the user typed; only a feed leg
  follows the feed's current line. It returns a new candidate object; the services layer writes history.
- ``analyze_user_ticket`` turns three pasted legs into one candidate (same-game tickets are qualitative).

Nothing here touches the clock, the network, or the database.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from hardrock_nba_parlay import correlation, freshness, normalization, probabilities
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.candidate_builder import analyze_leg, make_candidate
from hardrock_nba_parlay.config import Clock, FixedClock, Settings, to_display
from hardrock_nba_parlay.db import new_id
from hardrock_nba_parlay.errors import InvalidInput
from hardrock_nba_parlay.providers import manual

__all__ = [
    "BLOCKING_UNRESOLVED_FIELDS",
    "PAYOUT_CONTRADICTS_REASON",
    "PRICE_CHANGED_REASON",
    "QUOTE_CAPTURE_STALE_REASON",
    "analyze_user_ticket",
    "loose_identity",
    "match_legs_as_shown",
    "rebuild_candidate",
    "review_book_quote",
    "revalidate",
]

PRICE_CHANGED_REASON = "price changed: re-import the slip quote"
QUOTE_CAPTURE_STALE_REASON = "slip quote captured too long ago: re-import a current quote"
PAYOUT_CONTRADICTS_REASON = "slip payout contradicts the combined price: re-check the slip and re-import"
DEFAULT_MAX_ODDS_AGE_SECONDS = 180
MANUAL_PRICE_TOLERANCE = Decimal("0.0105")  # the schema's own American/decimal cross-check tolerance

# Unresolved book-quote fields that keep a candidate out of READY_FOR_USER_REVIEW until a re-import.
BLOCKING_UNRESOLVED_FIELDS: frozenset[str] = frozenset(
    {"legs_as_shown", "combined_odds", "payout_shown_usd", "captured_at_utc", "price_changed"}
)

_QUOTE_CODES: frozenset[str] = frozenset(
    {
        "QUOTE_FIELDS_MISSING",
        "QUOTE_SIGN_AMBIGUOUS",
        "QUOTE_UNCONFIRMED",
        "QUOTE_CONFLICTS_WITH_LEGS",
        "QUOTE_REPLACES_INDICATIVE",
        "QUOTE_STALE",
    }
)
_TERMINAL_STATES: frozenset[S.CandidateState] = frozenset(
    {S.CandidateState.USER_CONFIRMED_PLACED, S.CandidateState.SETTLED}
)
_FROZEN_STATES: frozenset[S.CandidateState] = frozenset({S.CandidateState.EXPIRED, S.CandidateState.REJECTED})
_MARKET_WORDS: dict[S.MarketType, tuple[str, ...]] = {
    S.MarketType.MONEYLINE: ("ml", "moneyline", "money line", "to win", "winner"),
    S.MarketType.SPREAD: ("spread", "handicap", "ats"),
    S.MarketType.TOTAL: ("total", "total points", "game total"),
    S.MarketType.TEAM_TOTAL: ("team total",),
    S.MarketType.PLAYER_POINTS: ("points", "pts"),
    S.MarketType.PLAYER_REBOUNDS: ("rebounds", "reb", "rebs"),
    S.MarketType.PLAYER_ASSISTS: ("assists", "ast", "asts"),
    S.MarketType.PLAYER_THREES: ("threes", "3pm", "3s", "three pointers", "made threes"),
}
# Words that sit right after the team a team-market slip line is about ("Pistons +3.5", "Thunder ML").
_SUBJECT_MARKERS: dict[S.MarketType, tuple[str, ...]] = {
    S.MarketType.MONEYLINE: ("ml", "moneyline", "money line", "to win", "winner"),
    S.MarketType.SPREAD: ("pk", "pick", "pick em"),
    S.MarketType.TEAM_TOTAL: ("team total", "total", "over", "under", "o", "u"),
}
_PICK_EM_WORDS: tuple[str, ...] = ("pk", "pick", "pick em")
# A signed number in the raw slip text: "+3.5", "-3.5", "- 3.5"; never the digits of a larger number.
_SIGNED_NUMBER = re.compile(r"(?<![\d.])([+-])\s*(\d+(?:\.\d+)?)(?![\d.])")
# Matchup separators as a sportsbook prints them: "BOS @ DET", "BOS at DET", "DET vs BOS", "DET v. BOS".
_MATCHUP_SEPARATOR = re.compile(r"\s*@\s*|\s+at\s+|\s+vs?\.?\s+|\s+versus\s+", re.IGNORECASE)


def _unambiguous_aliases() -> dict[str, tuple[str, ...]]:
    """Normalised aliases per team id, dropping spellings shared by two clubs ("LA", "Los Angeles")."""
    owners: dict[str, set[str]] = {}
    for record in normalization.NBA_TEAMS:
        for alias in record.all_names():
            owners.setdefault(normalization.normalize_name(alias), set()).add(record.team_id)
    out: dict[str, tuple[str, ...]] = {}
    for record in normalization.NBA_TEAMS:
        keys = {normalization.normalize_name(a) for a in record.all_names()}
        out[record.team_id] = tuple(sorted(k for k in keys if k and len(owners[k]) == 1))
    return out


_UNAMBIGUOUS_ALIASES: dict[str, tuple[str, ...]] = _unambiguous_aliases()


# --------------------------------------------------------------------------------------
# Candidate rebuild helper
# --------------------------------------------------------------------------------------


def rebuild_candidate(candidate: S.Candidate, **changes: Any) -> S.Candidate:
    """A new, fully validated ``Candidate`` with ``changes`` applied (never mutates the input)."""
    data = candidate.model_dump()
    data.update(changes)
    return S.Candidate.model_validate(data)


def _dedupe(codes: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(codes))


def _without_quote_codes(codes: Sequence[str]) -> list[str]:
    return [c for c in codes if c not in _QUOTE_CODES]


# --------------------------------------------------------------------------------------
# legs_as_shown matching
# --------------------------------------------------------------------------------------


def _team_aliases(team: S.Team) -> list[str]:
    record = next((t for t in normalization.NBA_TEAMS if t.team_id == team.team_id), None)
    names = list(record.all_names()) if record is not None else [team.name]
    if team.abbreviation:
        names.append(team.abbreviation)
    return names


def _has(padded: str, phrase: str) -> bool:
    key = normalization.normalize_name(phrase)
    return bool(key) and f" {key} " in padded


def _line_present(padded: str, line_text: str) -> bool:
    """The line as a whole token, also when glued to an over/under letter ("o8 5" after normalisation)."""
    key = normalization.normalize_name(line_text)
    return bool(key) and re.search(rf"(?: |[ou]){re.escape(key)} ", padded) is not None


def _side_present(padded: str, side: S.Side) -> bool:
    """ "over" / "o" / "o24.5" (normalised to "o24 5") for OVER; the UNDER forms for UNDER."""
    letter = "o" if side == S.Side.OVER else "u"
    word = "over" if side == S.Side.OVER else "under"
    return _has(padded, word) or _has(padded, letter) or re.search(rf" {letter}\d", padded) is not None


def _padded(shown: str) -> str:
    """Normalised slip text with matchup separators kept as the word "at" (normalisation would drop "@")."""
    return f" {normalization.normalize_name(_MATCHUP_SEPARATOR.sub(' at ', shown))} "


def _strip_matchups(padded: str, home: S.Team, away: S.Team) -> str:
    """Remove "X at Y" phrases naming both teams of the event: the matchup line is context, not the bet."""
    out = padded
    home_aliases = [normalization.normalize_name(a) for a in _team_aliases(home)]
    away_aliases = [normalization.normalize_name(a) for a in _team_aliases(away)]
    for first, second in ((away_aliases, home_aliases), (home_aliases, away_aliases)):
        for a in first:
            for b in second:
                if a and b:
                    out = re.sub(rf" {re.escape(a)} at {re.escape(b)} ", " ", out)
    return out


def _names_team(padded: str, team: S.Team) -> bool:
    return any(_has(padded, alias) for alias in _team_aliases(team))


def _names_foreign_team(padded: str, event: S.Event) -> bool:
    """True when the slip names an NBA team that is not playing in ``event`` (another game's bet)."""
    playing = {event.home_team.team_id, event.away_team.team_id}
    for team_id, aliases in _UNAMBIGUOUS_ALIASES.items():
        if team_id in playing:
            continue
        if any(f" {alias} " in padded for alias in aliases):
            return True
    return False


def _signed_tokens(shown: str) -> set[tuple[str, Decimal]]:
    """Every signed number on the raw slip line, e.g. {("+", 3.5), ("-", 110)} for "Pistons +3.5 (-110)"."""
    out: set[tuple[str, Decimal]] = set()
    for sign, digits in _SIGNED_NUMBER.findall(shown):
        try:
            out.add((sign, Decimal(digits).normalize()))
        except ArithmeticError:  # pragma: no cover - the regex only admits plain decimals
            continue
    return out


def _spread_sign_matches(shown: str, padded: str, line: Decimal) -> bool:
    """The slip must show the handicap WITH the sign the leg was offered at; the opposite sign is another bet."""
    magnitude = abs(line).normalize()
    wanted = ("-" if line < 0 else "+", magnitude)
    tokens = _signed_tokens(shown)
    if wanted in tokens:
        return True
    if magnitude == 0:
        return any(_has(padded, w) for w in _PICK_EM_WORDS) or _line_present(padded, "0")
    return False


def _subject_team_is(padded: str, leg: S.Selection, team: S.Team, opponent: S.Team) -> bool | None:
    """Whether the slip line is about ``team`` (True), about ``opponent`` (False), or unresolvable (None)."""
    stripped = _strip_matchups(padded, leg.event.home_team, leg.event.away_team)
    ours = _names_team(stripped, team)
    theirs = _names_team(stripped, opponent)
    if ours and not theirs:
        return True
    if theirs and not ours:
        return False
    if not ours and not theirs:
        return None
    # Both clubs named outside a matchup phrase: the subject is the club written right before the bet marker
    # ("Pistons +3.5", "Thunder ML", "Knicks team total over").
    markers = list(_SUBJECT_MARKERS.get(leg.quote.market_type, ()))
    if leg.quote.market_type == S.MarketType.SPREAD and leg.quote.line is not None:
        markers.append(normalization.format_line(abs(leg.quote.line)))
    elif leg.quote.market_type == S.MarketType.TEAM_TOTAL and leg.quote.line is not None:
        markers.append(normalization.format_line(leg.quote.line))

    def adjacent(candidate: S.Team) -> bool:
        for alias in _team_aliases(candidate):
            key = normalization.normalize_name(alias)
            for marker in markers:
                m = normalization.normalize_name(marker)
                if key and m and f" {key} {m} " in stripped:
                    return True
                if key and m and re.search(rf" {re.escape(key)} [ou]{re.escape(m)} ", stripped):
                    return True
        return False

    ours_adjacent, theirs_adjacent = adjacent(team), adjacent(opponent)
    if ours_adjacent and not theirs_adjacent:
        return True
    if theirs_adjacent and not ours_adjacent:
        return False
    return None


def _leg_match_score(shown: str, leg: S.Selection) -> int | None:
    """Specificity score when ``shown`` describes ``leg`` (the same bet); None when it cannot.

    A slip line that names a team outside the leg's game, the opponent as the subject of a team market, a
    spread with the opposite sign (or no sign), the other side of a total, or a different line never matches.
    """
    padded = _padded(shown)
    quote = leg.quote
    event = leg.event
    score = 0
    if quote.market_type in S.PLAYER_MARKETS:
        name = leg.player.name if leg.player is not None else (quote.player_name_raw or "")
        tokens = normalization.normalize_name(name).split()
        if not tokens:
            return None
        if _has(padded, name):
            score += 2
        elif _has(padded, tokens[-1]):
            score += 1
        else:
            return None
        # A player's name may contain a city ("P.J. Washington"): judge foreign teams on the rest of the line.
        without_name = padded.replace(f" {normalization.normalize_name(name)} ", " ")
        if _names_foreign_team(without_name, event):
            return None
    elif _names_foreign_team(padded, event):
        return None
    elif quote.market_type in (S.MarketType.MONEYLINE, S.MarketType.SPREAD, S.MarketType.TEAM_TOTAL):
        team = leg.team or (normalization.team_by_id(quote.team_id) if quote.team_id else None)
        if team is None:
            return None
        opponent = event.away_team if team.team_id == event.home_team.team_id else event.home_team
        if _subject_team_is(padded, leg, team, opponent) is not True:
            return None
        score += 1
    else:  # TOTAL: the game is the subject; naming one of its teams or the word "total" is a bonus
        if _names_team(padded, event.home_team) or _names_team(padded, event.away_team):
            score += 1
    if quote.side in (S.Side.OVER, S.Side.UNDER):
        if _side_present(padded, quote.side):
            score += 1
        else:
            return None
    if quote.line is not None:
        if quote.market_type == S.MarketType.SPREAD:
            if not _spread_sign_matches(shown, padded, quote.line):
                return None
        elif not _line_present(padded, normalization.format_line(abs(quote.line))):
            return None
        score += 1
    if any(_has(padded, w) for w in _MARKET_WORDS.get(quote.market_type, ())):
        score += 1
    return score


def match_legs_as_shown(
    legs_as_shown: Sequence[str], ticket: S.ThreeLegTicket
) -> tuple[list[int | None], list[str]]:
    """Map each slip line to the candidate leg it describes.

    Returns ``(indexes, conflicts)``: ``indexes[i]`` is the 0-based leg index for ``legs_as_shown[i]`` (None
    when nothing matches) and ``conflicts`` lists human-readable problems (empty when the slip matches the
    three legs one-to-one). An empty ``legs_as_shown`` matches trivially.
    """
    conflicts: list[str] = []
    if not legs_as_shown:
        return [], conflicts
    if len(legs_as_shown) != len(ticket.legs):
        conflicts.append(f"slip shows {len(legs_as_shown)} leg(s); the candidate has {len(ticket.legs)}")
    indexes: list[int | None] = []
    for shown in legs_as_shown:
        scored = [(idx, _leg_match_score(shown, leg)) for idx, leg in enumerate(ticket.legs)]
        viable = [(idx, s) for idx, s in scored if s is not None]
        if not viable:
            conflicts.append(f"{shown!r} matches none of the candidate legs")
            indexes.append(None)
            continue
        best = max(s for _, s in viable)
        winners = [idx for idx, s in viable if s == best]
        if len(winners) != 1:
            names = ", ".join(ticket.legs[i].description for i in winners)
            conflicts.append(f"{shown!r} is ambiguous between: {names}")
            indexes.append(None)
            continue
        indexes.append(winners[0])
    matched = [i for i in indexes if i is not None]
    if len(set(matched)) != len(matched):
        conflicts.append("two slip lines describe the same candidate leg")
    return indexes, conflicts


# --------------------------------------------------------------------------------------
# Book quote review
# --------------------------------------------------------------------------------------


def _combined_decimal(quote: S.ManualQuoteInput) -> tuple[Decimal | None, list[str]]:
    codes: list[str] = []
    from_american = (
        probabilities.american_to_decimal(quote.combined_american)
        if quote.combined_american is not None
        else None
    )
    if quote.combined_decimal is not None:
        combined = probabilities.q_odds(quote.combined_decimal)
        if from_american is not None and abs(from_american - combined) > Decimal("0.0105"):
            codes.append("QUOTE_SIGN_AMBIGUOUS")
        return combined, codes
    return from_american, codes


def _payout_consistent(quote: S.ManualQuoteInput, combined: Decimal) -> bool | None:
    """Whether the slip's stake and payout agree with the combined price (None when not checkable).

    With an unknown payout convention both readings (stake included / excluded) are tried; a payout that fits
    neither contradicts the price.
    """
    if quote.stake_shown_usd is None or quote.payout_shown_usd is None:
        return None
    conventions = [True, False]
    if quote.payout_includes_stake is not None:
        conventions = [quote.payout_includes_stake]
    for includes_stake in conventions:
        expected = quote.stake_shown_usd * (combined if includes_stake else combined - 1)
        tolerance = max(Decimal("0.02"), expected * Decimal("0.005"))
        if abs(expected - quote.payout_shown_usd) <= tolerance:
            return True
    return False


def _capture_age_seconds(quote: S.ManualQuoteInput, now: datetime) -> int:
    """How long ago the slip quote was captured (0 when the caller did not say: captured now)."""
    if quote.captured_at_utc is None:
        return 0
    return int(abs((now - quote.captured_at_utc).total_seconds()))


def review_book_quote(
    candidate: S.Candidate,
    quote: S.ManualQuoteInput,
    now: datetime,
    settings: Settings | None = None,
    *,
    max_odds_age_seconds: int | None = None,
) -> tuple[S.Candidate, list[str]]:
    """Attach the sportsbook's combined quote to ``candidate``; returns ``(new_candidate, reason_codes)``.

    - no combined price -> ``QUOTE_FIELDS_MISSING`` and the candidate is returned unchanged;
    - slip legs that do not describe the candidate's legs -> ``QUOTE_CONFLICTS_WITH_LEGS``, quote stored as
      unresolved, state NEEDS_BOOK_QUOTE;
    - American and decimal prices that disagree, or a slip payout that contradicts the combined price ->
      ``QUOTE_SIGN_AMBIGUOUS``, quote stored as unresolved, state NEEDS_BOOK_QUOTE;
    - ``captured_at_utc`` more than ``max_odds_age_seconds`` from ``now`` -> ``QUOTE_STALE``, quote stored
      as unresolved (``captured_at_utc``), state NEEDS_BOOK_QUOTE: re-import a current quote;
    - ``user_confirmed=False`` -> ``QUOTE_UNCONFIRMED``, quote stored, state NEEDS_BOOK_QUOTE;
    - otherwise the book quote replaces the indicative payout math (``QUOTE_REPLACES_INDICATIVE``), the EV
      is recomputed when a joint probability exists, and the state becomes READY_FOR_USER_REVIEW only when
      the inputs are still fresh and every leg is USABLE (else NEEDS_BOOK_QUOTE with QUOTE_STALE or
      WAIT_FOR_UPDATE); a candidate past its earliest tip-off becomes EXPIRED.
    """
    if max_odds_age_seconds is None:
        max_odds_age_seconds = settings.max_odds_age_seconds if settings else DEFAULT_MAX_ODDS_AGE_SECONDS
    combined, codes = _combined_decimal(quote)
    if combined is None:
        return candidate, ["QUOTE_FIELDS_MISSING"]
    unresolved: list[str] = []
    notes_blocked: list[str] = []
    if "QUOTE_SIGN_AMBIGUOUS" in codes:
        unresolved.append("combined_odds")
    if quote.payout_includes_stake is None:
        unresolved.append("payout_includes_stake")
    if quote.payout_shown_usd is not None and quote.stake_shown_usd is None:
        unresolved.append("stake_shown_usd")
    if _payout_consistent(quote, combined) is False:
        unresolved.append("payout_shown_usd")
        if "QUOTE_SIGN_AMBIGUOUS" not in codes:
            codes.append("QUOTE_SIGN_AMBIGUOUS")
        notes_blocked.append(
            f"{PAYOUT_CONTRADICTS_REASON}: stake {quote.stake_shown_usd} at {combined} does not pay "
            f"{quote.payout_shown_usd}."
        )
    capture_age = _capture_age_seconds(quote, now)
    capture_stale = capture_age > max_odds_age_seconds
    if capture_stale:
        unresolved.append("captured_at_utc")
        codes.append("QUOTE_STALE")
        notes_blocked.append(
            f"{QUOTE_CAPTURE_STALE_REASON}: captured {capture_age}s ago (limit {max_odds_age_seconds}s)."
        )
    _indexes, conflicts = match_legs_as_shown(quote.legs_as_shown, candidate.ticket)
    if conflicts:
        unresolved.append("legs_as_shown")
        codes.append("QUOTE_CONFLICTS_WITH_LEGS")
    if not quote.user_confirmed:
        codes.append("QUOTE_UNCONFIRMED")
    book_quote = S.BookQuote(
        book_quote_id=new_id("bq"),
        candidate_id=candidate.candidate_id,
        combined_decimal=combined,
        combined_american=quote.combined_american,
        stake_shown_usd=quote.stake_shown_usd,
        payout_shown_usd=quote.payout_shown_usd,
        payout_includes_stake=quote.payout_includes_stake,
        legs_as_shown=list(quote.legs_as_shown),
        source=quote.source,
        captured_at_utc=quote.captured_at_utc or now,
        confirmed_by_user=quote.user_confirmed,
        unresolved_fields=_dedupe(unresolved),
    )
    base_codes = _without_quote_codes(candidate.reason_codes)
    frozen = candidate.state in _FROZEN_STATES or candidate.state in _TERMINAL_STATES

    blocked = (
        "QUOTE_CONFLICTS_WITH_LEGS" in codes
        or "QUOTE_UNCONFIRMED" in codes
        or "QUOTE_SIGN_AMBIGUOUS" in codes
        or capture_stale
    )
    if blocked:
        notes = [f"Quote {combined} stored but not applied: {', '.join(codes)}."]
        notes.extend(notes_blocked)
        notes.extend(conflicts)
        new_state = candidate.state if frozen else S.CandidateState.NEEDS_BOOK_QUOTE
        updated = rebuild_candidate(
            candidate,
            book_quote=book_quote,
            state=new_state,
            updated_at_utc=now,
            reason_codes=_dedupe([*base_codes, *codes]),
            rationale=candidate.rationale + "\n" + " ".join(notes),
        )
        return updated, _dedupe(codes)

    # Success: the book quote governs the payout math.
    codes.append("QUOTE_REPLACES_INDICATIVE")
    payout = probabilities.payout_math(candidate.payout.stake_usd, combined, "BOOK_QUOTE")
    ev = probabilities.ev_per_dollar(candidate.p_joint, combined) if candidate.p_joint is not None else None
    legs_usable = all(a.decision == S.LegDecision.USABLE for a in candidate.leg_analyses)
    age = (now - candidate.inputs_snapshot_utc).total_seconds()
    notes = [probabilities.describe_combined_odds(candidate.indicative_multiplied_decimal, combined)]
    if frozen:
        new_state = candidate.state
        notes.append(
            f"Candidate is {candidate.state.value}; the quote is recorded but the state does not change."
        )
    elif now >= candidate.expires_at_utc:
        new_state = S.CandidateState.EXPIRED
        codes.append("GAME_STARTED")
        notes.append("The earliest game has started; the candidate is EXPIRED.")
    elif age > max_odds_age_seconds:
        new_state = S.CandidateState.NEEDS_BOOK_QUOTE
        codes.append("QUOTE_STALE")
        notes.append(
            f"Inputs are {int(age)}s old (limit {max_odds_age_seconds}s): run refresh_parlay before review."
        )
    elif not legs_usable:
        new_state = S.CandidateState.NEEDS_BOOK_QUOTE
        codes.append("WAIT_FOR_UPDATE")
        notes.append("A leg is not USABLE right now; wait for the next update, then refresh_parlay.")
    else:
        new_state = S.CandidateState.READY_FOR_USER_REVIEW
    if ev is not None:
        notes.append(f"EV per dollar at the book quote: {ev:+f} (market-baseline joint probability).")
    updated = rebuild_candidate(
        candidate,
        book_quote=book_quote,
        payout=payout,
        ev_per_dollar=ev,
        state=new_state,
        updated_at_utc=now,
        reason_codes=_dedupe([*base_codes, *codes]),
        rationale=candidate.rationale + "\n" + " ".join(notes),
    )
    return updated, _dedupe(codes)


# --------------------------------------------------------------------------------------
# Revalidation
# --------------------------------------------------------------------------------------


def loose_identity(selection: S.Selection) -> tuple[str, str, str, bool, str, str]:
    q = selection.quote
    subject = q.player_id or q.player_name_raw or q.team_id or ""
    return (q.event_id, q.market_type.value, q.period.value, q.is_alternate, q.side.value, subject)


def _price_moved(old: S.MarketQuote, fresh: S.MarketQuote) -> bool:
    """Exact comparison for feed quotes; a typed (MANUAL_INPUT) quote tolerates American-odds rounding."""
    if old.stamp.data_mode == S.DataMode.MANUAL_INPUT:
        return abs(fresh.odds_decimal - old.odds_decimal) > MANUAL_PRICE_TOLERANCE
    return fresh.odds_decimal != old.odds_decimal


def _unresolved_book_quote(book_quote: S.BookQuote) -> S.BookQuote:
    fields = _dedupe([*book_quote.unresolved_fields, "price_changed"])
    return book_quote.model_copy(update={"confirmed_by_user": False, "unresolved_fields": fields})


def revalidate(
    candidate: S.Candidate,
    fresh_selections: Sequence[S.Selection],
    fresh_refs: Sequence[S.MarketQuote],
    fresh_injuries: Sequence[S.InjuryContext],
    now: datetime,
    settings: Settings,
) -> S.Candidate:
    """Re-analyse every leg with fresh data and return the updated candidate (a new object).

    Transitions: a started game -> EXPIRED (GAME_STARTED); a postponed game or a feed leg whose quote is
    gone -> REJECTED (GAME_POSTPONED / MARKET_SUSPENDED); a leg now UNUSABLE -> REJECTED; a price or line
    change -> NEEDS_BOOK_QUOTE ("price changed: re-import the slip quote") with the old quote kept but
    marked unresolved; a leg now WAIT_FOR_UPDATE -> NEEDS_BOOK_QUOTE (WAIT_FOR_UPDATE); otherwise the
    analyses and ``inputs_snapshot_utc`` are refreshed and READY_FOR_USER_REVIEW is kept or restored when
    a confirmed book quote with no blocking unresolved field exists. A typed (MANUAL_INPUT) leg follows
    the feed only when the feed carries exactly the same bet (same line); otherwise it is kept at the line
    the user typed and re-analysed there (LINE_MISMATCH when no benchmark exists at that line), never
    rewritten to the feed's main line and never called suspended. Placed or settled candidates are
    returned unchanged.
    """
    if candidate.state in _TERMINAL_STATES:
        return candidate
    exact = {s.selection_id: s for s in fresh_selections}
    loose = {loose_identity(s): s for s in fresh_selections}
    new_legs: list[S.Selection] = []
    analyses: dict[str, S.LegAnalysis] = {}
    codes: list[str] = []
    changes: list[str] = []
    started = postponed = False
    gone: list[str] = []
    unusable: list[str] = []
    waiting: list[str] = []
    for leg in candidate.ticket.legs:
        typed = leg.quote.stamp.data_mode == S.DataMode.MANUAL_INPUT
        fresh = exact.get(leg.selection_id)
        if fresh is None and not typed:
            fresh = loose.get(loose_identity(leg))
        event = fresh.event if fresh is not None else leg.event
        game_codes = freshness.check_event_not_started(event, now)
        if "GAME_STARTED" in game_codes:
            started = True
        if "GAME_POSTPONED" in game_codes:
            postponed = True
        codes += game_codes
        if fresh is None:
            new_legs.append(leg)
            analysis = analyze_leg(leg, fresh_refs, fresh_injuries, now, settings)
            analyses[leg.selection_id] = analysis
            if typed:
                # The user's own line stays; it is only re-analysed against the fresh benchmarks.
                if analysis.decision == S.LegDecision.UNUSABLE and not game_codes:
                    unusable.append(f"{leg.description}: {', '.join(analysis.reason_codes)}")
                elif analysis.decision == S.LegDecision.WAIT_FOR_UPDATE:
                    waiting.append(f"{leg.description}: {', '.join(analysis.reason_codes)}")
            elif not game_codes:
                gone.append(leg.description)
            continue
        new_legs.append(fresh)
        analysis = analyze_leg(fresh, fresh_refs, fresh_injuries, now, settings)
        analyses[fresh.selection_id] = analysis
        if _price_moved(leg.quote, fresh.quote) or fresh.quote.line != leg.quote.line:
            changes.append(
                f"{leg.description} {leg.quote.odds_decimal} -> {fresh.description} {fresh.quote.odds_decimal}"
            )
        if analysis.decision == S.LegDecision.UNUSABLE and not game_codes:
            unusable.append(f"{fresh.description}: {', '.join(analysis.reason_codes)}")
        elif analysis.decision == S.LegDecision.WAIT_FOR_UPDATE:
            waiting.append(f"{fresh.description}: {', '.join(analysis.reason_codes)}")

    try:
        ticket = S.ThreeLegTicket(legs=new_legs)
    except ValueError:
        ticket = candidate.ticket
        analyses = {
            leg.selection_id: analyses.get(leg.selection_id)
            or analyze_leg(leg, fresh_refs, fresh_injuries, now, settings)
            for leg in ticket.legs
        }
    report = correlation.check_correlation(ticket)
    rebuilt = make_candidate(
        ticket,
        analyses,
        report,
        now,
        settings,
        candidate.user_id,
        candidate.payout.stake_usd,
        candidate_id=candidate.candidate_id,
        state=candidate.state,
    )
    ranking = dict(rebuilt.ranking)
    ranking.update({k: v for k, v in candidate.ranking.items() if k.startswith("reservation")})
    codes = _dedupe([*rebuilt.reason_codes, *codes])
    book_quote = candidate.book_quote
    payout = rebuilt.payout
    ev = rebuilt.ev_per_dollar
    notes: list[str] = [f"Revalidated at {to_display(now)}."]

    if started:
        state = S.CandidateState.EXPIRED
        notes.append("A game in this ticket has started; the candidate is EXPIRED.")
    elif postponed:
        state = S.CandidateState.REJECTED
        notes.append("A game in this ticket is postponed or cancelled; the candidate is REJECTED.")
    elif gone:
        state = S.CandidateState.REJECTED
        codes.append("MARKET_SUSPENDED")
        notes.append("Quote no longer offered for: " + "; ".join(gone) + ". The candidate is REJECTED.")
    elif unusable:
        state = S.CandidateState.REJECTED
        notes.append("Leg(s) now unusable: " + "; ".join(unusable) + ". The candidate is REJECTED.")
    elif changes:
        state = S.CandidateState.NEEDS_BOOK_QUOTE
        notes.append(PRICE_CHANGED_REASON + ": " + "; ".join(changes) + ".")
        if book_quote is not None:
            book_quote = _unresolved_book_quote(book_quote)
    elif waiting:
        state = S.CandidateState.NEEDS_BOOK_QUOTE
        codes.append("WAIT_FOR_UPDATE")
        notes.append("Leg(s) waiting for an update: " + "; ".join(waiting) + ".")
    else:
        quote_ok = (
            book_quote is not None
            and book_quote.confirmed_by_user
            and not (BLOCKING_UNRESOLVED_FIELDS & set(book_quote.unresolved_fields))
        )
        if quote_ok and book_quote is not None:
            state = S.CandidateState.READY_FOR_USER_REVIEW
            payout = probabilities.payout_math(
                candidate.payout.stake_usd, book_quote.combined_decimal, "BOOK_QUOTE"
            )
            ev = (
                probabilities.ev_per_dollar(rebuilt.p_joint, book_quote.combined_decimal)
                if rebuilt.p_joint is not None
                else None
            )
            codes.append("QUOTE_REPLACES_INDICATIVE")
            notes.append("Prices unchanged; the confirmed book quote still applies.")
        else:
            state = S.CandidateState.NEEDS_BOOK_QUOTE
            notes.append("Prices unchanged; import the Hard Rock combined quote to proceed.")
    return rebuild_candidate(
        rebuilt,
        created_at_utc=candidate.created_at_utc,
        state=state,
        book_quote=book_quote,
        payout=payout,
        ev_per_dollar=ev,
        reason_codes=_dedupe(codes),
        ranking=ranking,
        rationale=rebuilt.rationale + "\n" + " ".join(notes),
        inputs_snapshot_utc=now,
        updated_at_utc=now,
    )


# --------------------------------------------------------------------------------------
# User ticket
# --------------------------------------------------------------------------------------


def _ticket_error(exc: ValueError) -> InvalidInput:
    text = str(exc)
    for code in ("NOT_THREE_LEGS", "DUPLICATE_SELECTION"):
        if code in text:
            return InvalidInput(text.splitlines()[0], [code])
    return InvalidInput(text.splitlines()[0], ["INVALID_INPUT"])


def analyze_user_ticket(
    inputs: Sequence[S.ManualSelectionInput],
    combined: S.ManualQuoteInput | None,
    slate: Sequence[S.Event],
    refs: Sequence[S.MarketQuote],
    injuries: Sequence[S.InjuryContext],
    now: datetime,
    settings: Settings,
    user_id: str,
    stake_usd: Decimal | None = None,
    *,
    clock: Clock | None = None,
    analyses: Mapping[str, S.LegAnalysis] | None = None,
) -> S.Candidate:
    """One candidate for the user's own three legs (MANUAL_INPUT quotes matched to ``slate``).

    Rejects anything that is not exactly three distinct, combinable legs (NOT_THREE_LEGS,
    DUPLICATE_SELECTION, CONTRADICTORY_SELECTION, NESTED_SELECTION, MUTUALLY_EXCLUSIVE_SELECTION,
    PERIOD_UNSUPPORTED). A same-game or mixed ticket is qualitative: ``p_joint`` is None, the model state is
    INSUFFICIENT_EVIDENCE and the rationale explains the missing numerical evidence. ``combined`` is applied
    through :func:`review_book_quote` when given.
    """
    if len(inputs) != 3:
        raise InvalidInput(
            f"a ticket must contain exactly three selections ({len(inputs)} given)", ["NOT_THREE_LEGS"]
        )
    selections = manual.selections_from_inputs(
        list(inputs), list(slate), clock or FixedClock(now), target_book=settings.target_book
    )
    hard = correlation.hard_rejections(selections)
    if hard:
        raise InvalidInput("these selections cannot be combined into one parlay: " + ", ".join(hard), hard)
    try:
        ticket = S.ThreeLegTicket(legs=selections)
    except ValueError as exc:
        raise _ticket_error(exc) from None
    if analyses is None:
        analyses = {s.selection_id: analyze_leg(s, refs, injuries, now, settings) for s in selections}
    report = correlation.check_correlation(ticket)
    stake = stake_usd if stake_usd is not None else settings.daily_cap_usd_default
    candidate = make_candidate(ticket, analyses, report, now, settings, user_id, stake)
    if combined is not None:
        candidate, codes = review_book_quote(candidate, combined, now, settings)
        if "QUOTE_FIELDS_MISSING" in codes:
            raise InvalidInput(
                "combined odds need combined_decimal or combined_american", ["QUOTE_FIELDS_MISSING"]
            )
    return candidate
