"""Team, player, and event identity plus selection building and reference pairing.

docs/ARCHITECTURE.md section 5 ("normalization.py"). Rules that matter for money:

- Teams resolve only through the explicit alias table below. Nothing fuzzy; an unknown or ambiguous name
  raises ``InvalidInput`` with ``TEAM_UNMATCHED`` (for example "LA" alone, which could be either club).
- Player ids are name slugs ("player:jalen-brunson") because The Odds API carries no player ids. A slug is an
  identity *claim*, not a verified identity; settlement providers must confirm it against a roster source.
- A reference two-way is only built from BOTH sides of ONE book at ONE snapshot (identical
  ``source_timestamp_utc``) on the SAME line (complementary handicaps for spreads). Otherwise the caller
  gets ``None`` plus the reason codes ``REFERENCE_MISSING`` / ``REFERENCE_INCOMPLETE`` / ``LINE_MISMATCH``.
- The target book never benchmarks itself: quotes whose ``book`` equals the selection's own book are ignored
  by ``pair_reference`` even when the caller passes the combined target-plus-reference list that the
  providers return.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.errors import InvalidInput

__all__ = [
    "NBA_TEAMS",
    "TeamRecord",
    "build_selections",
    "canonical_player",
    "canonical_team",
    "describe_quote",
    "format_line",
    "match_event",
    "normalize_name",
    "pair_reference",
    "pair_reference_with_reasons",
    "player_slug",
    "selection_id_for",
    "team_by_id",
    "try_canonical_team",
]

# --------------------------------------------------------------------------------------
# Teams
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TeamRecord:
    """One NBA franchise with every spelling we accept for it."""

    abbreviation: str
    name: str
    city: str
    nickname: str
    aliases: tuple[str, ...] = ()

    @property
    def team_id(self) -> str:
        return f"nba:{self.abbreviation}"

    def to_team(self) -> S.Team:
        return S.Team(team_id=self.team_id, name=self.name, abbreviation=self.abbreviation)

    def all_names(self) -> tuple[str, ...]:
        return (self.abbreviation, self.name, self.city, self.nickname, *self.aliases)


# "LA" and "Los Angeles" are listed for both Los Angeles clubs on purpose: duplicated keys are dropped from the
# index below, so those spellings raise TEAM_UNMATCHED instead of guessing.
NBA_TEAMS: tuple[TeamRecord, ...] = (
    TeamRecord("ATL", "Atlanta Hawks", "Atlanta", "Hawks"),
    TeamRecord("BOS", "Boston Celtics", "Boston", "Celtics"),
    TeamRecord("BKN", "Brooklyn Nets", "Brooklyn", "Nets", ("BRK", "NJN")),
    TeamRecord("CHA", "Charlotte Hornets", "Charlotte", "Hornets", ("CHO",)),
    TeamRecord("CHI", "Chicago Bulls", "Chicago", "Bulls"),
    TeamRecord("CLE", "Cleveland Cavaliers", "Cleveland", "Cavaliers", ("Cavs",)),
    TeamRecord("DAL", "Dallas Mavericks", "Dallas", "Mavericks", ("Mavs",)),
    TeamRecord("DEN", "Denver Nuggets", "Denver", "Nuggets"),
    TeamRecord("DET", "Detroit Pistons", "Detroit", "Pistons"),
    TeamRecord("GSW", "Golden State Warriors", "Golden State", "Warriors", ("GS", "Dubs")),
    TeamRecord("HOU", "Houston Rockets", "Houston", "Rockets"),
    TeamRecord("IND", "Indiana Pacers", "Indiana", "Pacers"),
    TeamRecord(
        "LAC",
        "LA Clippers",
        "Los Angeles",
        "Clippers",
        ("Los Angeles Clippers", "L.A. Clippers", "LA"),
    ),
    TeamRecord("LAL", "Los Angeles Lakers", "Los Angeles", "Lakers", ("LA Lakers", "L.A. Lakers", "LA")),
    TeamRecord("MEM", "Memphis Grizzlies", "Memphis", "Grizzlies", ("Grizz",)),
    TeamRecord("MIA", "Miami Heat", "Miami", "Heat"),
    TeamRecord("MIL", "Milwaukee Bucks", "Milwaukee", "Bucks"),
    TeamRecord("MIN", "Minnesota Timberwolves", "Minnesota", "Timberwolves", ("Wolves", "T-Wolves")),
    TeamRecord("NOP", "New Orleans Pelicans", "New Orleans", "Pelicans", ("NO", "NOLA", "Pels")),
    TeamRecord("NYK", "New York Knicks", "New York", "Knicks", ("NY",)),
    TeamRecord("OKC", "Oklahoma City Thunder", "Oklahoma City", "Thunder"),
    TeamRecord("ORL", "Orlando Magic", "Orlando", "Magic"),
    TeamRecord("PHI", "Philadelphia 76ers", "Philadelphia", "76ers", ("Sixers", "Philly")),
    TeamRecord("PHX", "Phoenix Suns", "Phoenix", "Suns", ("PHO",)),
    TeamRecord("POR", "Portland Trail Blazers", "Portland", "Trail Blazers", ("Blazers", "Trailblazers")),
    TeamRecord("SAC", "Sacramento Kings", "Sacramento", "Kings"),
    TeamRecord("SAS", "San Antonio Spurs", "San Antonio", "Spurs", ("SA",)),
    TeamRecord("TOR", "Toronto Raptors", "Toronto", "Raptors", ("Raps",)),
    TeamRecord("UTA", "Utah Jazz", "Utah", "Jazz", ("UTAH",)),
    TeamRecord("WAS", "Washington Wizards", "Washington", "Wizards", ("WSH", "Wiz")),
)

_TEAM_BY_ID: dict[str, TeamRecord] = {t.team_id: t for t in NBA_TEAMS}


def normalize_name(text: str) -> str:
    """Lowercase ASCII key: strip accents and punctuation, collapse whitespace."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).split())


