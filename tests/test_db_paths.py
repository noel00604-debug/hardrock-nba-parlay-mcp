"""A fresh install must be able to open its SQLite ledger even when the folder does not exist yet."""

from hardrock_nba_parlay.db import open_database


def test_sqlite_parent_folder_is_created(tmp_path):
    target = tmp_path / "nested" / "deeper" / "ledger.db"
    db = open_database(f"sqlite:///{target}")
    assert target.is_file() and db.ping()
    db.dispose()
