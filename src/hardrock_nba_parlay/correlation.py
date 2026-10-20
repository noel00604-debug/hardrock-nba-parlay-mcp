"""Combinability and correlation checks for exactly-three-leg tickets (docs/ARCHITECTURE.md section 5).

Two layers:

1. ``hard_rejections`` - reason codes that make a set of legs unplayable as one parlay. It works on a plain
   list of ``Selection`` (before a ``ThreeLegTicket`` exists) or on a ticket. Codes: NOT_THREE_LEGS,
   DUPLICATE_SELECTION, CONTRADICTORY_SELECTION, NESTED_SELECTION, MUTUALLY_EXCLUSIVE_SELECTION,
   PERIOD_UNSUPPORTED.
2. ``check_correlation`` - a ``CorrelationReport`` for a valid ticket. Shared-game dependence is flagged, and
   any shared event is BLOCKING for a numeric joint estimate: there is no validated joint model here, so
   marginals are never multiplied for same-game legs. Nothing here guesses a correlation coefficient.

Games are identified by ``event_id``. When two different event ids describe the same matchup (the same game
present once from the provider and once from a manual import), those legs are additionally treated as one
game: the same two teams meet at most once per slate, so independence between them cannot be assumed.

``leg_indexes`` in every flag are 0-based positions in ``ticket.legs``. Explanations name legs by their
``description`` so a reader does not need the indexes.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from itertools import combinations

from hardrock_nba_parlay import schemas as S

HARD_FLAG_REASON_CODES: dict[S.CorrelationType, str] = {
    S.CorrelationType.DUPLICATE: "DUPLICATE_SELECTION",
    S.CorrelationType.CONTRADICTORY: "CONTRADICTORY_SELECTION",
    S.CorrelationType.NESTED: "NESTED_SELECTION",
    S.CorrelationType.MUTUALLY_EXCLUSIVE: "MUTUALLY_EXCLUSIVE_SELECTION",
}
_REJECTION_ORDER: tuple[str, ...] = (
    "NOT_THREE_LEGS",
    "DUPLICATE_SELECTION",
    "CONTRADICTORY_SELECTION",
    "NESTED_SELECTION",
    "MUTUALLY_EXCLUSIVE_SELECTION",
    "PERIOD_UNSUPPORTED",
)
_SEVERITY_RANK: dict[S.Severity, int] = {S.Severity.BLOCKING: 0, S.Severity.WARNING: 1, S.Severity.INFO: 2}

WEAKEST_ASSUMPTION_MULTI_GAME = "independence across games is assumed, not demonstrated"
WEAKEST_ASSUMPTION_SAME_GAME = "joint outcome depends on shared game state (pace, minutes, score margin) that no validated model here quantifies"
SAME_GAME_UNQUANTIFIED_EXPLANATION = "no validated joint model; marginals cannot be multiplied"
MATCHUP_COLLISION_EXPLANATION = (
    "the same two teams meet at most once per slate, so these legs are treated as one game"
)

_SCORING_MARKETS: frozenset[S.MarketType] = frozenset(
    {S.MarketType.PLAYER_POINTS, S.MarketType.PLAYER_THREES}
)
_ZERO = Decimal(0)


# --------------------------------------------------------------------------------------
# Keys
# --------------------------------------------------------------------------------------


def _legs_of(legs: Sequence[S.Selection] | S.ThreeLegTicket) -> list[S.Selection]:
    if isinstance(legs, S.ThreeLegTicket):
        return list(legs.legs)
    return list(legs)


def _fmt_line(line: Decimal | None) -> str:
    return "" if line is None else format(line.normalize(), "f")


def _player_key(sel: S.Selection) -> str | None:
    """Stable identity of the player behind a prop leg (None for team markets)."""
    q = sel.quote
    if q.market_type not in S.PLAYER_MARKETS:
        return None
    raw = q.player_id or (sel.player.player_id if sel.player is not None else None) or q.player_name_raw or ""
    return raw.strip().lower() or None


def _team_key(sel: S.Selection) -> str | None:
    """Team behind a prop or team-total leg when known (quote, then player, then selection.team)."""
    q = sel.quote
    if q.team_id:
        return q.team_id
    if sel.player is not None and sel.player.team_id:
        return sel.player.team_id
    if sel.team is not None:
        return sel.team.team_id
    return None


def _subject(sel: S.Selection) -> str:
    """What the market is about: the player for props, the team for team totals, the game otherwise.

    MONEYLINE/SPREAD/TOTAL deliberately use an empty subject: HOME and AWAY are sides of ONE market, and the
    contradictory/nested checks must see them together even though their team_ids differ.
    """
    q = sel.quote
    if q.market_type in S.PLAYER_MARKETS:
        return _player_key(sel) or ""
    if q.market_type == S.MarketType.TEAM_TOTAL:
        return _team_key(sel) or ""
    return ""


def _market_key(sel: S.Selection) -> tuple[str, str, str, str]:
    q = sel.quote
    return (q.event_id, q.market_type.value, q.period.value, _subject(sel))


def _outcome_key(sel: S.Selection) -> tuple[str, str, str, str, str, str]:
    q = sel.quote
    return (*_market_key(sel), q.side.value, _fmt_line(q.line))


def _matchup_key(event: S.Event) -> tuple[str, str]:
    """The two teams of a game, independent of which source assigned the event id."""
    return (event.away_team.team_id, event.home_team.team_id)


def _matchup_collisions(legs: Sequence[S.Selection]) -> list[tuple[str, list[str]]]:
    """``(short_name, [event_ids])`` for every matchup that appears under two or more event ids."""
    ids_by_matchup: dict[tuple[str, str], dict[str, None]] = defaultdict(dict)
    name_by_matchup: dict[tuple[str, str], str] = {}
    for leg in legs:
        key = _matchup_key(leg.event)
        ids_by_matchup[key][leg.event.event_id] = None  # insertion-ordered set
        name_by_matchup.setdefault(key, leg.event.short_name)
    return [(name_by_matchup[key], list(ids)) for key, ids in ids_by_matchup.items() if len(ids) >= 2]


def _no_integer_strictly_between(lower: Decimal, upper: Decimal) -> bool:
    """True when no integer x satisfies lower < x < upper (NBA margins and stat counts are integers)."""
    smallest_above = lower.to_integral_value(rounding=ROUND_FLOOR) + 1
    largest_below = upper.to_integral_value(rounding=ROUND_CEILING) - 1
    return smallest_above > largest_below


def _flag(
    kind: S.CorrelationType, idx: Sequence[int], severity: S.Severity, explanation: str
) -> S.CorrelationFlag:
    return S.CorrelationFlag(type=kind, leg_indexes=list(idx), severity=severity, explanation=explanation)


# --------------------------------------------------------------------------------------
# Pairwise hard flags (duplicate / contradictory / nested / mutually exclusive)
# --------------------------------------------------------------------------------------


def _moneyline_vs_opponent_spread_flag(
    i: int, a: S.Selection, j: int, b: S.Selection
) -> S.CorrelationFlag | None:
    """MUTUALLY_EXCLUSIVE when a moneyline and the opponent's spread in one game can never both win.

    The home margin ``m`` is an integer and an NBA game cannot end level. The HOME moneyline wins iff
    ``m > 0`` and the AWAY moneyline iff ``m < 0``; a HOME spread at handicap ``h`` covers iff ``m > -h`` and
    an AWAY spread at ``s`` covers iff ``m < s`` (a push is not a win). Both legs win only for an integer ``m``
    strictly inside the resulting interval; when no such integer exists the parlay can never pay. The same
    team's moneyline and spread are never impossible together (that pair gets the soft TEAM_WIN_AND_SPREAD
    flag instead).
    """
    qa, qb = a.quote, b.quote
    if qa.event_id != qb.event_id or qa.period != qb.period:
        return None
    if {qa.market_type, qb.market_type} != {S.MarketType.MONEYLINE, S.MarketType.SPREAD}:
        return None
    if {qa.side, qb.side} != {S.Side.HOME, S.Side.AWAY}:
        return None
    ml, spread = (a, b) if qa.market_type == S.MarketType.MONEYLINE else (b, a)
    line = spread.quote.line
    if line is None:
        return None
    # HOME ML + AWAY spread: 0 < m < line.  AWAY ML + HOME spread: -line < m < 0.
    lower, upper = (_ZERO, line) if ml.quote.side == S.Side.HOME else (-line, _ZERO)
    if _no_integer_strictly_between(lower, upper):
        return _flag(
            S.CorrelationType.MUTUALLY_EXCLUSIVE,
            (i, j),
            S.Severity.BLOCKING,
            f"'{a.description}' and '{b.description}' cannot both win (no final margin lets that team win and "
            "the opponent cover); the parlay can never pay",
        )
    return None


def _hard_flag(i: int, a: S.Selection, j: int, b: S.Selection) -> S.CorrelationFlag | None:
    qa, qb = a.quote, b.quote
    pair = (i, j)
    if (
        a.selection_id == b.selection_id
        or qa.identity_tuple() == qb.identity_tuple()
        or _outcome_key(a) == _outcome_key(b)
    ):
        return _flag(
            S.CorrelationType.DUPLICATE,
            pair,
            S.Severity.BLOCKING,
            f"'{a.description}' and '{b.description}' are the same outcome; a parlay cannot include one selection twice",
        )
    if _market_key(a) != _market_key(b):
        return _moneyline_vs_opponent_spread_flag(i, a, j, b)
    market = qa.market_type
    if market == S.MarketType.MONEYLINE:
        return _flag(
            S.CorrelationType.CONTRADICTORY,
            pair,
            S.Severity.BLOCKING,
            f"'{a.description}' and '{b.description}' are both sides of the same moneyline; at most one can win",
        )
    if qa.side == qb.side:
        return _flag(
            S.CorrelationType.NESTED,
            pair,
            S.Severity.BLOCKING,
            f"'{a.description}' and '{b.description}' are the same side of one market at different lines; "
            "one implies the other, so this is one bet priced twice, not two legs",
        )
    # Opposite sides of one market.
    if market == S.MarketType.SPREAD:
        home_leg, away_leg = (a, b) if qa.side == S.Side.HOME else (b, a)
        home_line, away_line = home_leg.quote.line, away_leg.quote.line
        if home_line is None or away_line is None:
            return None
        if home_line == -away_line:
            return _flag(
                S.CorrelationType.CONTRADICTORY,
                pair,
                S.Severity.BLOCKING,
                f"'{a.description}' and '{b.description}' are complementary handicaps of the same spread; at most one can win",
            )
        lower, upper = -home_line, away_line  # home margin must satisfy lower < m < upper for both to win
    else:
        over_leg, under_leg = (a, b) if qa.side == S.Side.OVER else (b, a)
        over_line, under_line = over_leg.quote.line, under_leg.quote.line
        if over_line is None or under_line is None:
            return None
        if over_line == under_line:
            return _flag(
                S.CorrelationType.CONTRADICTORY,
                pair,
                S.Severity.BLOCKING,
                f"'{a.description}' and '{b.description}' are over and under the same line; at most one can win",
            )
        lower, upper = over_line, under_line  # value must satisfy lower < v < upper for both to win
    if _no_integer_strictly_between(lower, upper):
        return _flag(
            S.CorrelationType.MUTUALLY_EXCLUSIVE,
            pair,
            S.Severity.BLOCKING,
            f"'{a.description}' and '{b.description}' cannot both win (no outcome satisfies both); the parlay can never pay",
        )
    return None


# --------------------------------------------------------------------------------------
# Pairwise soft flags (same event only)
# --------------------------------------------------------------------------------------


def _soft_pair_flags(i: int, a: S.Selection, j: int, b: S.Selection) -> list[S.CorrelationFlag]:
    qa, qb = a.quote, b.quote
    if qa.event_id != qb.event_id:
        return []
    out: list[S.CorrelationFlag] = []
    pair = (i, j)
    markets = {qa.market_type, qb.market_type}
    same_side = qa.side == qb.side
    direction = qa.side.value.lower()
    pa, pb = _player_key(a), _player_key(b)
    names = f"'{a.description}' and '{b.description}'"

    if pa is not None and pa == pb and markets == _SCORING_MARKETS and same_side:
        out.append(
            _flag(
                S.CorrelationType.SAME_PLAYER_POINTS_THREES,
                pair,
                S.Severity.WARNING,
                f"{names}: the same player's points and threes move together (made threes are points), so both "
                f"{direction}s are one hot-or-cold outcome, not two independent legs",
            )
        )
    if (
        markets == {S.MarketType.PLAYER_ASSISTS, S.MarketType.PLAYER_POINTS}
        and pa
        and pb
        and pa != pb
        and same_side
    ):
        ta, tb = _team_key(a), _team_key(b)
        if ta is not None and ta == tb:
            out.append(
                _flag(
                    S.CorrelationType.ASSISTS_AND_TEAMMATE_POINTS,
                    pair,
                    S.Severity.WARNING,
                    f"{names}: a teammate's made baskets are what produce assists, so these {direction}s depend "
                    "on the same possessions and the same offensive flow",
                )
            )
    if markets == {S.MarketType.MONEYLINE, S.MarketType.SPREAD} and same_side:
        out.append(
            _flag(
                S.CorrelationType.TEAM_WIN_AND_SPREAD,
                pair,
                S.Severity.WARNING,
                f"{names}: the moneyline and the spread on the same team are nested-like outcomes (covering usually "
                "implies winning or vice versa); the book prices them as one correlated bet, not two",
            )
        )
    if (markets & _SCORING_MARKETS) and S.MarketType.TOTAL in markets and same_side:
        out.append(
            _flag(
                S.CorrelationType.PLAYER_SCORING_AND_GAME_TOTAL,
                pair,
                S.Severity.WARNING,
                f"{names}: a player's scoring is part of the game total, so both {direction}s lean on the same "
                "pace and shooting outcome",
            )
        )
    if (qa.market_type in S.PLAYER_MARKETS and qb.market_type == S.MarketType.SPREAD) or (
        qb.market_type in S.PLAYER_MARKETS and qa.market_type == S.MarketType.SPREAD
    ):
        out.append(
            _flag(
                S.CorrelationType.SHARED_BLOWOUT_SENSITIVITY,
                pair,
                S.Severity.INFO,
                f"{names}: a blowout changes both the spread result and starters' fourth-quarter minutes, so the "
                "prop and the spread share score-margin risk",
            )
        )
    return out


# --------------------------------------------------------------------------------------
# Group flags (per event, then per matchup)
# --------------------------------------------------------------------------------------


def _group_flags(legs: Sequence[S.Selection]) -> list[S.CorrelationFlag]:
    by_event: dict[str, list[int]] = defaultdict(list)
    for i, leg in enumerate(legs):
        by_event[leg.event.event_id].append(i)
    out: list[S.CorrelationFlag] = []
    for idxs in by_event.values():
        if len(idxs) < 2:
            continue
        game = legs[idxs[0]].event.short_name
        overs = [i for i in idxs if legs[i].quote.side == S.Side.OVER]
        if len(overs) >= 2:
            names = ", ".join(f"'{legs[i].description}'" for i in overs)
            out.append(
                _flag(
                    S.CorrelationType.MULTIPLE_OVERS_SHARED_PACE,
                    overs,
                    S.Severity.WARNING,
                    f"{names} are all overs in {game}; they share one game's pace, foul rate, and overtime chance",
                )
            )
        by_team: dict[str, list[int]] = defaultdict(list)
        for i in idxs:
            if legs[i].quote.market_type in S.PLAYER_MARKETS:
                key = _team_key(legs[i]) or (
                    f"player:{_player_key(legs[i])}" if _player_key(legs[i]) else None
                )
                if key:
                    by_team[key].append(i)
        for tidx in by_team.values():
            if len(tidx) >= 2:
                names = ", ".join(f"'{legs[i].description}'" for i in tidx)
                out.append(
                    _flag(
                        S.CorrelationType.SHARED_MINUTES_OR_INJURY,
                        tidx,
                        S.Severity.WARNING,
                        f"{names} are props on the same team in {game}; one rotation change, foul-trouble spell, "
                        "late scratch, or blowout rest decision moves all of them at once (minutes/injury dependence)",
                    )
                )
        names = ", ".join(f"'{legs[i].description}'" for i in idxs)
        out.append(
            _flag(
                S.CorrelationType.SAME_GAME_UNQUANTIFIED,
                idxs,
                S.Severity.BLOCKING,
                f"{names} share {game}: {SAME_GAME_UNQUANTIFIED_EXPLANATION}",
            )
        )
    return out


def _matchup_flags(legs: Sequence[S.Selection]) -> list[S.CorrelationFlag]:
    """BLOCKING SAME_GAME_UNQUANTIFIED for legs whose events are one matchup under two or more event ids.

    ``_group_flags`` keys by ``event_id``; this catches the same game imported twice (provider id plus manual
    id), which would otherwise look like two independent games.
    """
    by_matchup: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, leg in enumerate(legs):
        by_matchup[_matchup_key(leg.event)].append(i)
    out: list[S.CorrelationFlag] = []
    for idxs in by_matchup.values():
        event_ids = sorted({legs[i].event.event_id for i in idxs})
        if len(event_ids) < 2:
            continue
        game = legs[idxs[0]].event.short_name
        names = ", ".join(f"'{legs[i].description}'" for i in idxs)
        out.append(
            _flag(
                S.CorrelationType.SAME_GAME_UNQUANTIFIED,
                idxs,
                S.Severity.BLOCKING,
                f"{names} are all on {game} under different event ids ({', '.join(event_ids)}); "
                f"{MATCHUP_COLLISION_EXPLANATION}: {SAME_GAME_UNQUANTIFIED_EXPLANATION}",
            )
        )
    return out


def _all_flags(legs: Sequence[S.Selection]) -> list[S.CorrelationFlag]:
    flags: list[S.CorrelationFlag] = []
    for (i, a), (j, b) in combinations(enumerate(legs), 2):
        hard = _hard_flag(i, a, j, b)
        if hard is not None:
            flags.append(hard)
            continue
        flags.extend(_soft_pair_flags(i, a, j, b))
    flags.extend(_group_flags(legs))
    flags.extend(_matchup_flags(legs))
    flags.sort(key=lambda f: _SEVERITY_RANK[f.severity])  # stable: keeps discovery order within a severity
    return flags


# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------


def hard_rejections(legs: Sequence[S.Selection] | S.ThreeLegTicket) -> list[str]:
    """Reason codes that make these legs unplayable as one parlay (empty list when combinable).

    Works on a plain list of selections before a ``ThreeLegTicket`` is built, or on a ticket. Codes, in
    this order when present: NOT_THREE_LEGS, DUPLICATE_SELECTION, CONTRADICTORY_SELECTION, NESTED_SELECTION,
    MUTUALLY_EXCLUSIVE_SELECTION, PERIOD_UNSUPPORTED.

    - DUPLICATE: same selection_id, same identity tuple, or the same outcome (event, market, period, subject,
      side, line) even when book or is_alternate differ.
    - CONTRADICTORY: both sides of one moneyline; complementary spread handicaps; over and under the same line.
    - NESTED: same side of one market at different lines (over 20.5 and over 24.5; DET +3.5 and DET +5.5).
    - MUTUALLY_EXCLUSIVE: opposite sides of one market that no integer outcome satisfies together
      (over 25.5 with under 24.5; HOME +3.5 with AWAY -5.5), or a team's moneyline with the opponent's spread
      that no final margin satisfies together (HOME ML with AWAY -3.5; HOME ML with AWAY +3.5 is a legal
      middle that wins by 1 to 3).
    - PERIOD_UNSUPPORTED: any leg whose period is not FULL_GAME.
    """
    items = _legs_of(legs)
    found: set[str] = set()
    if len(items) != 3:
        found.add("NOT_THREE_LEGS")
    if any(leg.quote.period not in S.SUPPORTED_PERIODS for leg in items):
        found.add("PERIOD_UNSUPPORTED")
    for (i, a), (j, b) in combinations(enumerate(items), 2):
        hard = _hard_flag(i, a, j, b)
        if hard is not None:
            found.add(HARD_FLAG_REASON_CODES[hard.type])
    return [code for code in _REJECTION_ORDER if code in found]


def describe_parlay_type(ticket: S.ThreeLegTicket) -> str:
    """One readable sentence explaining the ticket's parlay type and what it implies for the math.

    Games are keyed by ``event_id`` exactly as ``ThreeLegTicket.parlay_type`` is derived, so a MIXED ticket whose
    two event ids render to the same matchup name still describes cleanly; such a collision is called out,
    because the same two teams meet at most once per slate and the legs are then treated as one game.
    """
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    for leg in ticket.legs:
        eid = leg.event.event_id
        counts[eid] = counts.get(eid, 0) + 1
        names.setdefault(eid, leg.event.short_name)
    collisions = _matchup_collisions(ticket.legs)
    collision_text = "; ".join(
        f"event ids {' and '.join(repr(e) for e in ids)} both describe {game}" for game, ids in collisions
    )
    if ticket.parlay_type == S.ParlayType.MULTI_GAME:
        if collisions:
            return (
                f"MULTI_GAME by event id (three event ids), but {collision_text}; "
                f"{MATCHUP_COLLISION_EXPLANATION}, so no numeric joint estimate is produced."
            )
        return (
            f"MULTI_GAME: three legs from three different games ({', '.join(names.values())}). Outcomes are "
            "treated as independent across games; that is an assumption, not a validated fact."
        )
    if ticket.parlay_type == S.ParlayType.SAME_GAME:
        return (
            f"SAME_GAME: all three legs come from one game ({next(iter(names.values()))}). The legs share game "
            "state (pace, minutes, score margin) and no validated joint model exists here, so their marginals "
            "cannot be multiplied."
        )
    shared = next(eid for eid, n in counts.items() if n >= 2)
    other = next(eid for eid, n in counts.items() if n == 1)
    if collisions:
        return (
            f"MIXED by event id: two legs share event {shared!r} and the third is on event {other!r}, but "
            f"{collision_text}; {MATCHUP_COLLISION_EXPLANATION}, so all three legs are treated as one game and "
            "no numeric joint estimate is produced."
        )
    return (
        f"MIXED: two legs share one game ({names[shared]}) and the third is from another game ({names[other]}). "
        "The shared-game pair cannot be multiplied without a validated joint model, so no numeric joint "
        "estimate is produced."
    )


def check_correlation(ticket: S.ThreeLegTicket) -> S.CorrelationReport:
    """Correlation report for a valid ticket.

    Flags: SAME_PLAYER_POINTS_THREES, ASSISTS_AND_TEAMMATE_POINTS, TEAM_WIN_AND_SPREAD,
    PLAYER_SCORING_AND_GAME_TOTAL, MULTIPLE_OVERS_SHARED_PACE, SHARED_MINUTES_OR_INJURY (WARNING);
    SHARED_BLOWOUT_SENSITIVITY (INFO); SAME_GAME_UNQUANTIFIED plus DUPLICATE/NESTED/CONTRADICTORY/
    MUTUALLY_EXCLUSIVE (BLOCKING). ``joint_numeric_allowed`` is True only when no two legs share an event, no
    two event ids describe the same matchup, and no flag is BLOCKING. ``weakest_assumption`` names the
    assumption the ticket rests on.
    """
    legs = list(ticket.legs)
    flags = _all_flags(legs)
    shares_event = len(set(ticket.event_ids)) < len(legs)
    shares_matchup = bool(_matchup_collisions(legs))
    blocking = [f for f in flags if f.severity == S.Severity.BLOCKING]
    allowed = not shares_event and not shares_matchup and not blocking
    weakest = (
        WEAKEST_ASSUMPTION_MULTI_GAME
        if ticket.parlay_type == S.ParlayType.MULTI_GAME and not shares_matchup
        else WEAKEST_ASSUMPTION_SAME_GAME
    )

    lines = [describe_parlay_type(ticket)]
    if flags:
        lines.append(f"{len(flags)} correlation flag(s):")
        lines.extend(f"- {f.type.value} [{f.severity.value}]: {f.explanation}" for f in flags)
    else:
        lines.append("No correlation flags: no two legs share a game, player, or team market.")
    hard = [f for f in blocking if f.type in HARD_FLAG_REASON_CODES]
    if hard:
        lines.append(
            "This ticket is not combinable: " + ", ".join(HARD_FLAG_REASON_CODES[f.type] for f in hard) + "."
        )
    if allowed:
        lines.append(
            "Numeric joint estimate: allowed as the product of the three marginals (independence across games assumed, not validated)."
        )
    else:
        lines.append(
            "Numeric joint estimate: not allowed; the report returns no joint probability for this ticket."
        )
    lines.append(f"Weakest assumption: {weakest}.")
    return S.CorrelationReport(
        flags=flags, joint_numeric_allowed=allowed, weakest_assumption=weakest, explanation="\n".join(lines)
    )


__all__ = [
    "HARD_FLAG_REASON_CODES",
    "MATCHUP_COLLISION_EXPLANATION",
    "SAME_GAME_UNQUANTIFIED_EXPLANATION",
    "WEAKEST_ASSUMPTION_MULTI_GAME",
    "WEAKEST_ASSUMPTION_SAME_GAME",
    "check_correlation",
    "describe_parlay_type",
    "hard_rejections",
]