def _build_team_index() -> dict[str, TeamRecord]:
    seen: dict[str, TeamRecord] = {}
    ambiguous: set[str] = set()
    for team in NBA_TEAMS:
        for alias in team.all_names():
            key = normalize_name(alias)
            if key in seen and seen[key] is not team:
                ambiguous.add(key)
            seen.setdefault(key, team)
    for key in ambiguous:
        seen.pop(key, None)
    return seen


_TEAM_INDEX: dict[str, TeamRecord] = _build_team_index()


def try_canonical_team(name: str) -> S.Team | None:
    """Return the canonical team for ``name`` or None when it is unknown or ambiguous."""
    key = normalize_name(name)
    if key.startswith("the "):
        key = key[4:]
    record = _TEAM_INDEX.get(key)
    return record.to_team() if record else None


def canonical_team(name: str) -> S.Team:
    """Resolve any accepted spelling of an NBA team; raises ``InvalidInput`` (TEAM_UNMATCHED) otherwise."""
    team = try_canonical_team(name)
    if team is None:
        raise InvalidInput(f"unknown or ambiguous NBA team: {name!r}", ["TEAM_UNMATCHED"])
    return team


def team_by_id(team_id: str) -> S.Team | None:
    """Look a team up by its canonical id (``nba:BOS``)."""
    record = _TEAM_BY_ID.get(team_id)
    return record.to_team() if record else None


# --------------------------------------------------------------------------------------
# Players
# --------------------------------------------------------------------------------------

_NAME_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})


def _first_last(name: str) -> str:
    raw = " ".join(name.split())
    if raw.count(",") == 1:
        last, first = (part.strip() for part in raw.split(","))
        if first and last:
            return f"{first} {last}"
    return raw


def player_slug(name: str) -> str:
    """NFKD -> ASCII -> lowercase -> hyphenated, generational suffixes removed ("Jaren Jackson Jr." -> "jaren-jackson")."""
    tokens = normalize_name(_first_last(name)).split()
    core = [t for t in tokens if t not in _NAME_SUFFIXES]
    return "-".join(core or tokens)


