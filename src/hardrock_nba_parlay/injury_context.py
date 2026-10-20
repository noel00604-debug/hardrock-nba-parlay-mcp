"""Injury-report context for one selection (docs/ARCHITECTURE.md section 5, "injury_context.py").

Decision rules (player markets): OUT -> UNUSABLE (INJURY_OUT); DOUBTFUL -> UNUSABLE (INJURY_DOUBTFUL);
QUESTIONABLE -> WAIT_FOR_UPDATE (INJURY_QUESTIONABLE_MATERIAL); PROBABLE / AVAILABLE / not listed -> USABLE.
A team whose report reads "NOT YET SUBMITTED" makes any leg touching that team WAIT_FOR_UPDATE.

Team markets never auto-reject on a listed player: the tool has no role/minutes data, so materiality is
unknown and the note tells the user to judge it (INJURY_QUESTIONABLE_IMMATERIAL with
``material_to_selection=None``). A report older than the configured maximum adds INJURY_REPORT_STALE and an
empty report adds INJURY_REPORT_MISSING; neither changes the decision by itself.
"""

from __future__ import annotations

from datetime import datetime

from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import to_display
from hardrock_nba_parlay.normalization import player_slug

__all__ = [
    "NOT_YET_SUBMITTED",
    "injury_for_selection",
    "materiality_note",
    "report_timestamp",
]

NOT_YET_SUBMITTED = "NOT YET SUBMITTED"

_LISTED_UNRESOLVED = (S.InjuryDesignation.OUT, S.InjuryDesignation.DOUBTFUL, S.InjuryDesignation.QUESTIONABLE)


def report_timestamp(report: list[S.InjuryContext]) -> datetime | None:
    """The newest report timestamp carried by the entries (None when no entry has one)."""
    stamps = [e.report_timestamp_utc for e in report if e.report_timestamp_utc is not None]
    return max(stamps) if stamps else None


def _player_matches(entry: S.InjuryContext, selection: S.Selection) -> bool:
    player = selection.player
    quote = selection.quote
    pid = (player.player_id if player else None) or quote.player_id
    if entry.player_id and pid:
        return entry.player_id == pid
    name = (player.name if player else None) or quote.player_name_raw or ""
    if entry.player_name_raw and name:
        return player_slug(entry.player_name_raw) == player_slug(name)
    return False


def _is_not_submitted(entry: S.InjuryContext) -> bool:
    return (
        entry.designation == S.InjuryDesignation.UNKNOWN
        and (entry.player_name_raw or "").upper() == NOT_YET_SUBMITTED
    )


def materiality_note(selection: S.Selection, entry: S.InjuryContext) -> str:
    """Explain why a listed player matters (or might matter) for this selection."""
    who = entry.player_name_raw or entry.player_id or "a listed player"
    status = entry.designation.value
    if selection.quote.market_type in S.PLAYER_MARKETS:
        if entry.designation in (S.InjuryDesignation.OUT, S.InjuryDesignation.DOUBTFUL):
            return f"{who} is {status}: the prop leg cannot be used."
        if entry.designation == S.InjuryDesignation.QUESTIONABLE:
            return f"{who} is QUESTIONABLE: participation is unresolved, wait for the next report or a confirmed lineup."
        return f"{who} is {status} on the report."
    team_text = f" ({entry.team_id})" if entry.team_id else ""
    return (
        f"{who}{team_text} is {status}. This is a team market; whether that is material depends on the player's "
        "role and minutes, which this tool does not have. Judge materiality yourself before using the leg."
    )


def _with_context(entry: S.InjuryContext, material: bool | None, note: str) -> S.InjuryContext:
    return entry.model_copy(update={"material_to_selection": material, "note": note})


def injury_for_selection(
    selection: S.Selection,
    report: list[S.InjuryContext],
    report_max_age_s: int,
    now: datetime,
) -> tuple[list[S.InjuryContext], S.LegDecision, list[str]]:
    """Return the entries relevant to the selection, the leg decision, and the reason codes."""
    codes: list[str] = []
    if not report:
        return [], S.LegDecision.USABLE, ["INJURY_REPORT_MISSING"]
    report_ts = report_timestamp(report)
    if report_ts is not None and (now - report_ts).total_seconds() > report_max_age_s:
        codes.append("INJURY_REPORT_STALE")
    event = selection.event
    team_ids = {event.home_team.team_id, event.away_team.team_id}
    relevant = [
        e
        for e in report
        if e.event_id == event.event_id or (e.event_id.startswith("unmatched:") and e.team_id in team_ids)
    ]
    entries: list[S.InjuryContext] = []
    decision = S.LegDecision.USABLE
    quote = selection.quote
    not_submitted_teams = {e.team_id for e in relevant if _is_not_submitted(e)}
    ts_text = to_display(report_ts) if report_ts else "latest"

    if quote.market_type in S.PLAYER_MARKETS:
        player_team = (selection.player.team_id if selection.player else None) or quote.team_id
        blocked_by_submission = (
            (player_team in not_submitted_teams) if player_team else bool(not_submitted_teams)
        )
        listed = [e for e in relevant if _player_matches(e, selection)]
        if listed:
            entry = listed[0]
            d = entry.designation
            if d == S.InjuryDesignation.OUT:
                decision, code = S.LegDecision.UNUSABLE, "INJURY_OUT"
            elif d == S.InjuryDesignation.DOUBTFUL:
                decision, code = S.LegDecision.UNUSABLE, "INJURY_DOUBTFUL"
            elif d == S.InjuryDesignation.QUESTIONABLE:
                decision, code = S.LegDecision.WAIT_FOR_UPDATE, "INJURY_QUESTIONABLE_MATERIAL"
            else:
                code = None
            if code:
                codes.append(code)
            material = d in _LISTED_UNRESOLVED
            entries.append(_with_context(entry, material, materiality_note(selection, entry)))
        else:
            name = (selection.player.name if selection.player else None) or quote.player_name_raw
            entries.append(
                S.InjuryContext(
                    event_id=event.event_id,
                    team_id=player_team,
                    player_id=(selection.player.player_id if selection.player else quote.player_id),
                    player_name_raw=name,
                    designation=S.InjuryDesignation.NOT_LISTED,
                    reason=None,
                    report_timestamp_utc=report_ts,
                    stamp=relevant[0].stamp if relevant else report[0].stamp,
                    material_to_selection=False,
                    note=f"{name or 'player'} not listed on the {ts_text} report",
                )
            )
        if blocked_by_submission and decision != S.LegDecision.UNUSABLE:
            decision = S.LegDecision.WAIT_FOR_UPDATE
            codes.append("WAIT_FOR_UPDATE")
            for e in relevant:
                if _is_not_submitted(e):
                    entries.append(_with_context(e, None, "team has not yet submitted its injury report"))
    else:
        flagged = False
        for entry in relevant:
            if _is_not_submitted(entry):
                entries.append(_with_context(entry, None, "team has not yet submitted its injury report"))
                continue
            if entry.designation in _LISTED_UNRESOLVED:
                flagged = True
                entries.append(_with_context(entry, None, materiality_note(selection, entry)))
            else:
                entries.append(_with_context(entry, False, materiality_note(selection, entry)))
        if flagged:
            codes.append("INJURY_QUESTIONABLE_IMMATERIAL")
        if not_submitted_teams:
            decision = S.LegDecision.WAIT_FOR_UPDATE
            codes.append("WAIT_FOR_UPDATE")

    return entries, decision, codes
