"""Leg analysis and bounded exactly-three-leg candidate construction (pipeline module).

Rules this module enforces (docs/ARCHITECTURE.md sections 5, 7 and 11):

- A leg's probability is a MARKET_BASELINE taken from a matching two-way benchmark at a different book
  with the vig removed proportionally. When the benchmark is missing, at another line, from the target
  book itself, further than ``max_reference_skew_seconds`` from the target quote, or of unmeasurable age
  (no source timestamp on the benchmark), the probability is ``INSUFFICIENT_EVIDENCE`` and the leg says so
  (REFERENCE_MISSING / LINE_MISMATCH / TIMESTAMP_SKEW / SOURCE_TIMESTAMP_UNKNOWN ...). A typed
  (MANUAL_INPUT) quote without ``observed_at_utc`` was observed when the user typed it, so its skew is
  measured from ``received_at_utc``.
- Facts (what a source said, with its stamp) are kept apart from interpretations (what we make of it).
- The candidate search is bounded: at most ``MAX_LEGS_SEARCHED`` usable legs and ``MAX_COMBINATIONS``
  three-leg combinations. Ranking uses evidence and price edge only, never the payout size.
- Same-game and mixed tickets never get a joint probability or an expected value; they are qualitative.
- Nothing here reads a clock, the network, or the database. ``now`` is always a parameter.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from itertools import combinations
from typing import Literal

from hardrock_nba_parlay import correlation, freshness, injury_context, normalization, probabilities
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import Settings, to_display
from hardrock_nba_parlay.db import new_id

__all__ = [
    "MAX_COMBINATIONS",
    "MAX_LEGS_SEARCHED",
    "RANKING_NOTE",
    "RECHECKS_REQUIRED",
    "ParlayTypeArg",
    "SearchStats",
    "analyze_leg",
    "build_candidates",
    "candidate_data_mode",
    "make_candidate",
    "order_usable_legs",
]

ParlayTypeArg = Literal["auto", "multi_game", "same_game", "mixed"]
PARLAY_TYPE_ARGS: tuple[str, ...] = ("auto", "multi_game", "same_game", "mixed")

MAX_LEGS_SEARCHED = 24
MAX_COMBINATIONS = 2024  # C(24, 3)
RANKING_NOTE = "ranking never uses payout size"
RECHECKS_REQUIRED: tuple[str, ...] = (
    "refresh prices right before placing (refresh_parlay)",
    "confirm the combined quote Hard Rock Bet shows on the slip (import_hardrock_quote)",
    "confirm the injury status of every player and team on the latest official report",
    "confirm the slip shows the same three legs, lines, and prices as this candidate",
)

_GRADE_RANK: dict[str, int] = {"A": 0, "B": 1, "C": 2, "D": 3}
_DECISION_RANK: dict[S.LegDecision, int] = {
    S.LegDecision.USABLE: 0,
    S.LegDecision.WAIT_FOR_UPDATE: 1,
    S.LegDecision.UNUSABLE: 2,
}
# INSUFFICIENT_EVIDENCE methods that are reason codes about the benchmark, never about the selection.
_BENCHMARK_CODES: frozenset[str] = frozenset(
    {
        "REFERENCE_MISSING",
        "LINE_MISMATCH",
        "REFERENCE_INCOMPLETE",
        "TIMESTAMP_SKEW",
        "SOURCE_TIMESTAMP_UNKNOWN",
    }
)
# Mismatch methods reported from the benchmark's side: the selection identity itself was already resolved.
_BENCHMARK_SIDE_MISMATCH: frozenset[str] = frozenset({"PLAYER_UNMATCHED", "EVENT_UNMATCHED"})
_NO_EDGE = Decimal("-999")


class SearchStats:
    """Counters filled by :func:`build_candidates` (legs considered, combinations evaluated)."""

    def __init__(self) -> None:
        self.legs_considered = 0
        self.legs_usable = 0
        self.legs_searched = 0
        self.combinations_evaluated = 0
        self.combinations_rejected = 0
        self.events_with_usable_legs = 0
        self.mode: str | None = None


# --------------------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------------------


def _fmt_dec(value: Decimal | None, places: str = "0.0001") -> str:
    if value is None:
        return "n/a"
    return format(value.quantize(Decimal(places)), "f")


def _signed(value: Decimal | None) -> str:
    if value is None:
        return "n/a"
    text = format(value.quantize(Decimal("0.000001")), "f")
    return text if text.startswith("-") else "+" + text


def _ts_text(stamp: S.SourceStamp) -> str:
    ts = stamp.source_timestamp_utc
    return to_display(ts) if ts is not None else "unknown time"


def _age_seconds(stamp: S.SourceStamp, now: datetime) -> int | None:
    ts = stamp.source_timestamp_utc
    return None if ts is None else int((now - ts).total_seconds())


def _reference_skew(
    quote: S.MarketQuote, ref: S.ReferenceTwoWay, max_skew_s: int
) -> tuple[list[str], int | None]:
    """``([TIMESTAMP_SKEW] | [SOURCE_TIMESTAMP_UNKNOWN] | [], skew_seconds)`` between target and benchmark.

    A typed (MANUAL_INPUT) target without ``observed_at_utc`` was observed when the user typed it, so its
    ``received_at_utc`` is the observation time. A benchmark without a source timestamp has an unmeasurable
    skew, which never satisfies the limit.
    """
    r_ts = ref.stamp.source_timestamp_utc
    t_ts = quote.stamp.source_timestamp_utc
    if t_ts is not None:
        codes = freshness.check_reference_skew(quote, ref, max_skew_s)
        seconds = None if r_ts is None else int(abs((t_ts - r_ts).total_seconds()))
        return codes, seconds
    if r_ts is None or quote.stamp.data_mode != S.DataMode.MANUAL_INPUT:
        return ["SOURCE_TIMESTAMP_UNKNOWN"], None
    seconds = int(abs((quote.stamp.received_at_utc - r_ts).total_seconds()))
    return (["TIMESTAMP_SKEW"] if seconds > max_skew_s else []), seconds


def _dedupe(codes: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(codes))


def _entry_name(entry: S.InjuryContext) -> str:
    return entry.player_name_raw or entry.player_id or "a listed player"


def _leg_subject(selection: S.Selection) -> str:
    if selection.player is not None:
        return selection.player.name
    if selection.team is not None:
        return selection.team.abbreviation or selection.team.name
    return selection.event.short_name


# --------------------------------------------------------------------------------------
# Leg analysis
# --------------------------------------------------------------------------------------


def _identity_matched(selection: S.Selection) -> tuple[bool, str | None]:
    quote = selection.quote
    event = selection.event
    team_ids = {event.home_team.team_id, event.away_team.team_id}
    if quote.market_type in S.PLAYER_MARKETS:
        player = selection.player
        if player is None or not player.player_id or not (quote.player_id or quote.player_name_raw):
            return False, "player identity could not be resolved"
        return True, "player identity is a name slug claim, not a roster-verified id"
    if quote.market_type in (S.MarketType.MONEYLINE, S.MarketType.SPREAD):
        if selection.team is None or selection.team.team_id not in team_ids:
            return False, "team could not be matched to the event"
        if quote.team_id and quote.team_id not in team_ids:
            return False, "quote team does not belong to the event"
        return True, None
    if quote.market_type == S.MarketType.TEAM_TOTAL:
        if not quote.team_id or quote.team_id not in team_ids:
            return False, "team total without a resolvable team"
        return True, None
    return True, None


def _grade(checks: Mapping[str, bool], *, hard_fail: bool) -> str:
    """A/B/C/D from the number of failed checks; a stale target quote or an unresolved identity is always D."""
    if hard_fail:
        return "D"
    failures = sum(1 for ok in checks.values() if not ok)
    if failures == 0:
        return "A"
    if failures == 1:
        return "B"
    if failures == 2:
        return "C"
    return "D"


def _strongest_reason_against(
    selection: S.Selection,
    codes: Sequence[str],
    ref: S.ReferenceTwoWay | None,
    same_book_only: bool,
    probability: S.ProbabilityEstimate,
    price: S.PriceValue,
    entries: Sequence[S.InjuryContext],
    skew_seconds: int | None,
    now: datetime,
    settings: Settings,
) -> str:
    quote = selection.quote
    event = selection.event
    code_set = set(codes)
    if "GAME_STARTED" in code_set:
        return f"the game has already started (tip-off {to_display(event.commence_time_utc)})"
    if "GAME_POSTPONED" in code_set:
        return "the game is postponed or cancelled"
    if "PERIOD_UNSUPPORTED" in code_set:
        return "only full-game markets are supported; this leg is for another period"
    if "QUOTE_STALE" in code_set:
        age = _age_seconds(quote.stamp, now)
        return (
            f"the {quote.book} price is {age}s old, older than the {settings.max_odds_age_seconds}s limit: "
            "refresh before relying on it"
        )
    listed = {
        e.designation: e
        for e in entries
        if e.designation
        in (S.InjuryDesignation.OUT, S.InjuryDesignation.DOUBTFUL, S.InjuryDesignation.QUESTIONABLE)
    }
    if quote.market_type in S.PLAYER_MARKETS:
        for designation in (
            S.InjuryDesignation.OUT,
            S.InjuryDesignation.DOUBTFUL,
            S.InjuryDesignation.QUESTIONABLE,
        ):
            entry = next(
                (e for e in entries if e.designation == designation and e.material_to_selection), None
            )
            if entry is not None:
                return (
                    f"{_entry_name(entry)} is {designation.value.capitalize()}: participation is unresolved"
                )
    if "WAIT_FOR_UPDATE" in code_set:
        return "a team in this game has not yet submitted its injury report"
    if probability.value is None:
        if ref is None:
            if same_book_only:
                return "the only benchmark is the target book itself: no independent value check"
            return "no benchmark for this line: value unknown"
        if probability.method == "TIMESTAMP_SKEW":
            return (
                f"the {ref.book} benchmark is {skew_seconds}s away from the {quote.book} quote "
                f"(limit {settings.max_reference_skew_seconds}s): the comparison is not reliable"
            )
        if probability.method == "SOURCE_TIMESTAMP_UNKNOWN":
            return (
                f"the {ref.book} benchmark carries no source timestamp, so its distance from the "
                f"{quote.book} quote cannot be measured against the {settings.max_reference_skew_seconds}s "
                "limit: the comparison is not reliable"
            )
        return "no benchmark at this exact line and period: value unknown"
    if quote.market_type not in S.PLAYER_MARKETS and listed:
        # An unresolved teammate can move the whole market; it outranks a known, modest price gap.
        entry = next(iter(listed.values()))
        return f"teammate {_entry_name(entry)} is {entry.designation.value.capitalize()}; materiality for a team market is yours to judge"
    if price.edge_per_dollar is not None and price.edge_per_dollar < 0:
        return (
            f"{quote.book} pays {_fmt_dec(price.target_decimal)} against a {ref.book if ref else 'benchmark'} fair "
            f"price of {_fmt_dec(price.fair_decimal)}: the price is below the benchmark ({_signed(price.edge_per_dollar)} per dollar)"
        )
    if quote.is_alternate:
        return "a one-sided alternate line: alternate ladders carry a wider margin than the main line"
    if "SOURCE_TIMESTAMP_UNKNOWN" in code_set:
        return "the quote carries no source timestamp, so its freshness is unknown"
    if "INJURY_REPORT_STALE" in code_set:
        return (
            "the injury report is older than the configured maximum; a newer report may change availability"
        )
    book = ref.book if ref is not None else "the benchmark book"
    return f"benchmark is {book}'s price as relayed by the odds feed, which may be delayed"


def analyze_leg(
    selection: S.Selection,
    references: Sequence[S.MarketQuote],
    injuries: Sequence[S.InjuryContext],
    now: datetime,
    settings: Settings,
) -> S.LegAnalysis:
    """Analyse one selection against reference quotes and the injury report at ``now``.

    Pairs the benchmark with ``normalization.pair_reference_with_reasons`` (preferred books from
    ``settings``), applies the freshness and game-state checks, the injury decision, the market-baseline
    probability (downgraded to INSUFFICIENT_EVIDENCE on TIMESTAMP_SKEW or when the only benchmark is the
    target book), the price value, a data-quality grade from named checks, and a specific strongest
    reason against the leg. ``facts`` carry source stamps; ``interpretations`` are ours.
    """
    quote = selection.quote
    event = selection.event
    codes: list[str] = []
    facts: list[S.SourcedFact] = []
    interpretations: list[str] = []
    notes: list[str] = []

    # Game state and period.
    codes += freshness.check_event_not_started(event, now)
    if quote.period not in S.SUPPORTED_PERIODS:
        codes.append("PERIOD_UNSUPPORTED")

    # Target quote freshness.
    target_codes = freshness.check_quote_age(quote, now, settings.max_odds_age_seconds)
    codes += target_codes
    target_fresh = not target_codes
    facts.append(
        S.SourcedFact(
            text=(
                f"{quote.book} prices {selection.description} at {_fmt_dec(quote.odds_decimal)} "
                f"(source update {_ts_text(quote.stamp)}, received {to_display(quote.stamp.received_at_utc)})"
            ),
            stamp=quote.stamp,
        )
    )

    # Benchmark pairing (never the target book itself).
    preferred = list(
        settings.prop_reference_books if quote.market_type in S.PLAYER_MARKETS else settings.reference_books
    )
    usable_refs = [r for r in references if r.book != quote.book]
    same_book_only = (not usable_refs) and any(r.book == quote.book for r in references)
    ref, pair_codes = normalization.pair_reference_with_reasons(selection, usable_refs, preferred)
    skew_codes: list[str] = []
    skew_seconds: int | None = None
    reference_fresh = False
    if ref is not None:
        facts.append(
            S.SourcedFact(
                text=(
                    f"{ref.book} two-way {quote.market_type.value}"
                    f"{' ' + normalization.format_line(ref.line) if ref.line is not None else ''}: "
                    f"{ref.side_a.value} {_fmt_dec(ref.odds_a)} / {ref.side_b.value} {_fmt_dec(ref.odds_b)} "
                    f"(source update {_ts_text(ref.stamp)})"
                ),
                stamp=ref.stamp,
            )
        )
        skew_codes, skew_seconds = _reference_skew(quote, ref, settings.max_reference_skew_seconds)
        ref_age = _age_seconds(ref.stamp, now)
        reference_fresh = not skew_codes and ref_age is not None and ref_age <= settings.max_odds_age_seconds
        codes += skew_codes
        if "SOURCE_TIMESTAMP_UNKNOWN" in skew_codes:
            notes.append("skew between the target quote and the benchmark cannot be measured")
    else:
        codes += pair_codes
        if same_book_only:
            notes.append("reference quotes came only from the target book; no independent benchmark")

    # Probability: market baseline, or INSUFFICIENT_EVIDENCE with the reason as the method. A benchmark
    # beyond the skew limit, or whose skew cannot be measured, is never used (section 11: never loosened).
    if ref is None:
        probability = probabilities.estimate_leg_probability(selection, None)
    elif "TIMESTAMP_SKEW" in skew_codes:
        probability = S.ProbabilityEstimate(
            value=None,
            state=S.ModelState.INSUFFICIENT_EVIDENCE,
            method="TIMESTAMP_SKEW",
            reference_book=ref.book,
            reference_stamp=ref.stamp,
            assumptions=[
                f"reference snapshot is {skew_seconds}s from the target quote, above "
                f"max_reference_skew_seconds={settings.max_reference_skew_seconds}; not loosened"
            ],
        )
    elif "SOURCE_TIMESTAMP_UNKNOWN" in skew_codes:
        probability = S.ProbabilityEstimate(
            value=None,
            state=S.ModelState.INSUFFICIENT_EVIDENCE,
            method="SOURCE_TIMESTAMP_UNKNOWN",
            reference_book=ref.book,
            reference_stamp=ref.stamp,
            assumptions=[
                "the benchmark or the target quote carries no source timestamp, so the skew against "
                f"max_reference_skew_seconds={settings.max_reference_skew_seconds} cannot be measured; "
                "an unmeasurable skew never satisfies the limit"
            ],
        )
    else:
        probability = probabilities.estimate_leg_probability(selection, ref)
    if probability.state == S.ModelState.INSUFFICIENT_EVIDENCE:
        method = probability.method
        if method in _BENCHMARK_CODES:
            codes.append(method)
        elif method in _BENCHMARK_SIDE_MISMATCH:
            codes.append("REFERENCE_MISSING")
        elif method == "PERIOD_UNSUPPORTED":
            codes.append("PERIOD_UNSUPPORTED")

    # Price value.
    if probability.value is not None and ref is not None:
        price = probabilities.price_value(
            quote.odds_decimal,
            probability.value,
            f"edge = p_reference x target - 1 with p_reference from {ref.book} (proportional no-vig)",
        )
        interpretations.append(
            f"{ref.book} no-vig probability {_fmt_dec(probability.value, '0.000001')} implies a fair price of "
            f"{_fmt_dec(price.fair_decimal)}; {quote.book} offers {_fmt_dec(price.target_decimal)}: edge "
            f"{_signed(price.edge_per_dollar)} per dollar. This is a market baseline, not a prediction."
        )
    else:
        price = probabilities.price_value(
            quote.odds_decimal, None, "no benchmark for this line: value unknown"
        )
        interpretations.append(
            f"value unknown: no usable benchmark for this exact line and period ({probability.method})."
        )

    # Injury context.
    entries, injury_decision, injury_codes = injury_context.injury_for_selection(
        selection, list(injuries), settings.injury_report_max_age_seconds, now
    )
    codes += injury_codes
    for entry in entries:
        if entry.designation in (S.InjuryDesignation.NOT_LISTED, S.InjuryDesignation.AVAILABLE):
            continue
        reason = f" ({entry.reason})" if entry.reason else ""
        when = to_display(entry.report_timestamp_utc) if entry.report_timestamp_utc else "unknown time"
        facts.append(
            S.SourcedFact(
                text=f"injury report {when}: {_entry_name(entry)} {entry.designation.value}{reason}",
                stamp=entry.stamp,
            )
        )
    injury_report_current = (
        bool(injuries) and "INJURY_REPORT_STALE" not in codes and "INJURY_REPORT_MISSING" not in codes
    )

    # Named data-quality checks.
    identity_ok, identity_note = _identity_matched(selection)
    if identity_note:
        notes.append(identity_note)
    if not identity_ok:
        codes.append("PLAYER_UNMATCHED" if quote.market_type in S.PLAYER_MARKETS else "TEAM_UNMATCHED")
    checks = {
        "target_fresh": target_fresh,
        "reference_complete": ref is not None,
        "reference_fresh": reference_fresh,
        "injury_report_current": injury_report_current,
        "identity_matched": identity_ok,
        "rules_profile_known": quote.period == S.Period.FULL_GAME,
    }
    grade = _grade(checks, hard_fail="QUOTE_STALE" in codes or not identity_ok)
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        notes.append("failed checks: " + ", ".join(failed))
    data_quality = S.DataQuality(grade=grade, checks=checks, notes=notes)  # type: ignore[arg-type]

    # Decision.
    codes = _dedupe(codes)
    decision = freshness.decision_for(codes)
    if _DECISION_RANK[injury_decision] > _DECISION_RANK[decision]:
        decision = injury_decision
    reason_against = _strongest_reason_against(
        selection, codes, ref, same_book_only, probability, price, entries, skew_seconds, now, settings
    )
    blocking = [c for c in codes if c in freshness.BLOCKING_REASON_CODES]
    waiting = [c for c in codes if c in freshness.WAIT_REASON_CODES]
    if decision == S.LegDecision.UNUSABLE:
        interpretations.append(f"decision UNUSABLE: {', '.join(blocking) or 'injury'}; {reason_against}.")
    elif decision == S.LegDecision.WAIT_FOR_UPDATE:
        interpretations.append(
            f"decision WAIT_FOR_UPDATE: {', '.join(waiting) or 'injury'}; {reason_against}."
        )
    else:
        interpretations.append(f"decision USABLE; strongest reason against: {reason_against}.")
    interpretations.append(
        f"data quality {grade} (not a win probability): "
        + ", ".join(f"{k}={'ok' if v else 'no'}" for k, v in checks.items())
    )

    return S.LegAnalysis(
        selection_id=selection.selection_id,
        facts=facts,
        interpretations=interpretations,
        strongest_reason_against=reason_against,
        injury=entries,
        data_quality=data_quality,
        probability=probability,
        price_value=price,
        decision=decision,
        reason_codes=codes,
        analyzed_at_utc=now,
    )


# --------------------------------------------------------------------------------------
# Candidate assembly
# --------------------------------------------------------------------------------------


def candidate_data_mode(
    legs: Sequence[S.Selection],
    analyses: Mapping[str, S.LegAnalysis] | Sequence[S.LegAnalysis] | None = None,
) -> S.DataMode:
    """The data mode of a ticket: what the ledger and the user must know about where its numbers came from.

    FIXTURE when any leg quote, any leg's event, or any benchmark behind the leg analyses is fixture data
    (a typed ticket matched to the demo slate and priced against demo benchmarks is fixture data and never
    reaches a real ledger); else MANUAL_INPUT when any leg was typed; else LIVE_PROVIDER. Injury entries
    are context, not market data, and do not set the mode.
    """
    stamps: list[S.SourceStamp] = [leg.quote.stamp for leg in legs] + [leg.event.stamp for leg in legs]
    if analyses is not None:
        if isinstance(analyses, Mapping):
            items = [analyses[leg.selection_id] for leg in legs if leg.selection_id in analyses]
        else:
            items = list(analyses)
        stamps.extend(
            a.probability.reference_stamp for a in items if a.probability.reference_stamp is not None
        )
    if any(s.data_mode == S.DataMode.FIXTURE for s in stamps):
        return S.DataMode.FIXTURE
    if any(leg.quote.stamp.data_mode == S.DataMode.MANUAL_INPUT for leg in legs):
        return S.DataMode.MANUAL_INPUT
    return S.DataMode.LIVE_PROVIDER


def _evidence_tier(legs_with_reference: int, p_joint: Decimal | None) -> str:
    if p_joint is not None and legs_with_reference == 3:
        return "A"
    return {3: "B", 2: "B", 1: "C"}.get(legs_with_reference, "D")


def _rationale(
    ticket: S.ThreeLegTicket,
    analyses: Mapping[str, S.LegAnalysis],
    report: S.CorrelationReport,
    p_joint: Decimal | None,
    p_method: str,
    indicative: Decimal,
    ev: Decimal | None,
    legs_with_reference: int,
) -> str:
    lines: list[str] = [f"{ticket.parlay_type.value} ticket with three legs:"]
    for leg in ticket.legs:
        a = analyses[leg.selection_id]
        if a.probability.value is not None:
            bench = (
                f"benchmark {a.probability.reference_book} p={_fmt_dec(a.probability.value, '0.000001')}, "
                f"fair {_fmt_dec(a.price_value.fair_decimal)}, edge {_signed(a.price_value.edge_per_dollar)}"
            )
        else:
            bench = "no usable benchmark: value unknown"
        lines.append(
            f"- {leg.description} at {_fmt_dec(leg.quote.odds_decimal)} ({leg.quote.book}); {bench}; "
            f"strongest reason against: {a.strongest_reason_against}"
        )
    if p_joint is not None:
        lines.append(
            f"Joint probability {_fmt_dec(p_joint, '0.000001')}: product of the three market-baseline marginals "
            "assuming independence across games (an assumption, not a validated model)."
        )
        lines.append(
            f"Indicative multiplied price {_fmt_dec(indicative)} gives an indicative-based EV of {_signed(ev)} per "
            "dollar; the sportsbook's combined quote replaces the indicative price and the EV is recomputed from it."
        )
    elif ticket.parlay_type != S.ParlayType.MULTI_GAME:
        lines.append(
            "Qualitative only: legs share a game, no validated joint model exists here, so the marginals are not "
            "multiplied, no joint probability or expected value is stated, and this ticket is not called value."
        )
        lines.append(
            f"Indicative multiplied price {_fmt_dec(indicative)} is the product of the leg prices only."
        )
    else:
        lines.append(
            f"No joint probability: {p_method}. Expected value is unknown; value of this ticket is unknown."
        )
        lines.append(
            f"Indicative multiplied price {_fmt_dec(indicative)} is the product of the leg prices only."
        )
    if legs_with_reference < 3:
        lines.append(
            f"Only {legs_with_reference} of 3 legs have an independent benchmark; the rest are unpriced."
        )
    lines.append(f"Weakest assumption: {report.weakest_assumption}.")
    lines.append("The sportsbook's combined quote governs the payout; import it before any decision.")
    return "\n".join(lines)


def make_candidate(
    ticket: S.ThreeLegTicket,
    analyses: Mapping[str, S.LegAnalysis],
    report: S.CorrelationReport,
    now: datetime,
    settings: Settings,
    user_id: str,
    stake_usd: Decimal,
    *,
    candidate_id: str | None = None,
    state: S.CandidateState = S.CandidateState.NEEDS_BOOK_QUOTE,
) -> S.Candidate:
    """Assemble a ``Candidate`` from a valid ticket, its leg analyses and its correlation report."""
    leg_estimates = [analyses[leg.selection_id].probability for leg in ticket.legs]
    p_joint, model_state, p_method = probabilities.joint_probability(ticket, leg_estimates, report)
    indicative = probabilities.indicative_multiplied_decimal([leg.quote.odds_decimal for leg in ticket.legs])
    payout = probabilities.payout_math(stake_usd, indicative, "INDICATIVE_MULTIPLIED")
    ev = probabilities.ev_per_dollar(p_joint, indicative) if p_joint is not None else None

    codes: list[str] = []
    for leg in ticket.legs:
        codes += analyses[leg.selection_id].reason_codes
    if ticket.parlay_type != S.ParlayType.MULTI_GAME:
        codes.append("SAME_GAME_CORRELATION")
    if p_joint is None:
        codes += ["JOINT_PROBABILITY_UNAVAILABLE", "EV_UNAVAILABLE"]
    codes = _dedupe(codes)

    legs_with_reference = sum(1 for e in leg_estimates if e.value is not None)
    edges = [analyses[leg.selection_id].price_value.edge_per_dollar for leg in ticket.legs]
    sum_edge = sum((e for e in edges if e is not None), Decimal(0))
    grades = [analyses[leg.selection_id].data_quality.grade for leg in ticket.legs]
    min_grade = max(grades, key=lambda g: _GRADE_RANK[g])
    ranking = {
        "evidence_tier": _evidence_tier(legs_with_reference, p_joint),
        "legs_with_reference": str(legs_with_reference),
        "sum_edge": format(sum_edge.quantize(Decimal("0.000001")), "f"),
        "min_grade": min_grade,
        "model_state": model_state.value,
        "parlay_type": ticket.parlay_type.value,
        "note": RANKING_NOTE,
    }
    rationale = _rationale(ticket, analyses, report, p_joint, p_method, indicative, ev, legs_with_reference)
    expires = min(leg.event.commence_time_utc for leg in ticket.legs)
    return S.Candidate(
        candidate_id=candidate_id or new_id("cand"),
        user_id=user_id,
        created_at_utc=now,
        updated_at_utc=now,
        state=state,
        parlay_type=ticket.parlay_type,
        ticket=ticket,
        leg_analyses=[analyses[leg.selection_id] for leg in ticket.legs],
        correlation=report,
        indicative_multiplied_decimal=indicative,
        book_quote=None,
        model_state=model_state,
        p_joint=p_joint,
        p_joint_method=p_method,
        ev_per_dollar=ev,
        payout=payout,
        rationale=rationale,
        rechecks_required=list(RECHECKS_REQUIRED),
        reason_codes=codes,
        ranking=ranking,
        inputs_snapshot_utc=now,
        expires_at_utc=expires,
        data_mode=candidate_data_mode(ticket.legs, [analyses[leg.selection_id] for leg in ticket.legs]),
    )


# --------------------------------------------------------------------------------------
# Bounded search
# --------------------------------------------------------------------------------------


def _leg_sort_key(selection: S.Selection, analysis: S.LegAnalysis) -> tuple[int, Decimal, int, str]:
    has_baseline = (
        analysis.probability.state == S.ModelState.MARKET_BASELINE and analysis.probability.value is not None
    )
    edge = analysis.price_value.edge_per_dollar
    return (
        0 if has_baseline else 1,
        -(edge if edge is not None else _NO_EDGE),
        _GRADE_RANK[analysis.data_quality.grade],
        selection.selection_id,
    )


def order_usable_legs(
    selections: Sequence[S.Selection], analyses: Mapping[str, S.LegAnalysis]
) -> list[S.Selection]:
    """USABLE legs ordered by (has a market-baseline probability, edge per dollar desc, data grade)."""
    usable = [s for s in selections if analyses[s.selection_id].decision == S.LegDecision.USABLE]
    return sorted(usable, key=lambda s: _leg_sort_key(s, analyses[s.selection_id]))


def _search_legs(ordered: Sequence[S.Selection], wanted: set[S.ParlayType]) -> list[S.Selection]:
    """The bounded search set: at most ``MAX_LEGS_SEARCHED`` of the ordered usable legs.

    For a MULTI_GAME search the cut is taken round-robin across events (each event keeps its best legs, in
    the global order within each round), so one game with many strong props cannot crowd the other games
    out of the search. Otherwise the global order is kept, which favours depth inside one game.
    """
    if len(ordered) <= MAX_LEGS_SEARCHED:
        return list(ordered)
    if S.ParlayType.MULTI_GAME not in wanted:
        return list(ordered[:MAX_LEGS_SEARCHED])
    by_event: dict[str, list[S.Selection]] = {}
    for leg in ordered:
        by_event.setdefault(leg.event.event_id, []).append(leg)
    out: list[S.Selection] = []
    depth = 0
    while len(out) < MAX_LEGS_SEARCHED:
        progressed = False
        for legs in by_event.values():
            if depth < len(legs):
                out.append(legs[depth])
                progressed = True
                if len(out) >= MAX_LEGS_SEARCHED:
                    break
        if not progressed:
            break
        depth += 1
    return out


def _candidate_sort_key(candidate: S.Candidate) -> tuple[int, int, Decimal, int, str]:
    r = candidate.ranking
    return (
        _GRADE_RANK[r["evidence_tier"]],
        -int(r["legs_with_reference"]),
        -Decimal(r["sum_edge"]),
        _GRADE_RANK[r["min_grade"]],
        candidate.candidate_id,
    )


def build_candidates(
    selections: Sequence[S.Selection],
    references: Sequence[S.MarketQuote],
    injuries: Sequence[S.InjuryContext],
    parlay_type: str,
    max_candidates: int,
    now: datetime,
    settings: Settings,
    user_id: str,
    stake_usd: Decimal | None = None,
    *,
    analyses: Mapping[str, S.LegAnalysis] | None = None,
    stats: SearchStats | None = None,
) -> list[S.Candidate]:
    """Bounded search for ranked exactly-three-leg candidates (best first, at most ``max_candidates``).

    ``parlay_type``: "auto" builds MULTI_GAME tickets (one leg per distinct event) when at least three events
    have usable legs (counted over ALL usable legs, not the search cut); with fewer events it produces
    qualitative SAME_GAME / MIXED tickets instead (no joint probability, no EV). "multi_game" never falls
    back. "same_game" / "mixed" build only that shape. The search cut keeps every event represented for a
    MULTI_GAME search (see ``_search_legs``). Pass precomputed ``analyses`` to avoid analysing each leg
    twice; ``stats`` receives the search counters.
    """
    if parlay_type not in PARLAY_TYPE_ARGS:
        raise ValueError(f"INVALID_INPUT: parlay_type must be one of {PARLAY_TYPE_ARGS}")
    if max_candidates < 1:
        raise ValueError("INVALID_INPUT: max_candidates must be >= 1")
    stats = stats or SearchStats()
    stake = stake_usd if stake_usd is not None else settings.daily_cap_usd_default
    if analyses is None:
        analyses = {s.selection_id: analyze_leg(s, references, injuries, now, settings) for s in selections}
    stats.legs_considered = len(selections)
    ordered = order_usable_legs(selections, analyses)
    stats.legs_usable = len(ordered)
    events_with_usable = {s.event.event_id for s in ordered}
    stats.events_with_usable_legs = len(events_with_usable)

    if parlay_type in ("auto", "multi_game"):
        if len(events_with_usable) >= 3:
            wanted: set[S.ParlayType] = {S.ParlayType.MULTI_GAME}
        elif parlay_type == "multi_game":
            stats.mode = "MULTI_GAME"
            return []
        else:
            wanted = {S.ParlayType.SAME_GAME, S.ParlayType.MIXED}
    elif parlay_type == "same_game":
        wanted = {S.ParlayType.SAME_GAME}
    else:
        wanted = {S.ParlayType.MIXED}
    stats.mode = "/".join(sorted(w.value for w in wanted))
    top = _search_legs(ordered, wanted)
    stats.legs_searched = len(top)

    candidates: list[S.Candidate] = []
    for combo in combinations(top, 3):
        if stats.combinations_evaluated >= MAX_COMBINATIONS:
            break
        stats.combinations_evaluated += 1
        distinct_events = len({s.event.event_id for s in combo})
        shape = (
            S.ParlayType.MULTI_GAME
            if distinct_events == 3
            else S.ParlayType.SAME_GAME
            if distinct_events == 1
            else S.ParlayType.MIXED
        )
        if shape not in wanted:
            continue
        if correlation.hard_rejections(list(combo)):
            stats.combinations_rejected += 1
            continue
        try:
            ticket = S.ThreeLegTicket(legs=list(combo))
        except ValueError:
            stats.combinations_rejected += 1
            continue
        report = correlation.check_correlation(ticket)
        if any(
            f.severity == S.Severity.BLOCKING and f.type in correlation.HARD_FLAG_REASON_CODES
            for f in report.flags
        ):
            stats.combinations_rejected += 1
            continue
        candidates.append(make_candidate(ticket, analyses, report, now, settings, user_id, stake))
    candidates.sort(key=_candidate_sort_key)
    return candidates[:max_candidates]