def canonical_player(name: str, team_hint: S.Team | None = None) -> S.Player:
    """Build the canonical ``Player`` for a display name ("First Last" or "Last, First").

    The id is a name slug, not a verified roster id. Raises ``InvalidInput`` (PLAYER_UNMATCHED) for blank input.
    """
    display = _first_last(name or "")
    slug = player_slug(display) if display else ""
    if not slug:
        raise InvalidInput("player name is required", ["PLAYER_UNMATCHED"])
    return S.Player(
        player_id=f"player:{slug}", name=display, team_id=team_hint.team_id if team_hint else None
    )


# --------------------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------------------

_SEPARATORS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\s*@\s*"), "away_home"),
    (re.compile(r"\s+at\s+", re.IGNORECASE), "away_home"),
    (re.compile(r"\s+vs?\.?\s+", re.IGNORECASE), "home_away"),
)


def _split_matchup(text: str) -> tuple[str, str, str] | None:
    for pattern, order in _SEPARATORS:
        parts = pattern.split(text, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            return parts[0].strip(), parts[1].strip(), order
    return None


def match_event(game_text: str, slate: Sequence[S.Event]) -> S.Event:
    """Find the slate event named by ``game_text``.

    Accepts an event_id, "AWAY @ HOME", "AWAY at HOME", "HOME vs AWAY", "AWAY@HOME" (names or abbreviations), or
    a single team when it plays exactly once in the slate. Raises ``InvalidInput`` (EVENT_UNMATCHED) when nothing
    or more than one event matches.
    """
    text = " ".join((game_text or "").split())
    if not text:
        raise InvalidInput("game is required", ["EVENT_UNMATCHED"])
    for event in slate:
        if event.event_id == text:
            return event
    split = _split_matchup(text)
    if split is not None:
        left, right, _order = split
        first, second = try_canonical_team(left), try_canonical_team(right)
        if first is None or second is None:
            raise InvalidInput(f"could not resolve both teams in {game_text!r}", ["EVENT_UNMATCHED"])
        wanted = {first.team_id, second.team_id}
        matches = [e for e in slate if {e.home_team.team_id, e.away_team.team_id} == wanted]
    else:
        team = try_canonical_team(text)
        if team is None:
            raise InvalidInput(f"could not resolve {game_text!r} to a slate game", ["EVENT_UNMATCHED"])
        matches = [e for e in slate if team.team_id in (e.home_team.team_id, e.away_team.team_id)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise InvalidInput(f"no slate game matches {game_text!r}", ["EVENT_UNMATCHED"])
    ids = ", ".join(e.event_id for e in matches)
    raise InvalidInput(f"{game_text!r} is ambiguous: {ids}", ["EVENT_UNMATCHED"])


# --------------------------------------------------------------------------------------
# Selections
# --------------------------------------------------------------------------------------

selection_id_for = S.compute_selection_id

_PERIOD_LABEL = {
    S.Period.FULL_GAME: "full game",
    S.Period.FIRST_HALF: "1st half",
    S.Period.SECOND_HALF: "2nd half",
    S.Period.FIRST_QUARTER: "1st quarter",
}
_STAT_LABEL = {
    S.MarketType.PLAYER_POINTS: "points",
    S.MarketType.PLAYER_REBOUNDS: "rebounds",
    S.MarketType.PLAYER_ASSISTS: "assists",
    S.MarketType.PLAYER_THREES: "made threes",
}


def format_line(line: Decimal | None, *, signed: bool = False) -> str:
    """ "3.5", "224.5", or "+3.5"/"-3.5" when ``signed``; trailing zeros dropped."""
    if line is None:
        return ""
    text = format(line.normalize(), "f")
    if signed and not text.startswith("-"):
        text = "+" + text
    return text


def _abbr(team: S.Team) -> str:
    return team.abbreviation or team.name


def _team_for(quote: S.MarketQuote, event: S.Event) -> S.Team | None:
    if quote.side == S.Side.HOME:
        return event.home_team
    if quote.side == S.Side.AWAY:
        return event.away_team
    if quote.team_id:
        for team in (event.home_team, event.away_team):
            if team.team_id == quote.team_id:
                return team
        return team_by_id(quote.team_id)
    return None


def describe_quote(quote: S.MarketQuote, event: S.Event) -> str:
    """Readable leg text: "DET +3.5 (full game)", "PHI/NYK over 224.5 (full game)", "Jalen Brunson over 24.5 points"."""
    period = _PERIOD_LABEL[quote.period]
    tag = f"(alternate, {period})" if quote.is_alternate else f"({period})"
    team = _team_for(quote, event)
    mt = quote.market_type
    if mt == S.MarketType.MONEYLINE:
        return f"{_abbr(team) if team else quote.side.value} moneyline {tag}"
    if mt == S.MarketType.SPREAD:
        return f"{_abbr(team) if team else quote.side.value} {format_line(quote.line, signed=True)} {tag}"
    if mt == S.MarketType.TOTAL:
        return f"{_abbr(event.away_team)}/{_abbr(event.home_team)} {quote.side.value.lower()} {format_line(quote.line)} {tag}"
    if mt == S.MarketType.TEAM_TOTAL:
        who = _abbr(team) if team else "team"
        return f"{who} team total {quote.side.value.lower()} {format_line(quote.line)} {tag}"
    player = quote.player_name_raw or quote.player_id or "player"
    text = f"{player} {quote.side.value.lower()} {format_line(quote.line)} {_STAT_LABEL[mt]}"
    if quote.is_alternate or quote.period != S.Period.FULL_GAME:
        text += f" {tag}"
    return text


def build_selections(
    quotes: Iterable[S.MarketQuote],
    events: Mapping[str, S.Event] | Sequence[S.Event],
    *,
    strict: bool = False,
) -> list[S.Selection]:
    """Attach each quote to its event and produce ``Selection`` objects with deterministic ids.

    Quotes whose event is not in ``events`` are skipped, or rejected with EVENT_UNMATCHED when ``strict``.
    """
    index: Mapping[str, S.Event] = events if isinstance(events, Mapping) else {e.event_id: e for e in events}
    out: list[S.Selection] = []
    for quote in quotes:
        event = index.get(quote.event_id)
        if event is None:
            if strict:
                raise InvalidInput(
                    f"quote {quote.quote_id} references unknown event {quote.event_id}", ["EVENT_UNMATCHED"]
                )
            continue
        team = _team_for(quote, event) if quote.market_type in S.TEAM_MARKETS else None
        player = None
        if quote.market_type in S.PLAYER_MARKETS:
            name = quote.player_name_raw or (quote.player_id or "").removeprefix("player:").replace("-", " ")
            player = S.Player(
                player_id=quote.player_id or f"player:{player_slug(name)}", name=name, team_id=quote.team_id
            )
        out.append(
            S.Selection(
                selection_id=selection_id_for(quote),
                quote=quote,
                event=event,
                team=team,
                player=player,
                description=describe_quote(quote, event),
            )
        )
    return out


# --------------------------------------------------------------------------------------
# Reference pairing
# --------------------------------------------------------------------------------------


def _subject_key(quote: S.MarketQuote) -> tuple[str, str]:
    """What must agree between a target quote and a reference quote beyond event/market/period."""
    if quote.market_type in S.PLAYER_MARKETS:
        if quote.player_id:
            return ("player", quote.player_id)
        return ("player", "player:" + player_slug(quote.player_name_raw or ""))
    if quote.market_type == S.MarketType.TEAM_TOTAL:
        return ("team", quote.team_id or "")
    return ("event", "")


def _target_line(quote: S.MarketQuote) -> Decimal | None:
    """The HOME handicap (spreads) or the threshold the reference pair must carry."""
    if quote.market_type == S.MarketType.MONEYLINE or quote.line is None:
        return None
    if quote.market_type == S.MarketType.SPREAD and quote.side == S.Side.AWAY:
        return -quote.line
    return quote.line


@dataclass(slots=True)
class _Pair:
    line: Decimal | None
    a: S.MarketQuote  # HOME or OVER
    b: S.MarketQuote  # AWAY or UNDER


def _complete_pairs(market: S.MarketType, quotes: Sequence[S.MarketQuote]) -> list[_Pair]:
    team_market = market in (S.MarketType.MONEYLINE, S.MarketType.SPREAD)
    side_a, side_b = (S.Side.HOME, S.Side.AWAY) if team_market else (S.Side.OVER, S.Side.UNDER)
    a_by_line: dict[Decimal | None, S.MarketQuote] = {}
    b_by_line: dict[Decimal | None, S.MarketQuote] = {}
    for q in quotes:
        if q.side == side_a:
            a_by_line.setdefault(q.line, q)
        elif q.side == side_b:
            b_by_line.setdefault(q.line, q)
    pairs: list[_Pair] = []
    for line, qa in a_by_line.items():
        if market == S.MarketType.SPREAD:
            if line is None:
                continue
            qb = b_by_line.get(-line)
        else:
            qb = b_by_line.get(line)
        if qb is not None:
            pairs.append(_Pair(line=line, a=qa, b=qb))
    return pairs


def pair_reference_with_reasons(
    selection: S.Selection,
    reference_quotes: Iterable[S.MarketQuote],
    preferred_books: Sequence[str] | None = None,
) -> tuple[S.ReferenceTwoWay | None, list[str]]:
    """Find both sides of the selection's market at one reference book in one snapshot on the same line.

    Returns ``(reference, [])`` on success. Otherwise ``(None, reasons)`` where reasons are drawn from
    REFERENCE_MISSING (nothing for this event/market/subject), LINE_MISMATCH (no reference quote at the
    selection's line) and REFERENCE_INCOMPLETE (a quote at the line exists but its opposite side is missing or
    comes from a different snapshot).

    Quotes from the selection's own book (``selection.quote.book``) are never candidates, so passing the
    providers' combined target-plus-reference list is safe: the target price is never its own "fair" price.
    """
    target = selection.quote
    subject = _subject_key(target)
    candidates = [
        r
        for r in reference_quotes
        if r.book != target.book
        and r.event_id == target.event_id
        and r.market_type == target.market_type
        and r.period == target.period
        and _subject_key(r) == subject
    ]
    if not candidates:
        return None, ["REFERENCE_MISSING"]
    wanted = _target_line(target)
    snapshots: dict[tuple[str, str], list[S.MarketQuote]] = {}
    for r in candidates:
        ts = r.stamp.source_timestamp_utc.isoformat() if r.stamp.source_timestamp_utc else ""
        snapshots.setdefault((r.book, ts), []).append(r)
    matching: list[tuple[str, str, _Pair]] = []
    any_pair = False
    for (book, ts), quotes in snapshots.items():
        for pair in _complete_pairs(target.market_type, quotes):
            any_pair = True
            if pair.line == wanted:
                matching.append((book, ts, pair))
    if matching:
        # Preferred book first (settings.reference_books order); within that book, the newest snapshot.
        order = {book: i for i, book in enumerate(preferred_books or [])}
        best_rank = min(order.get(book, len(order)) for book, _ts, _pair in matching)
        same_book = [m for m in matching if order.get(m[0], len(order)) == best_rank]
        book, _ts, pair = max(same_book, key=lambda m: m[1])
        ref = S.ReferenceTwoWay(
            book=book,
            event_id=target.event_id,
            market_type=target.market_type,
            period=target.period,
            player_id=pair.a.player_id or target.player_id,
            line=pair.line,
            side_a=pair.a.side,
            odds_a=pair.a.odds_decimal,
            side_b=pair.b.side,
            odds_b=pair.b.odds_decimal,
            stamp=pair.a.stamp,
        )
        return ref, []
    reasons: list[str] = []
    at_line = [r for r in candidates if _target_line(r) == wanted or r.line == wanted]
    if not at_line:
        reasons.append("LINE_MISMATCH")
        if not any_pair:
            reasons.append("REFERENCE_INCOMPLETE")
    else:
        reasons.append("REFERENCE_INCOMPLETE")
    return None, reasons


def pair_reference(
    selection: S.Selection,
    reference_quotes: Iterable[S.MarketQuote],
    preferred_books: Sequence[str] | None = None,
) -> S.ReferenceTwoWay | None:
    """``pair_reference_with_reasons`` without the reasons (contract signature)."""
    ref, _ = pair_reference_with_reasons(selection, reference_quotes, preferred_books)
    return ref
