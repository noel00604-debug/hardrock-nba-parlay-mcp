"""Performance reports, the 30-day review, data costs, and a self-contained HTML dashboard.

Every number is computed from recorded bets, their effective settlement record (the latest
BOOK_CONFIRMED one when any exists, else the latest record), and the costs table for one ``user_id``.
Reports state their denominators, keep ticket win rate and leg hit rate apart, count net profit only
from book-confirmed cash figures, exclude pending tickets from profit (shown as pending exposure), and
never claim predictive skill.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import insert, select

from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.actual_bets import StoredBet, list_stored_bets, settlement_from_row
from hardrock_nba_parlay.budget import (
    IdempotencyConflictError,
    LedgerError,
    q_money,
    q_odds,
    q_prob,
    write_audit,
)
from hardrock_nba_parlay.db import Database, cents, costs, from_cents, iso, new_id, parse_iso, settlements
from hardrock_nba_parlay.settlement import (
    cash_profit,
    effective_leg_results,
    effective_settlement,
    ticket_outcome,
)

ZERO = Decimal("0.00")
SMALL_SAMPLE_TICKETS = 30


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _ratio(numerator: int, denominator: int) -> S.Ratio:
    value = q_prob(Decimal(numerator) / Decimal(denominator)) if denominator else None
    return S.Ratio(numerator=numerator, denominator=denominator, value=value)


@dataclass
class _Bucket:
    tickets: int = 0
    stake: Decimal = field(default_factory=lambda: ZERO)
    cash: Decimal = field(default_factory=lambda: ZERO)
    net: Decimal = field(default_factory=lambda: ZERO)
    won: int = 0
    lost: int = 0
    void_or_other: int = 0
    pending: int = 0

    def add(
        self,
        stake: Decimal,
        status: S.BetStatus,
        outcome: S.BetStatus | None,
        cash: Decimal | None,
        net: Decimal | None,
    ) -> None:
        self.tickets += 1
        self.stake += stake
        if outcome == S.BetStatus.WON:
            self.won += 1
        elif outcome == S.BetStatus.LOST:
            self.lost += 1
        elif status in S.FINAL_BET_STATUSES:
            self.void_or_other += 1
        else:
            self.pending += 1
        if cash is not None and net is not None:
            self.cash += cash
            self.net += net

    def model(self) -> S.PerfBucket:
        return S.PerfBucket(
            tickets=self.tickets,
            stake_usd=q_money(self.stake),
            cash_returned_usd=q_money(self.cash),
            net_usd=q_money(self.net),
            won=self.won,
            lost=self.lost,
            void_or_other=self.void_or_other,
            pending=self.pending,
        )


def _effective_settlements(db: Database, user_id: str, bet_ids: list[str]) -> dict[str, S.SettlementRecord]:
    """The governing settlement per bet: latest BOOK_CONFIRMED record when any exists, else the latest."""
    if not bet_ids:
        return {}
    with db.engine.connect() as conn:
        rows = conn.execute(
            select(settlements)
            .where(settlements.c.user_id == user_id, settlements.c.bet_id.in_(bet_ids))
            .order_by(settlements.c.bet_id, settlements.c.seq)
        ).all()
    grouped: dict[str, list[S.SettlementRecord]] = {}
    for row in rows:
        grouped.setdefault(row.bet_id, []).append(settlement_from_row(row))
    effective: dict[str, S.SettlementRecord] = {}
    for bet_id, records in grouped.items():
        chosen = effective_settlement(records)
        if chosen is not None:
            effective[bet_id] = chosen
    return effective


def parlay_type_of(stored: StoredBet) -> str:
    """forecast.parlay_type when recorded; else derived from three legs with event ids; else UNKNOWN."""
    forecast = stored.forecast or {}
    value = forecast.get("parlay_type")
    if isinstance(value, str) and value in S.ParlayType.__members__:
        return value
    legs = stored.bet.legs
    if len(legs) == 3 and all(leg.event_id for leg in legs):
        distinct = len({leg.event_id for leg in legs})
        return (
            S.ParlayType.MULTI_GAME.value
            if distinct == 3
            else S.ParlayType.SAME_GAME.value
            if distinct == 1
            else S.ParlayType.MIXED.value
        )
    return "UNKNOWN"


def market_composition_of(stored: StoredBet) -> str:
    """Sorted market types of the legs joined by '+'; legs without a market type contribute UNKNOWN."""
    legs = stored.bet.legs
    if all(leg.market_type is not None for leg in legs):
        return "+".join(sorted(leg.market_type.value for leg in legs if leg.market_type is not None))
    forecast = stored.forecast or {}
    value = forecast.get("market_composition")
    if isinstance(value, str) and value:
        return value
    return "+".join(sorted(leg.market_type.value if leg.market_type else "UNKNOWN" for leg in legs))


def _forecast_p_joint(forecast: dict[str, Any] | None) -> Decimal | None:
    if not forecast:
        return None
    raw = forecast.get("p_joint")
    if raw is None or raw == "":
        return None
    try:
        value = Decimal(str(raw))
    except (ArithmeticError, ValueError):
        return None
    if not (Decimal(0) <= value <= Decimal(1)):
        return None
    return q_prob(value)


def _forecast_model_state(forecast: dict[str, Any] | None) -> S.ModelState | None:
    if not forecast:
        return None
    raw = forecast.get("model_state")
    if isinstance(raw, str) and raw in S.ModelState.__members__:
        return S.ModelState(raw)
    return None


def _calibration_outcome(status: S.BetStatus, outcome: S.BetStatus | None) -> str | None:
    if outcome == S.BetStatus.WON:
        return "WON"
    if outcome == S.BetStatus.LOST:
        return "LOST"
    if status in (S.BetStatus.VOID, S.BetStatus.PARTIALLY_VOID):
        return "VOID"
    if status in (S.BetStatus.PENDING, S.BetStatus.DISPUTED):
        return "PENDING"
    return None  # CASHED_OUT / REPRICED / an unresolved CORRECTED carry no binary outcome


def _days_inclusive(start_date: str, end_date: str) -> int:
    return (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days + 1


# --------------------------------------------------------------------------------------
# Performance
# --------------------------------------------------------------------------------------


def performance(
    db: Database, user_id: str, start_date: str, end_date: str, now: datetime
) -> S.PerformanceReport:
    """Performance over ``start_date..end_date`` (inclusive ET dates) for one user.

    - ``net_profit_usd`` sums (cash returned - stake) over settled tickets whose effective settlement is
      BOOK_CONFIRMED with a cash figure; provisional results carry no cash and never move it. Pending
      and disputed tickets are excluded and shown as ``pending_exposure_usd``.
    - ``ticket_win_rate`` = WON / (WON + LOST) per ``settlement.ticket_outcome``: a CORRECTED ticket
      counts by its corrected leg results (any LOST -> LOST, all WON -> WON) or a 0.00 cash return
      (LOST); voids, cash-outs, repriced and unresolved corrections are not in the denominator.
      ``leg_hit_rate`` = legs WON / legs WON or LOST, reported separately and never substituted for
      the ticket rate.
    - Calibration points exist only for bets whose forecast carried ``p_joint`` before placement.
    - ``data_costs_usd`` sums every cost category in the window; ``after_cost_net_usd = net - costs``.
    """
    if start_date > end_date:
        raise LedgerError("INVALID_INPUT", "INVALID_INPUT: start_date must not be after end_date")
    stored_bets = list_stored_bets(db, user_id, start_date, end_date)
    latest = _effective_settlements(db, user_id, [s.bet.bet_id for s in stored_bets])

    total_stake = ZERO
    total_cash = ZERO
    net = ZERO
    pending_exposure = ZERO
    settled = 0
    voids = 0
    won = lost = 0
    legs_won = legs_resolved = 0
    provisional_count = 0
    by_type: dict[str, _Bucket] = {}
    by_comp: dict[str, _Bucket] = {}
    deltas: list[S.OddsDelta] = []
    calibration: list[S.CalibrationPoint] = []
    summaries: list[S.BetSummary] = []
    incomplete: list[str] = []
    late_injury: list[str] = []
    notes: list[str] = []
    skipped_calibration = 0

    for stored in stored_bets:
        bet = stored.bet
        settlement = latest.get(bet.bet_id)
        status = bet.status
        outcome = ticket_outcome(bet, settlement)
        is_final = status in S.FINAL_BET_STATUSES
        provisional = (
            settlement is not None and settlement.source == S.SettlementSource.PROVISIONAL_NBA_RESULTS
        )
        if provisional:
            provisional_count += 1
        total_stake += bet.stake_usd

        cash: Decimal | None = None
        bet_net: Decimal | None = None
        if is_final:
            settled += 1
            if (
                settlement is not None
                and settlement.cash_returned_usd is not None
                and settlement.status == status
            ):
                cash = settlement.cash_returned_usd
                bet_net = cash_profit(bet, settlement)
            if bet_net is None:
                incomplete.append(
                    f"{bet.bet_id}: status {status.value} without a confirmed cash-returned figure; excluded from net profit"
                )
            else:
                assert cash is not None
                total_cash += cash
                net += bet_net
        else:
            pending_exposure += bet.stake_usd

        if status in (S.BetStatus.VOID, S.BetStatus.PARTIALLY_VOID):
            voids += 1
        if outcome == S.BetStatus.WON:
            won += 1
        elif outcome == S.BetStatus.LOST:
            lost += 1

        leg_results = effective_leg_results(bet, settlement)
        for result in leg_results:
            if result == S.LegResult.WON:
                legs_won += 1
                legs_resolved += 1
            elif result == S.LegResult.LOST:
                legs_resolved += 1

        ptype = parlay_type_of(stored)
        comp = market_composition_of(stored)
        by_type.setdefault(ptype, _Bucket()).add(bet.stake_usd, status, outcome, cash, bet_net)
        by_comp.setdefault(comp, _Bucket()).add(bet.stake_usd, status, outcome, cash, bet_net)

        if bet.accepted_combined_decimal is not None or bet.recommended_combined_decimal is not None:
            delta = None
            if bet.accepted_combined_decimal is not None and bet.recommended_combined_decimal is not None:
                delta = q_odds(bet.accepted_combined_decimal - bet.recommended_combined_decimal)
            deltas.append(
                S.OddsDelta(
                    bet_id=bet.bet_id,
                    recommended_decimal=bet.recommended_combined_decimal,
                    accepted_decimal=bet.accepted_combined_decimal,
                    delta=delta,
                )
            )
        if bet.accepted_combined_decimal is None:
            incomplete.append(f"{bet.bet_id}: accepted combined odds not recorded")
        if any(leg.market_type is None or leg.event_id is None for leg in bet.legs):
            incomplete.append(f"{bet.bet_id}: one or more legs lack a market type or event id")

        p_joint = _forecast_p_joint(stored.forecast)
        if p_joint is not None:
            model_state = _forecast_model_state(stored.forecast)
            cal_outcome = _calibration_outcome(status, outcome)
            if model_state is None or cal_outcome is None:
                skipped_calibration += 1
            else:
                calibration.append(
                    S.CalibrationPoint(
                        bet_id=bet.bet_id,
                        forecast_p_joint=p_joint,
                        model_state=model_state,
                        outcome=cal_outcome,
                    )
                )
        for note in (stored.forecast or {}).get("late_injury_notes", []) or []:
            if isinstance(note, str) and note:
                late_injury.append(f"{bet.bet_id}: {note}")

        summaries.append(
            S.BetSummary(
                bet_id=bet.bet_id,
                date_local=bet.date_local,
                parlay_type=ptype,
                stake_usd=bet.stake_usd,
                accepted_decimal=bet.accepted_combined_decimal,
                status=status,
                cash_returned_usd=cash,
                net_usd=bet_net,
                provisional=provisional,
                leg_results=leg_results,
            )
        )

    data_costs = sum((c.amount_usd for c in list_costs(db, user_id, start_date, end_date)), ZERO)

    notes.append(
        "Net profit counts settled tickets with a book-confirmed cash-returned figure only; "
        f"{len(stored_bets) - settled} unsettled ticket(s) are shown as pending exposure."
    )
    notes.append(
        "Ticket win rate denominator = tickets resolved WON or LOST; a corrected ticket resolves by its "
        "corrected leg results or a 0.00 cash return, while voids, cash-outs, repriced and unresolved "
        "corrected tickets are excluded. Leg hit rate is reported separately and is not a parlay win rate."
    )
    if settled < SMALL_SAMPLE_TICKETS:
        notes.append(
            f"Small sample: {settled} settled ticket(s). Observed results at this size cannot distinguish "
            "skill from variance."
        )
    if provisional_count:
        notes.append(
            f"{provisional_count} ticket(s) carry a provisional result from NBA data, not a Hard Rock "
            "settlement; they may change when the book settles."
        )
    if voids:
        notes.append(f"{voids} ticket(s) are VOID or PARTIALLY_VOID; partial voids are counted in 'voids'.")
    if skipped_calibration:
        notes.append(
            f"{skipped_calibration} forecast(s) were skipped for calibration (no model state or no binary outcome)."
        )
    if data_costs:
        notes.append(
            "data_costs_usd sums every cost category (DATA, SOFTWARE, HOSTING, OTHER) in the window."
        )

    return S.PerformanceReport(
        start_date=start_date,
        end_date=end_date,
        generated_at_utc=now,
        tickets_placed=len(stored_bets),
        total_stake_usd=q_money(total_stake),
        settled_tickets=settled,
        total_cash_returned_usd=q_money(total_cash),
        net_profit_usd=q_money(net),
        pending_exposure_usd=q_money(pending_exposure),
        voids=voids,
        ticket_win_rate=_ratio(won, won + lost),
        leg_hit_rate=_ratio(legs_won, legs_resolved),
        by_parlay_type={k: v.model() for k, v in sorted(by_type.items())},
        by_market_composition={k: v.model() for k, v in sorted(by_comp.items())},
        accepted_vs_recommended=deltas,
        calibration=calibration,
        data_costs_usd=q_money(data_costs),
        after_cost_net_usd=q_money(net - data_costs),
        bets=summaries,
        incomplete_data_notes=incomplete,
        late_injury_notes=late_injury,
        notes=notes,
    )


# --------------------------------------------------------------------------------------
# 30-day review
# --------------------------------------------------------------------------------------


def thirty_day_review(
    db: Database, user_id: str, window_start: str, window_end: str, cap_usd: Decimal, now: datetime
) -> S.ReviewReport:
    """The initial review: observed results stated plainly, with an explicit note that they are not evidence of skill."""
    perf = performance(db, user_id, window_start, window_end, now)
    days = _days_inclusive(window_start, window_end)
    cap = q_money(cap_usd)
    max_possible = q_money(cap * days)
    stored_bets = list_stored_bets(db, user_id, window_start, window_end)
    days_with_bets = len({s.bet.date_local for s in stored_bets})

    resolved = perf.ticket_win_rate.denominator
    wins = perf.ticket_win_rate.numerator
    observed = [
        f"{perf.tickets_placed} ticket(s) placed on {days_with_bets} of {days} days in the window "
        f"{window_start} to {window_end}.",
        f"Total stake ${perf.total_stake_usd} of a maximum possible ${max_possible} at the ${cap} daily cap.",
        f"Settled tickets: {perf.settled_tickets}; won {wins}, lost {resolved - wins}, void or other "
        f"{perf.settled_tickets - resolved}.",
        f"Cash returned on settled tickets ${perf.total_cash_returned_usd}; net profit ${perf.net_profit_usd}; "
        f"after data/software costs of ${perf.data_costs_usd}: ${perf.after_cost_net_usd}.",
        f"Pending exposure ${perf.pending_exposure_usd} on {perf.tickets_placed - perf.settled_tickets} unsettled ticket(s).",
    ]
    if perf.ticket_win_rate.value is not None:
        observed.append(
            f"Observed ticket win frequency {wins}/{resolved} ({perf.ticket_win_rate.value}); "
            f"leg hit frequency {perf.leg_hit_rate.numerator}/{perf.leg_hit_rate.denominator}."
        )
    else:
        observed.append("No ticket has resolved to WON or LOST yet, so no win frequency is reported.")

    evidence = [
        f"{perf.settled_tickets} settled ticket(s) cannot establish predictive skill; the observed result is "
        "consistent with chance and with the sportsbook's margin.",
        "Observed frequencies are not probability estimates and are not extrapolated.",
        "This review makes no claim of skill. A positive or negative result over this window is not evidence either way.",
    ]
    if perf.calibration:
        evidence.append(
            f"{len(perf.calibration)} ticket(s) had a numerical pre-placement forecast; that is too few to assess calibration."
        )
    else:
        evidence.append(
            "No ticket carried a numerical pre-placement forecast, so calibration cannot be assessed."
        )

    same_game = sum(
        1
        for s in stored_bets
        if parlay_type_of(s) in (S.ParlayType.SAME_GAME.value, S.ParlayType.MIXED.value)
    )
    shared_days = 0
    seen: dict[str, set[str]] = {}
    for s in stored_bets:
        events = {leg.event_id for leg in s.bet.legs if leg.event_id}
        day_events = seen.setdefault(s.bet.date_local, set())
        if events & day_events:
            shared_days += 1
        day_events |= events
    dependence = [
        "Daily three-leg parlays are a small, dependent sample: legs within a ticket share game, pace, "
        "minutes and injury assumptions, so ticket outcomes are not independent trials.",
        f"{same_game} ticket(s) were same-game or mixed parlays whose joint probability was not quantified.",
        f"{shared_days} ticket(s) shared a game with another ticket placed the same day.",
        "Thirty days of daily parlays can still be inconclusive; continue tracking before drawing conclusions.",
    ]
    return S.ReviewReport(
        window_start=window_start,
        window_end=window_end,
        generated_at_utc=now,
        performance=perf,
        max_possible_gross_stake_usd=max_possible,
        days_with_bets=days_with_bets,
        observed_results=observed,
        evidence_of_skill=evidence,
        dependence_and_sample_notes=dependence,
        continue_operation_note=f"Normal operation continues; daily cap unchanged at ${cap}.",
    )


# --------------------------------------------------------------------------------------
# Costs
# --------------------------------------------------------------------------------------


def _cost_from_row(row: Any) -> S.CostEntry:
    created = parse_iso(row.created_at)
    assert created is not None
    amount = from_cents(row.amount_cents)
    assert amount is not None
    return S.CostEntry(
        cost_id=row.cost_id,
        user_id=row.user_id,
        date_local=row.date_local,
        description=row.description,
        amount_usd=amount,
        category=row.category,
        created_at_utc=created,
    )


def add_cost(db: Database, user_id: str, cost: S.CostInput, now: datetime) -> tuple[S.CostEntry, bool]:
    """Record a data/software/hosting cost. With an idempotency key, a repeat returns ``replay=True``;
    the same key with a different amount, date, category or description raises ``IdempotencyConflictError``."""
    amount = q_money(cost.amount_usd)
    with db.tx() as conn:
        if cost.idempotency_key:
            existing = conn.execute(
                select(costs).where(
                    costs.c.user_id == user_id, costs.c.idempotency_key == cost.idempotency_key
                )
            ).first()
            if existing is not None:
                same = (
                    existing.amount_cents == cents(amount)
                    and existing.date_local == cost.date_local
                    and existing.category == cost.category
                    and existing.description == cost.description
                )
                if not same:
                    raise IdempotencyConflictError(
                        message="IDEMPOTENCY_CONFLICT: idempotency_key already used for a different cost"
                    )
                return _cost_from_row(existing), True
        cost_id = new_id("cost")
        conn.execute(
            insert(costs).values(
                cost_id=cost_id,
                user_id=user_id,
                date_local=cost.date_local,
                category=cost.category,
                amount_cents=cents(amount),
                description=cost.description,
                idempotency_key=cost.idempotency_key or None,
                created_at=iso(now),
            )
        )
        write_audit(
            conn,
            user_id,
            "cost.add",
            cost_id,
            {"date_local": cost.date_local, "category": cost.category, "amount_usd": str(amount)},
            now,
        )
        row = conn.execute(select(costs).where(costs.c.cost_id == cost_id)).one()
        return _cost_from_row(row), False


def list_costs(
    db: Database, user_id: str, start_date: str | None = None, end_date: str | None = None
) -> list[S.CostEntry]:
    """The user's cost entries, optionally limited to ``start_date..end_date`` inclusive."""
    stmt = select(costs).where(costs.c.user_id == user_id)
    if start_date is not None:
        stmt = stmt.where(costs.c.date_local >= start_date)
    if end_date is not None:
        stmt = stmt.where(costs.c.date_local <= end_date)
    stmt = stmt.order_by(costs.c.date_local, costs.c.created_at, costs.c.cost_id)
    with db.engine.connect() as conn:
        rows = conn.execute(stmt).all()
    return [_cost_from_row(r) for r in rows]


