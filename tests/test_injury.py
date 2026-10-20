"""nba_injury_report.py and injury_context.py: slot URLs, text/PDF parsing, probing, decisions."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from conftest import NOW, TEAMS, make_event, make_quote, make_selection, stamp

from hardrock_nba_parlay import injury_context as IC
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import FixedClock
from hardrock_nba_parlay.errors import InvalidInput, ProviderError
from hardrock_nba_parlay.providers import nba_injury_report as R

FIXTURES = Path(__file__).parent / "fixtures"
REPORT_TEXT = (FIXTURES / "injury_report_2026-10-19_07_00PM.txt").read_text(encoding="utf-8")
REPORT_TS = datetime(2026, 10, 19, 23, 0, tzinfo=UTC)


@pytest.fixture
def real_slate():
    """The real opening-night slate (times from docs/research/nba-schedule-injuries.md)."""
    return [
        make_event("BOS", "DET", start=datetime(2026, 10, 20, 19, 0, tzinfo=UTC)),
        make_event("PHI", "NYK", start=datetime(2026, 10, 20, 23, 0, tzinfo=UTC)),
        make_event("OKC", "SAS", start=datetime(2026, 10, 21, 1, 30, tzinfo=UTC)),
    ]


# --------------------------------------------------------------------------------------
# Slot URLs
# --------------------------------------------------------------------------------------


def test_report_slots_example_from_brief():
    now = datetime(2026, 10, 19, 23, 7, tzinfo=UTC)  # 19:07 ET
    urls = R.report_slots("2026-10-20", now)
    assert urls[0] == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-19_07_00PM.pdf"
    assert urls[1].endswith("Injury-Report_2026-10-19_06_45PM.pdf")
    assert urls[-1].endswith("Injury-Report_2026-10-18_07_15AM.pdf")
    assert len(urls) == 36 * 4
    assert len(set(urls)) == len(urls)


def test_report_slots_twelve_hour_clock_and_midnight():
    assert R.slot_url(datetime(2026, 10, 19, 0, 0, tzinfo=R.tz(R.ET))).endswith("_2026-10-19_12_00AM.pdf")
    assert R.slot_url(datetime(2026, 10, 19, 12, 15, tzinfo=R.tz(R.ET))).endswith("_2026-10-19_12_15PM.pdf")
    assert R.slot_url(datetime(2026, 10, 19, 6, 45, tzinfo=R.tz(R.ET))).endswith("_2026-10-19_06_45AM.pdf")
    # 00:02 ET on Oct 20 -> newest slot is 12:00 AM Oct 20, then 11:45 PM Oct 19
    urls = R.report_slots("2026-10-20", datetime(2026, 10, 20, 4, 2, tzinfo=UTC), lookback_hours=1)
    assert urls[0].endswith("_2026-10-20_12_00AM.pdf")
    assert urls[1].endswith("_2026-10-19_11_45PM.pdf")
    assert len(urls) == 4


def test_report_slots_past_date_is_capped_to_that_day_and_dst_day_has_no_duplicates():
    later = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    urls = R.report_slots("2026-10-20", later, lookback_hours=2)
    assert urls[0].endswith("_2026-10-20_11_45PM.pdf")
    dst = R.report_slots("2026-11-01", datetime(2026, 11, 1, 12, 0, tzinfo=UTC), lookback_hours=12)
    assert len(dst) == len(set(dst))
    assert any(u.endswith("_2026-11-01_01_30AM.pdf") for u in dst)


def test_report_slots_requires_aware_now():
    with pytest.raises(InvalidInput):
        R.report_slots("2026-10-20", datetime(2026, 10, 19, 23, 7))


# --------------------------------------------------------------------------------------
# Text parsing
# --------------------------------------------------------------------------------------


def test_parse_text_fixture_rows_timestamp_and_event_matching(real_slate):
    entries = R.parse_injury_report_text(
        REPORT_TEXT, NOW, real_slate, source_url="https://example.invalid/report.pdf"
    )
    assert len(entries) == 16
    assert all(e.report_timestamp_utc == REPORT_TS for e in entries)
    assert all(e.stamp.source_timestamp_utc == REPORT_TS and e.stamp.received_at_utc == NOW for e in entries)
    assert all(
        e.stamp.data_mode == S.DataMode.LIVE_PROVIDER and e.stamp.source == "nba-official-injury-report"
        for e in entries
    )
    by_player = {e.player_id: e for e in entries}
    assert by_player["player:devin-carter"].event_id == "fixture:BOS@DET"
    assert by_player["player:devin-carter"].team_id == "nba:BOS"
    assert by_player["player:devin-carter"].designation == S.InjuryDesignation.OUT
    assert by_player["player:devin-carter"].player_name_raw == "Devin Carter"
    assert by_player["player:jayden-quaintance"].event_id == "fixture:OKC@SAS"
    assert by_player["player:elijah-harkless"].designation == S.InjuryDesignation.QUESTIONABLE


def test_parse_text_team_carry_forward_and_wrapped_reason(real_slate):
    entries = {e.player_id: e for e in R.parse_injury_report_text(REPORT_TEXT, NOW, real_slate)}
    # team label printed once, carried to the following rows
    assert entries["player:isaac-jones"].team_id == "nba:DET"
    assert entries["player:taurean-prince"].team_id == "nba:DET"
    assert (
        entries["player:topic-nikola"].team_id == "nba:OKC"
        if "player:topic-nikola" in entries
        else entries["player:nikola-topic"].team_id == "nba:OKC"
    )
    # carry-forward across the page break (page 2 has no team label)
    assert entries["player:jayden-quaintance"].team_id == "nba:SAS"
    # wrapped reasons are joined
    assert entries["player:ariel-hukporti"].reason == "Injury/Illness - Right Achilles Tendon Rupture / Tear"
    assert entries["player:anfernee-simons"].reason == "Injury/Illness - Left Hamstring Tightness / Soreness"
    assert entries["player:otega-oweh"].reason == "Injury/Illness - Right Achilles Tendon Repair / Surgery"
    assert entries["player:dominick-barlow"].reason == "Injury/Illness - Low Back Stress Reaction"


def test_parse_text_unmatched_event_without_slate():
    entries = R.parse_injury_report_text(REPORT_TEXT, NOW, None)
    assert {e.event_id for e in entries} == {"unmatched:BOS@DET", "unmatched:PHI@NYK", "unmatched:OKC@SAS"}
    # wrong date in the slate -> unmatched too
    wrong_day = [make_event("BOS", "DET", start=datetime(2026, 10, 21, 19, 0, tzinfo=UTC))]
    entries = R.parse_injury_report_text(REPORT_TEXT, NOW, wrong_day)
    assert all(e.event_id.startswith("unmatched:") for e in entries)


SYNTHETIC_NOT_SUBMITTED = """# FIXTURE: synthetic layout exercising NOT YET SUBMITTED and every status word (not a real report)
                                        Injury Report: 03/26/26 08:00 PM
