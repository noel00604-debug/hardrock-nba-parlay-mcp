"""Regression test on the real 2026-10-19 10:00 PM ET injury report as extracted by ``pdftotext -layout``."""

from datetime import UTC, datetime
from pathlib import Path

from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.providers import nba_injury_report as R

FIXTURE = Path(__file__).parent / "fixtures" / "injury_report_2026-10-19_10_00PM_pdftotext.txt"


def _by_player(entries):
    return {e.player_name_raw: e for e in entries}


def test_live_layout_header_and_wrapped_reasons():
    now = datetime(2026, 10, 20, 2, 5, tzinfo=UTC)
    entries = R.parse_injury_report_text(FIXTURE.read_text(encoding="utf-8"), now, slate=None, source_url="x")
    assert entries[0].report_timestamp_utc == datetime(2026, 10, 20, 2, 0, tzinfo=UTC)  # 10:00 PM ET
    by = _by_player(entries)
    assert by["Taurean Prince"].reason == "Personal Reasons"
    assert by["Taurean Prince"].designation is S.InjuryDesignation.QUESTIONABLE
    assert by["Dominick Barlow"].reason == "Injury/Illness - Low Back Stress Reaction"
    assert by["Dominick Barlow"].team_id == "nba:PHI"
    assert by["Ariel Hukporti"].reason == "Injury/Illness - Right Achilles Tendon Rupture / Tear"
    assert by["Anfernee Simons"].reason == "Injury/Illness - Left Hamstring Tightness / Soreness"
    assert by["Otega Oweh"].reason == "Injury/Illness - Right Achilles Tendon Repair / Surgery"
    assert by["Otega Oweh"].team_id == "nba:OKC"
    assert by["Tobias Harris"].team_id == "nba:SAS"
    assert (
        by["Devin Carter"].designation is S.InjuryDesignation.OUT and by["Devin Carter"].team_id == "nba:BOS"
    )


def test_pdftotext_helper_returns_none_without_binary(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert R._pdftotext_layout(b"%PDF-1.4") is None
