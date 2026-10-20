"""normalization.py: team aliases, player slugs, event matching, descriptions, reference pairing."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from conftest import NOW, TEAMS, make_event, make_quote, make_selection

from hardrock_nba_parlay import normalization as N
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.errors import InvalidInput

# --------------------------------------------------------------------------------------
# Teams
# --------------------------------------------------------------------------------------


def test_thirty_teams_with_unique_ids():
    assert len(N.NBA_TEAMS) == 30
    ids = {t.team_id for t in N.NBA_TEAMS}
    assert len(ids) == 30


@pytest.mark.parametrize("record", N.NBA_TEAMS, ids=lambda r: r.abbreviation)
def test_every_team_resolves_by_abbreviation_name_and_nickname(record):
    for spelling in (
        record.abbreviation,
        record.abbreviation.lower(),
        record.name,
        record.name.upper(),
        record.nickname,
    ):
        team = N.canonical_team(spelling)
        assert team.team_id == record.team_id, spelling
        assert team.name == record.name
        assert team.abbreviation == record.abbreviation
    for alias in record.aliases:
        if alias in ("LA",):
            continue  # deliberately ambiguous
        assert N.canonical_team(alias).team_id == record.team_id, alias


@pytest.mark.parametrize(
    ("spelling", "team_id"),
    [
        ("Sixers", "nba:PHI"),
        ("Philly", "nba:PHI"),
        ("Blazers", "nba:POR"),
        ("Trail Blazers", "nba:POR"),
        ("Wolves", "nba:MIN"),
        ("T-Wolves", "nba:MIN"),
        ("Cavs", "nba:CLE"),
        ("Mavs", "nba:DAL"),
        ("LA Clippers", "nba:LAC"),
        ("Los Angeles Clippers", "nba:LAC"),
        ("L.A. Clippers", "nba:LAC"),
        ("Los Angeles Lakers", "nba:LAL"),
        ("LA Lakers", "nba:LAL"),
        ("New York", "nba:NYK"),
        ("NY", "nba:NYK"),
        ("Brooklyn", "nba:BKN"),
        ("BRK", "nba:BKN"),
        ("GS", "nba:GSW"),
        ("PHO", "nba:PHX"),
        ("NOLA", "nba:NOP"),
        ("Golden State", "nba:GSW"),
        ("the Celtics", "nba:BOS"),
        ("Oklahoma City", "nba:OKC"),
        ("San Antonio", "nba:SAS"),
    ],
)
def test_alias_spellings(spelling, team_id):
    assert N.canonical_team(spelling).team_id == team_id


@pytest.mark.parametrize("spelling", ["LA", "Los Angeles", "Lakerss", "", "Heat Celtics", "NBA"])
def test_unknown_or_ambiguous_team_raises(spelling):
    with pytest.raises(InvalidInput) as exc:
        N.canonical_team(spelling)
    assert exc.value.reason_codes == ["TEAM_UNMATCHED"]
    assert N.try_canonical_team(spelling) is None


def test_conftest_teams_match_canonical_table():
    for abbr, team in TEAMS.items():
        assert N.canonical_team(abbr) == team
        assert N.team_by_id(team.team_id) == team


# --------------------------------------------------------------------------------------
# Players
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "player_id", "display"),
    [
        ("Jalen Brunson", "player:jalen-brunson", "Jalen Brunson"),
        ("  jalen   brunson ", "player:jalen-brunson", "jalen brunson"),
        ("Luka Dončić", "player:luka-doncic", "Luka Dončić"),
        ("Dončić, Luka", "player:luka-doncic", "Luka Dončić"),
        ("Jaren Jackson Jr.", "player:jaren-jackson", "Jaren Jackson Jr."),
        ("Porter Jr., Michael", "player:michael-porter", "Michael Porter Jr."),
        ("Gilgeous-Alexander, Shai", "player:shai-gilgeous-alexander", "Shai Gilgeous-Alexander"),
        ("Robert Williams III", "player:robert-williams", "Robert Williams III"),
        ("P.J. Washington", "player:p-j-washington", "P.J. Washington"),
    ],
)
def test_canonical_player_slugs(name, player_id, display):
    player = N.canonical_player(name, None)
    assert player.player_id == player_id
    assert player.name == display
    assert player.team_id is None


def test_canonical_player_team_hint_and_blank():
    player = N.canonical_player("Jalen Brunson", TEAMS["NYK"])
    assert player.team_id == "nba:NYK"
    with pytest.raises(InvalidInput) as exc:
        N.canonical_player("   ", None)
    assert exc.value.reason_codes == ["PLAYER_UNMATCHED"]


# --------------------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("BOS@DET", "fixture:BOS@DET"),
        ("BOS @ DET", "fixture:BOS@DET"),
        ("bos@det", "fixture:BOS@DET"),
        ("Boston Celtics at Detroit Pistons", "fixture:BOS@DET"),
        ("Celtics at Pistons", "fixture:BOS@DET"),
        ("DET vs BOS", "fixture:BOS@DET"),
        ("Pistons vs. Celtics", "fixture:BOS@DET"),
        ("Knicks v Sixers", "fixture:PHI@NYK"),
        ("fixture:OKC@SAS", "fixture:OKC@SAS"),
        ("Knicks", "fixture:PHI@NYK"),
        ("Thunder @ Spurs", "fixture:OKC@SAS"),
    ],
)
def test_match_event_formats(three_game_slate, text, expected):
    assert N.match_event(text, three_game_slate).event_id == expected


@pytest.mark.parametrize("text", ["MIA@ORL", "BOS@XYZ", "LA @ BOS", "", "Celtics vs Knicks", "nothing here"])
def test_match_event_unmatched(three_game_slate, text):
    with pytest.raises(InvalidInput) as exc:
        N.match_event(text, three_game_slate)
    assert exc.value.reason_codes == ["EVENT_UNMATCHED"]


def test_match_event_ambiguous_pair_and_single_team():
    slate = [
        make_event("BOS", "DET", event_id="fixture:BOS@DET:1"),
        make_event("BOS", "DET", start=NOW + timedelta(days=1), event_id="fixture:BOS@DET:2"),
        make_event("PHI", "NYK"),
    ]
    with pytest.raises(InvalidInput) as exc:
        N.match_event("BOS@DET", slate)
    assert exc.value.reason_codes == ["EVENT_UNMATCHED"]
    assert "ambiguous" in exc.value.message
    with pytest.raises(InvalidInput):
        N.match_event("Celtics", slate)
    assert N.match_event("Knicks", slate).event_id == "fixture:PHI@NYK"


# --------------------------------------------------------------------------------------
# Selections
# --------------------------------------------------------------------------------------


def test_build_selections_descriptions_and_ids(three_game_slate):
    e1, e2, e3 = three_game_slate
    quotes = [
        make_quote(e1, S.MarketType.SPREAD, S.Side.HOME, "1.91", line="3.5", team=TEAMS["DET"]),
        make_quote(e1, S.MarketType.SPREAD, S.Side.AWAY, "1.91", line="-3.5", team=TEAMS["BOS"]),
        make_quote(e2, S.MarketType.TOTAL, S.Side.OVER, "1.91", line="224.5"),
        make_quote(e2, S.MarketType.PLAYER_POINTS, S.Side.OVER, "1.87", line="24.5", player="Jalen Brunson"),
        make_quote(
            e2,
            S.MarketType.PLAYER_POINTS,
            S.Side.OVER,
            "3.00",
            line="29.5",
            player="Jalen Brunson",
            is_alternate=True,
        ),
        make_quote(e3, S.MarketType.MONEYLINE, S.Side.AWAY, "1.60", team=TEAMS["OKC"]),
        make_quote(e3, S.MarketType.PLAYER_THREES, S.Side.UNDER, "1.87", line="2.5", player="Jaylen Brown"),
    ]
    selections = N.build_selections(quotes, three_game_slate)
    assert [s.description for s in selections] == [
        "DET +3.5 (full game)",
        "BOS -3.5 (full game)",
        "PHI/NYK over 224.5 (full game)",
        "Jalen Brunson over 24.5 points",
        "Jalen Brunson over 29.5 points (alternate, full game)",
        "OKC moneyline (full game)",
        "Jaylen Brown under 2.5 made threes",
    ]
    assert selections[0].team == TEAMS["DET"]
    assert selections[3].player is not None and selections[3].player.player_id == "player:jalen-brunson"
    assert selections[2].team is None
    for sel, quote in zip(selections, quotes, strict=True):
        assert sel.selection_id == N.selection_id_for(quote) == S.compute_selection_id(quote)
    # dict input and unknown events
    by_id = {e.event_id: e for e in three_game_slate}
    assert len(N.build_selections(quotes, by_id)) == 7
    orphan = make_quote(
        make_event("MIA", "ORL") if "MIA" in TEAMS else e1,
        S.MarketType.TOTAL,
        S.Side.OVER,
        "1.9",
        line="200.5",
    )
    orphan = orphan.model_copy(update={"event_id": "fixture:nope"})
    assert N.build_selections([orphan], by_id) == []
    with pytest.raises(InvalidInput) as exc:
        N.build_selections([orphan], by_id, strict=True)
    assert exc.value.reason_codes == ["EVENT_UNMATCHED"]


# --------------------------------------------------------------------------------------
# Reference pairing
# --------------------------------------------------------------------------------------


def _ref_quotes(event, market, pairs, *, book="pinnacle", player=None, source_ts=None):
    out = []
    for side, line, odds, ts in pairs:
        out.append(
            make_quote(
                event,
                market,
                side,
                odds,
                line=line,
                player=player,
                team=(event.home_team if side == S.Side.HOME else event.away_team)
                if market in (S.MarketType.SPREAD, S.MarketType.MONEYLINE)
                else None,
                book=book,
                source_ts=ts if ts is not None else source_ts,
            )
        )
    return out


def test_pair_reference_complementary_spread_home_and_away(three_game_slate):
    e1 = three_game_slate[0]
    refs = _ref_quotes(
        e1, S.MarketType.SPREAD, [(S.Side.HOME, "3.5", "1.93", None), (S.Side.AWAY, "-3.5", "1.89", None)]
    )
    home = make_selection(
        make_quote(e1, S.MarketType.SPREAD, S.Side.HOME, "1.91", line="3.5", team=TEAMS["DET"]), e1
    )
    away = make_selection(
        make_quote(e1, S.MarketType.SPREAD, S.Side.AWAY, "1.91", line="-3.5", team=TEAMS["BOS"]), e1
    )
    ref, reasons = N.pair_reference_with_reasons(home, refs)
    assert reasons == [] and ref is not None
    assert ref.book == "pinnacle" and ref.line == Decimal("3.5")
    assert ref.side_a == S.Side.HOME and ref.odds_a == Decimal("1.93")
    assert ref.side_b == S.Side.AWAY and ref.odds_b == Decimal("1.89")
    ref_away = N.pair_reference(away, refs)
    assert ref_away is not None and ref_away.line == Decimal("3.5")
    assert ref_away.odds_for(S.Side.AWAY) == Decimal("1.89")


def test_pair_reference_non_complementary_handicap_is_incomplete(three_game_slate):
    e1 = three_game_slate[0]
    refs = _ref_quotes(
        e1, S.MarketType.SPREAD, [(S.Side.HOME, "3.5", "1.93", None), (S.Side.AWAY, "-4", "1.89", None)]
    )
    sel = make_selection(
        make_quote(e1, S.MarketType.SPREAD, S.Side.HOME, "1.91", line="3.5", team=TEAMS["DET"]), e1
    )
    ref, reasons = N.pair_reference_with_reasons(sel, refs)
    assert ref is None and reasons == ["REFERENCE_INCOMPLETE"]


def test_pair_reference_line_mismatch(three_game_slate):
    e2 = three_game_slate[1]
    refs = _ref_quotes(
        e2,
        S.MarketType.PLAYER_POINTS,
        [(S.Side.OVER, "25.5", "1.91", None), (S.Side.UNDER, "25.5", "1.91", None)],
        player="Jalen Brunson",
    )
    sel = make_selection(
        make_quote(e2, S.MarketType.PLAYER_POINTS, S.Side.OVER, "1.87", line="24.5", player="Jalen Brunson"),
        e2,
    )
    ref, reasons = N.pair_reference_with_reasons(sel, refs)
    assert ref is None and reasons == ["LINE_MISMATCH"]
    # a single side at another line is both a mismatch and incomplete
    ref, reasons = N.pair_reference_with_reasons(sel, refs[:1])
    assert ref is None and reasons == ["LINE_MISMATCH", "REFERENCE_INCOMPLETE"]


def test_pair_reference_requires_same_snapshot(three_game_slate):
    e2 = three_game_slate[1]
    refs = _ref_quotes(
        e2,
        S.MarketType.TOTAL,
        [
            (S.Side.OVER, "224.5", "1.91", NOW - timedelta(seconds=30)),
            (S.Side.UNDER, "224.5", "1.91", NOW - timedelta(seconds=90)),
        ],
    )
    sel = make_selection(make_quote(e2, S.MarketType.TOTAL, S.Side.OVER, "1.91", line="224.5"), e2)
    ref, reasons = N.pair_reference_with_reasons(sel, refs)
    assert ref is None and reasons == ["REFERENCE_INCOMPLETE"]


def test_pair_reference_missing_and_wrong_player(three_game_slate):
    e1, e2, _ = three_game_slate
    sel = make_selection(
        make_quote(e2, S.MarketType.PLAYER_POINTS, S.Side.OVER, "1.87", line="24.5", player="Jalen Brunson"),
        e2,
    )
    other_event = _ref_quotes(
        e1, S.MarketType.TOTAL, [(S.Side.OVER, "221.5", "1.9", None), (S.Side.UNDER, "221.5", "1.9", None)]
    )
    other_player = _ref_quotes(
        e2,
        S.MarketType.PLAYER_POINTS,
        [(S.Side.OVER, "24.5", "1.9", None), (S.Side.UNDER, "24.5", "1.9", None)],
        player="Tyrese Maxey",
    )
    assert N.pair_reference_with_reasons(sel, []) == (None, ["REFERENCE_MISSING"])
    assert N.pair_reference_with_reasons(sel, other_event) == (None, ["REFERENCE_MISSING"])
    assert N.pair_reference_with_reasons(sel, other_player) == (None, ["REFERENCE_MISSING"])


def test_pair_reference_moneyline_and_preferred_book(three_game_slate):
    e3 = three_game_slate[2]
    pinnacle = _ref_quotes(
        e3, S.MarketType.MONEYLINE, [(S.Side.HOME, None, "2.45", None), (S.Side.AWAY, None, "1.62", None)]
    )
    dk = _ref_quotes(
        e3,
        S.MarketType.MONEYLINE,
        [(S.Side.HOME, None, "2.40", None), (S.Side.AWAY, None, "1.60", None)],
        book="draftkings",
    )
    sel = make_selection(make_quote(e3, S.MarketType.MONEYLINE, S.Side.AWAY, "1.60", team=TEAMS["OKC"]), e3)
    ref = N.pair_reference(sel, dk + pinnacle, preferred_books=["pinnacle", "draftkings"])
    assert ref is not None and ref.book == "pinnacle" and ref.line is None
    ref = N.pair_reference(sel, dk + pinnacle, preferred_books=["draftkings"])
    assert ref is not None and ref.book == "draftkings"


def test_pair_reference_ignores_other_period(three_game_slate):
    e2 = three_game_slate[1]
    refs = _ref_quotes(
        e2, S.MarketType.TOTAL, [(S.Side.OVER, "224.5", "1.91", None), (S.Side.UNDER, "224.5", "1.91", None)]
    )
    refs = [r.model_copy(update={"period": S.Period.FIRST_HALF}) for r in refs]
    sel = make_selection(make_quote(e2, S.MarketType.TOTAL, S.Side.OVER, "1.91", line="224.5"), e2)
    assert N.pair_reference_with_reasons(sel, refs) == (None, ["REFERENCE_MISSING"])


def test_format_line():
    assert N.format_line(Decimal("3.50"), signed=True) == "+3.5"
    assert N.format_line(Decimal("-3.5"), signed=True) == "-3.5"
    assert N.format_line(Decimal("224.5")) == "224.5"
    assert N.format_line(Decimal("3")) == "3"
    assert N.format_line(None) == ""


def test_pair_reference_never_uses_the_selection_own_book(three_game_slate):
    # The providers return target and reference books in one list; the target must never benchmark itself.
    e1 = three_game_slate[0]
    target = make_quote(e1, S.MarketType.TOTAL, S.Side.OVER, "1.91", line="221.5")
    sel = make_selection(target, e1)
    own_two_way = [target, make_quote(e1, S.MarketType.TOTAL, S.Side.UNDER, "1.91", line="221.5")]
    assert N.pair_reference_with_reasons(sel, own_two_way) == (None, ["REFERENCE_MISSING"])
    pinnacle = [
        make_quote(e1, S.MarketType.TOTAL, side, "1.95", line="221.5", book="pinnacle")
        for side in (S.Side.OVER, S.Side.UNDER)
    ]
    ref = N.pair_reference(sel, own_two_way + pinnacle)
    assert ref is not None and ref.book == "pinnacle" and ref.line == Decimal("221.5")
    # a different line at the reference book is LINE_MISMATCH even though the target's own line "matches"
    other_line = [
        make_quote(e1, S.MarketType.TOTAL, side, "1.95", line="222.5", book="pinnacle")
        for side in (S.Side.OVER, S.Side.UNDER)
    ]
    assert N.pair_reference_with_reasons(sel, own_two_way + other_line, preferred_books=["pinnacle"]) == (
        None,
        ["LINE_MISMATCH"],
    )