Game Date    Game Time    Matchup    Team                 Player Name          Current Status    Reason
03/27/2026   07:30 (ET)   MIA@ORL    Miami Heat           NOT YET SUBMITTED
                                     Orlando Magic        Banchero, Paolo      Probable          Injury/Illness - Right Ankle Sprain
                                                          Wagner, Franz        Available         Injury/Illness - Left Knee Soreness
                                                          Suggs, Jalen         Doubtful          Injury/Illness - Right Knee; Contusion
"""


def test_parse_text_not_yet_submitted_and_all_status_words():
    slate = (
        [make_event("MIA", "ORL", start=datetime(2026, 3, 27, 23, 30, tzinfo=UTC))]
        if "MIA" in TEAMS
        else None
    )
    entries = R.parse_injury_report_text(SYNTHETIC_NOT_SUBMITTED, NOW, slate)
    assert entries[0].report_timestamp_utc == datetime(
        2026, 3, 27, 0, 0, tzinfo=UTC
    )  # 8 PM EDT = 00:00Z next day
    placeholder = entries[0]
    assert placeholder.designation == S.InjuryDesignation.UNKNOWN
    assert placeholder.player_name_raw == "NOT YET SUBMITTED" and placeholder.player_id is None
    assert placeholder.team_id == "nba:MIA" and "not submitted" in (placeholder.note or "")
    statuses = {e.player_id: e.designation for e in entries[1:]}
    assert statuses == {
        "player:paolo-banchero": S.InjuryDesignation.PROBABLE,
        "player:franz-wagner": S.InjuryDesignation.AVAILABLE,
        "player:jalen-suggs": S.InjuryDesignation.DOUBTFUL,
    }
    assert all(e.team_id == "nba:ORL" for e in entries[1:])


# --------------------------------------------------------------------------------------
# PDF parsing (hand-built PDF so no network and no binary fixture)
# --------------------------------------------------------------------------------------


def make_pdf(rows: list[list[tuple[int, str]]]) -> bytes:
    """Minimal single-page PDF; each row is a list of (x, text) placed on one baseline."""
    content = ["BT", "/F1 9 Tf"]
    y = 560
    for row in rows:
        for x, text in row:
            esc = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            content.append(f"1 0 0 1 {x} {y} Tm ({esc}) Tj")
        y -= 14
    content.append("ET")
    stream = "\n".join(content).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 792 612] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


PDF_ROWS = [
    [(300, "Injury Report: 10/19/26 07:00 PM")],
    [
        (30, "Game Date"),
        (90, "Game Time"),
        (150, "Matchup"),
        (210, "Team"),
        (330, "Player Name"),
        (450, "Current Status"),
        (540, "Reason"),
    ],
    [
        (30, "10/20/2026"),
        (90, "03:00 (ET)"),
        (150, "BOS@DET"),
        (210, "Boston Celtics"),
        (330, "Carter, Devin"),
        (450, "Out"),
        (540, "Injury/Illness - Illness"),
    ],
    [(210, "Detroit Pistons"), (330, "Harkless, Elijah"), (450, "Questionable"), (540, "G League - Two-Way")],
    [(330, "Jones, Isaac"), (450, "Out"), (540, "G League - Two-Way")],
]


def test_parse_pdf_with_pypdf(real_slate):
    entries = R.parse_injury_report_pdf(
        make_pdf(PDF_ROWS), NOW, real_slate, source_url="https://example.invalid/x.pdf"
    )
    assert [e.player_id for e in entries] == [
        "player:devin-carter",
        "player:elijah-harkless",
        "player:isaac-jones",
    ]
    assert [e.team_id for e in entries] == ["nba:BOS", "nba:DET", "nba:DET"]
    assert entries[0].report_timestamp_utc == REPORT_TS
    assert entries[0].event_id == "fixture:BOS@DET"
    assert entries[0].stamp.source_url == "https://example.invalid/x.pdf"


def test_parse_pdf_rejects_garbage():
    with pytest.raises(ProviderError) as exc:
        R.parse_injury_report_pdf(b"not a pdf", NOW)
    assert exc.value.reason_codes == ["PROVIDER_ERROR"]


# --------------------------------------------------------------------------------------
# Fetching (respx; HEAD then GET; 403 = missing slot)
# --------------------------------------------------------------------------------------


def test_fetch_latest_report_skips_missing_slots(real_slate):
    now = datetime(2026, 10, 19, 23, 37, tzinfo=UTC)  # 19:37 ET: slots 07:30, 07:15 missing; 07:00 exists
    pdf = make_pdf(PDF_ROWS)
    hit = "Injury-Report_2026-10-19_07_00PM.pdf"
    with respx.mock(assert_all_called=False) as router:
        router.head(url__regex=r".*/Injury-Report_.*\.pdf").mock(
            side_effect=lambda request: httpx.Response(200 if request.url.path.endswith(hit) else 403)
        )
        get_route = router.get(url__regex=r".*/Injury-Report_.*\.pdf").mock(
            side_effect=lambda request: (
                httpx.Response(200, content=pdf, headers={"content-type": "application/pdf"})
                if request.url.path.endswith(hit)
                else httpx.Response(403)
            )
        )
        with httpx.Client() as client:
            result = R.fetch_latest_report(now, real_slate, client, FixedClock(now))
    assert get_route.call_count == 1
    assert result.stamp.source_url is not None and result.stamp.source_url.endswith(hit)
    assert result.stamp.source_timestamp_utc == REPORT_TS
    assert result.stamp.received_at_utc == now
    assert [e.player_id for e in result.data] == [
        "player:devin-carter",
        "player:elijah-harkless",
        "player:isaac-jones",
    ]
    assert any("2 newer slot(s) were missing" in w for w in result.warnings)
    assert result.reason_codes == []


def test_fetch_latest_report_stops_after_consecutive_misses(real_slate):
    now = datetime(2026, 10, 19, 23, 7, tzinfo=UTC)
    with respx.mock(assert_all_called=False) as router:
        head = router.head(url__regex=r".*/Injury-Report_.*\.pdf").mock(return_value=httpx.Response(404))
        with httpx.Client() as client:
            result = R.fetch_latest_report(now, real_slate, client, FixedClock(now))
    assert head.call_count == 8
    assert result.data == []
    assert result.reason_codes == ["INJURY_REPORT_MISSING"]
    assert result.stamp.source_timestamp_utc is None


def test_fetch_latest_report_server_error_is_provider_error(real_slate):
    now = datetime(2026, 10, 19, 23, 7, tzinfo=UTC)
    with respx.mock(assert_all_called=False) as router:
        router.head(url__regex=r".*/Injury-Report_.*\.pdf").mock(return_value=httpx.Response(503))
        with httpx.Client() as client, pytest.raises(ProviderError) as exc:
            R.fetch_latest_report(now, real_slate, client, FixedClock(now))
    assert exc.value.reason_codes == ["PROVIDER_ERROR"]


def test_injury_provider_protocol_object(real_slate):
    now = datetime(2026, 10, 19, 23, 7, tzinfo=UTC)
    with respx.mock(assert_all_called=False) as router:
        router.head(url__regex=r".*/Injury-Report_.*\.pdf").mock(return_value=httpx.Response(403))
        with httpx.Client() as client:
            provider = R.NbaInjuryReportProvider(client, FixedClock(now), lookback_hours=1)
            assert provider.name == "nba-official-injury-report"
            result = provider.fetch_latest_report(now, real_slate)
    assert result.reason_codes == ["INJURY_REPORT_MISSING"]


# --------------------------------------------------------------------------------------
# Manual entries
# --------------------------------------------------------------------------------------


def test_manual_injury_entries():
    entries = R.manual_injury_entries(
        [
            {
                "event_id": "fixture:PHI@NYK",
                "team": "NYK",
                "player": "Jalen Brunson",
                "status": "Questionable",
                "reason": "Ankle",
                "report_timestamp_utc": "2026-10-20T16:00:00Z",
            },
            {"event_id": "fixture:PHI@NYK", "team": "Philadelphia 76ers", "status": "NOT YET SUBMITTED"},
            {"event_id": "fixture:PHI@NYK", "player": "Tyrese Maxey", "status": "not listed"},
        ],
        NOW,
    )
    assert entries[0].stamp.data_mode == S.DataMode.MANUAL_INPUT and entries[0].stamp.source == "user"
    assert entries[0].player_id == "player:jalen-brunson" and entries[0].team_id == "nba:NYK"
    assert entries[0].designation == S.InjuryDesignation.QUESTIONABLE
    assert entries[0].report_timestamp_utc == datetime(2026, 10, 20, 16, 0, tzinfo=UTC)
    assert (
        entries[1].designation == S.InjuryDesignation.UNKNOWN
        and entries[1].player_name_raw == "NOT YET SUBMITTED"
    )
    assert entries[2].designation == S.InjuryDesignation.NOT_LISTED and entries[2].team_id is None
    with pytest.raises(InvalidInput) as exc:
        R.manual_injury_entries(
            [{"event_id": "x", "team": "Lost Angeles", "player": "A B", "status": "Out"}], NOW
        )
    assert exc.value.reason_codes == ["TEAM_UNMATCHED"]
    with pytest.raises(InvalidInput) as exc:
        R.manual_injury_entries([{"event_id": "x", "status": "Out"}], NOW)
    assert exc.value.reason_codes == ["PLAYER_UNMATCHED"]
    with pytest.raises(InvalidInput):
        R.manual_injury_entries([{"event_id": "x", "player": "A B", "status": "Maybe"}], NOW)


# --------------------------------------------------------------------------------------
# injury_for_selection
# --------------------------------------------------------------------------------------


def _entry(event, team, player, designation, *, report_ts=None, reason="Injury/Illness - Test"):
    report_ts = report_ts or (NOW - timedelta(hours=1))
    return S.InjuryContext(
        event_id=event.event_id,
        team_id=team.team_id if team else None,
        player_id=f"player:{player.lower().replace(' ', '-')}" if player else None,
        player_name_raw=player,
        designation=designation,
        reason=reason,
        report_timestamp_utc=report_ts,
        stamp=stamp(source="nba-official-injury-report", mode=S.DataMode.LIVE_PROVIDER, source_ts=report_ts),
    )


def _not_submitted(event, team, report_ts=None):
    report_ts = report_ts or (NOW - timedelta(hours=1))
    return S.InjuryContext(
        event_id=event.event_id,
        team_id=team.team_id,
        designation=S.InjuryDesignation.UNKNOWN,
        player_name_raw="NOT YET SUBMITTED",
        report_timestamp_utc=report_ts,
        stamp=stamp(source="nba-official-injury-report", mode=S.DataMode.LIVE_PROVIDER, source_ts=report_ts),
    )


@pytest.fixture
def prop_leg(three_game_slate):
    event = three_game_slate[1]
    quote = make_quote(
        event, S.MarketType.PLAYER_POINTS, S.Side.OVER, "1.87", line="24.5", player="Jalen Brunson"
    )
    return make_selection(quote, event, "Jalen Brunson over 24.5 points")


@pytest.fixture
def team_leg(three_game_slate):
    event = three_game_slate[1]
    quote = make_quote(event, S.MarketType.SPREAD, S.Side.HOME, "1.91", line="-6.5", team=TEAMS["NYK"])
    return make_selection(quote, event, "NYK -6.5")


MAX_AGE = 6 * 3600


@pytest.mark.parametrize(
    ("designation", "decision", "codes", "material"),
    [
        (S.InjuryDesignation.OUT, S.LegDecision.UNUSABLE, ["INJURY_OUT"], True),
        (S.InjuryDesignation.DOUBTFUL, S.LegDecision.UNUSABLE, ["INJURY_DOUBTFUL"], True),
        (
            S.InjuryDesignation.QUESTIONABLE,
            S.LegDecision.WAIT_FOR_UPDATE,
            ["INJURY_QUESTIONABLE_MATERIAL"],
            True,
        ),
        (S.InjuryDesignation.PROBABLE, S.LegDecision.USABLE, [], False),
        (S.InjuryDesignation.AVAILABLE, S.LegDecision.USABLE, [], False),
    ],
)
def test_player_market_decisions(prop_leg, designation, decision, codes, material):
    report = [
        _entry(prop_leg.event, TEAMS["NYK"], "Jalen Brunson", designation),
        _entry(prop_leg.event, TEAMS["PHI"], "Tyrese Maxey", S.InjuryDesignation.OUT),
    ]
    entries, got_decision, got_codes = IC.injury_for_selection(prop_leg, report, MAX_AGE, NOW)
    assert got_decision == decision
    assert got_codes == codes
    assert len(entries) == 1 and entries[0].player_id == "player:jalen-brunson"
    assert entries[0].material_to_selection is material
    assert entries[0].note


def test_player_not_listed_adds_fact(prop_leg):
    report = [
        _entry(
            prop_leg.event,
            TEAMS["PHI"],
            "Tyrese Maxey",
            S.InjuryDesignation.OUT,
            report_ts=NOW - timedelta(hours=2),
        )
    ]
    entries, decision, codes = IC.injury_for_selection(prop_leg, report, MAX_AGE, NOW)
    assert decision == S.LegDecision.USABLE and codes == []
    assert len(entries) == 1
    assert entries[0].designation == S.InjuryDesignation.NOT_LISTED
    assert entries[0].player_id == "player:jalen-brunson"
    assert (
        entries[0].note is not None
        and "not listed on the 2026-10-20T13:00:00-04:00 report" in entries[0].note
    )
    assert entries[0].material_to_selection is False


def test_player_name_match_without_player_id(prop_leg):
    entry = _entry(prop_leg.event, TEAMS["NYK"], "Brunson, Jalen", S.InjuryDesignation.OUT).model_copy(
        update={"player_id": None}
    )
    entries, decision, codes = IC.injury_for_selection(prop_leg, [entry], MAX_AGE, NOW)
    assert decision == S.LegDecision.UNUSABLE and codes == ["INJURY_OUT"]


def test_team_market_lists_both_teams_and_keeps_usable(team_leg):
    report = [
        _entry(team_leg.event, TEAMS["NYK"], "Jalen Brunson", S.InjuryDesignation.QUESTIONABLE),
        _entry(team_leg.event, TEAMS["PHI"], "Tyrese Maxey", S.InjuryDesignation.OUT),
        _entry(team_leg.event, TEAMS["PHI"], "Paul George", S.InjuryDesignation.PROBABLE),
        _entry(
            make_event("BOS", "DET"), TEAMS["BOS"], "Jaylen Brown", S.InjuryDesignation.OUT
        ),  # other game, excluded
    ]
    entries, decision, codes = IC.injury_for_selection(team_leg, report, MAX_AGE, NOW)
    assert decision == S.LegDecision.USABLE
    assert codes == ["INJURY_QUESTIONABLE_IMMATERIAL"]
    assert [e.player_id for e in entries] == [
        "player:jalen-brunson",
        "player:tyrese-maxey",
        "player:paul-george",
    ]
    assert entries[0].material_to_selection is None and entries[1].material_to_selection is None
    assert entries[2].material_to_selection is False
    assert "Judge materiality yourself" in (entries[0].note or "")
    assert "nba:PHI" in (entries[1].note or "")


def test_stale_and_missing_reports(prop_leg, team_leg):
    stale_ts = NOW - timedelta(seconds=MAX_AGE + 1)
    report = [
        _entry(
            prop_leg.event, TEAMS["NYK"], "Jalen Brunson", S.InjuryDesignation.PROBABLE, report_ts=stale_ts
        )
    ]
    entries, decision, codes = IC.injury_for_selection(prop_leg, report, MAX_AGE, NOW)
    assert decision == S.LegDecision.USABLE and codes == ["INJURY_REPORT_STALE"]
    exact = [
        _entry(
            prop_leg.event,
            TEAMS["NYK"],
            "Jalen Brunson",
            S.InjuryDesignation.PROBABLE,
            report_ts=NOW - timedelta(seconds=MAX_AGE),
        )
    ]
    assert IC.injury_for_selection(prop_leg, exact, MAX_AGE, NOW)[2] == []
    report = [
        _entry(prop_leg.event, TEAMS["NYK"], "Jalen Brunson", S.InjuryDesignation.OUT, report_ts=stale_ts)
    ]
    _, decision, codes = IC.injury_for_selection(prop_leg, report, MAX_AGE, NOW)
    assert decision == S.LegDecision.UNUSABLE and codes == ["INJURY_REPORT_STALE", "INJURY_OUT"]
    assert IC.injury_for_selection(team_leg, [], MAX_AGE, NOW) == (
        [],
        S.LegDecision.USABLE,
        ["INJURY_REPORT_MISSING"],
    )


def test_not_yet_submitted_forces_wait(prop_leg, team_leg):
    report = [
        _not_submitted(prop_leg.event, TEAMS["NYK"]),
        _entry(prop_leg.event, TEAMS["PHI"], "Tyrese Maxey", S.InjuryDesignation.OUT),
    ]
    entries, decision, codes = IC.injury_for_selection(prop_leg, report, MAX_AGE, NOW)
    assert decision == S.LegDecision.WAIT_FOR_UPDATE and codes == ["WAIT_FOR_UPDATE"]
    assert any(e.player_name_raw == "NOT YET SUBMITTED" for e in entries)
    # player's team known and it is the OTHER team that has not submitted -> no wait
    leg_with_team = prop_leg.model_copy(
        update={"player": prop_leg.player.model_copy(update={"team_id": "nba:NYK"})}
    )
    report = [_not_submitted(prop_leg.event, TEAMS["PHI"])]
    _, decision, codes = IC.injury_for_selection(leg_with_team, report, MAX_AGE, NOW)
    assert decision == S.LegDecision.USABLE and codes == []
    # player's team unknown and a team has not submitted -> wait (conservative)
    _, decision, codes = IC.injury_for_selection(prop_leg, report, MAX_AGE, NOW)
    assert decision == S.LegDecision.WAIT_FOR_UPDATE
    # team market: either team not submitted -> wait
    entries, decision, codes = IC.injury_for_selection(
        team_leg, [_not_submitted(team_leg.event, TEAMS["PHI"])], MAX_AGE, NOW
    )
    assert decision == S.LegDecision.WAIT_FOR_UPDATE and codes == ["WAIT_FOR_UPDATE"]


def test_materiality_note_text(prop_leg, team_leg):
    q = _entry(prop_leg.event, TEAMS["NYK"], "Jalen Brunson", S.InjuryDesignation.QUESTIONABLE)
    assert "QUESTIONABLE" in IC.materiality_note(prop_leg, q)
    assert "does not have" in IC.materiality_note(team_leg, q)
    assert IC.report_timestamp([]) is None