# --------------------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------------------

_CSS = (
    "body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:24px;color:#1b1b1b;background:#fff}"
    "h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:24px 0 8px}"
    "table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid #ccc;padding:4px 8px;text-align:left}"
    "th{background:#f0f0f0}td.num,th.num{text-align:right}.muted{color:#555;font-size:12px}"
    ".flag{color:#a40000;font-weight:600}ul{font-size:13px}"
)


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _row(cells: list[Any], numeric: set[int] | None = None, header: bool = False) -> str:
    tag = "th" if header else "td"
    out = []
    for i, cell in enumerate(cells):
        cls = ' class="num"' if numeric and i in numeric else ""
        out.append(f"<{tag}{cls}>{_e(cell)}</{tag}>")
    return "<tr>" + "".join(out) + "</tr>"


def dashboard_html(
    report: S.PerformanceReport, budget_today: S.DailyBudget, costs_list: list[S.CostEntry] | None = None
) -> str:
    """Self-contained HTML (inline CSS, no scripts, no external assets). Every text value is escaped."""
    parts: list[str] = [
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Hard Rock NBA parlay ledger</title>",
        f"<style>{_CSS}</style></head><body>",
        "<h1>Hard Rock NBA parlay ledger</h1>",
        f'<p class="muted">Report window {_e(report.start_date)} to {_e(report.end_date)}; generated '
        f"{_e(report.generated_at_utc.isoformat(timespec='seconds'))}. Application ledger of user-confirmed wagers; "
        "not a sportsbook account view. No prediction or win-rate claim is implied.</p>",
    ]

    parts.append("<h2>Budget today</h2><table>")
    parts.append(_row(["Date (ET)", "Cap", "Recorded", "Reserved", "Remaining", "Breaches"], header=True))
    breaches = ", ".join(budget_today.breaches) or "none"
    parts.append(
        _row(
            [
                budget_today.date_local,
                f"${budget_today.cap_usd}",
                f"${budget_today.recorded_stake_usd}",
                f"${budget_today.reserved_stake_usd}",
                f"${budget_today.remaining_usd}",
                breaches,
            ],
            numeric={1, 2, 3, 4},
        )
    )
    parts.append("</table>")
    parts.append(f'<p class="muted">{_e(budget_today.note)}</p>')

    win = report.ticket_win_rate
    legs = report.leg_hit_rate
    parts.append("<h2>Profit and loss (settled tickets only)</h2><table>")
    parts.append(_row(["Metric", "Value"], header=True))
    for label, value in [
        ("Tickets placed", report.tickets_placed),
        ("Total stake", f"${report.total_stake_usd}"),
        ("Settled tickets", report.settled_tickets),
        ("Cash returned (settled)", f"${report.total_cash_returned_usd}"),
        ("Net profit (settled)", f"${report.net_profit_usd}"),
        ("Pending exposure", f"${report.pending_exposure_usd}"),
        ("Voids (incl. partial)", report.voids),
        (
            "Ticket win rate (won / won+lost)",
            f"{win.numerator}/{win.denominator}" + (f" = {win.value}" if win.value is not None else " (n/a)"),
        ),
        (
            "Leg hit rate (legs won / resolved)",
            f"{legs.numerator}/{legs.denominator}"
            + (f" = {legs.value}" if legs.value is not None else " (n/a)"),
        ),
        ("Data/software costs", f"${report.data_costs_usd}"),
        ("After-cost net", f"${report.after_cost_net_usd}"),
    ]:
        parts.append(_row([label, value], numeric={1}))
    parts.append("</table>")

    parts.append("<h2>Bets</h2><table>")
    parts.append(
        _row(
            [
                "Bet id",
                "Date (ET)",
                "Type",
                "Stake",
                "Accepted odds",
                "Status",
                "Cash returned",
                "Net",
                "Legs",
                "Provisional",
            ],
            header=True,
        )
    )
    for b in report.bets:
        parts.append(
            _row(
                [
                    b.bet_id,
                    b.date_local,
                    b.parlay_type or "UNKNOWN",
                    f"${b.stake_usd}",
                    "" if b.accepted_decimal is None else str(b.accepted_decimal),
                    b.status.value,
                    "" if b.cash_returned_usd is None else f"${b.cash_returned_usd}",
                    "" if b.net_usd is None else f"${b.net_usd}",
                    "/".join(r.value for r in b.leg_results),
                    "yes" if b.provisional else "",
                ],
                numeric={3, 4, 6, 7},
            )
        )
    if not report.bets:
        parts.append(_row(["No bets recorded in this window", "", "", "", "", "", "", "", "", ""]))
    parts.append("</table>")

    parts.append("<h2>Results by parlay type</h2><table>")
    parts.append(
        _row(
            ["Type", "Tickets", "Stake", "Cash returned", "Net", "Won", "Lost", "Void/other", "Pending"],
            header=True,
        )
    )
    for key, bucket in report.by_parlay_type.items():
        parts.append(
            _row(
                [
                    key,
                    bucket.tickets,
                    f"${bucket.stake_usd}",
                    f"${bucket.cash_returned_usd}",
                    f"${bucket.net_usd}",
                    bucket.won,
                    bucket.lost,
                    bucket.void_or_other,
                    bucket.pending,
                ],
                numeric={1, 2, 3, 4, 5, 6, 7, 8},
            )
        )
    parts.append("</table>")

    parts.append("<h2>Costs</h2><table>")
    parts.append(_row(["Date (ET)", "Category", "Description", "Amount"], header=True))
    for c in costs_list or []:
        parts.append(_row([c.date_local, c.category, c.description, f"${c.amount_usd}"], numeric={3}))
    parts.append(_row(["Total in window", "", "", f"${report.data_costs_usd}"], numeric={3}))
    parts.append("</table>")

    notes = list(report.notes) + list(report.incomplete_data_notes) + list(report.late_injury_notes)
    if notes:
        parts.append("<h2>Notes</h2><ul>")
        parts.extend(f"<li>{_e(n)}</li>" for n in notes)
        parts.append("</ul>")
    parts.append("</body></html>")
    return "".join(parts)
