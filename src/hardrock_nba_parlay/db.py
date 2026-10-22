"""Database layer (docs/ARCHITECTURE.md section 4): SQLAlchemy Core, SQLite (WAL) or PostgreSQL.

- Short transactions via `Database.tx()`.
- SQLite transactions start with BEGIN IMMEDIATE so concurrent writers serialise instead of deadlocking.
- PostgreSQL per-user-day row lock via `lock_user_day` (SELECT ... FOR UPDATE).
- Money stored as integer cents; odds/probabilities as decimal strings; timestamps as ISO-8601 UTC 'Z'.
- Fixture-mode records are refused in ledger tables unless the database was opened with allow_fixture_ledger=True.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import (
    Column,
    Connection,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    insert,
    select,
    text,
)
from sqlalchemy.engine import Engine

SCHEMA_VERSION = 1

metadata = MetaData()

schema_migrations = Table(
    "schema_migrations",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("applied_at", Text, nullable=False),
)
users = Table(
    "users",
    metadata,
    Column("user_id", Text, primary_key=True),
    Column("email", Text, nullable=True, unique=True),
    Column("display_name", Text, nullable=True),
    Column("disabled", Integer, nullable=False, default=0),
    Column("created_at", Text, nullable=False),
)
user_settings = Table(
    "user_settings",
    metadata,
    Column("user_id", Text, primary_key=True),
    Column("daily_cap_cents", Integer, nullable=False),
    Column("display_tz", Text, nullable=False),
    Column("onboarding_complete", Integer, nullable=False, default=0),
    Column("odds_api_key_encrypted", Text, nullable=True),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
)
user_days = Table(
    "user_days",
    metadata,
    Column("user_id", Text, primary_key=True),
    Column("date_local", Text, primary_key=True),
    Column("created_at", Text, nullable=False),
)
oauth_clients = Table(
    "oauth_clients",
    metadata,
    Column("client_id", Text, primary_key=True),
    Column("client_json", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)
oauth_codes = Table(
    "oauth_codes",
    metadata,
    Column("code", Text, primary_key=True),
    Column("client_id", Text, nullable=False),
    Column("user_id", Text, nullable=False),
    Column("json", Text, nullable=False),
    Column("expires_at", Text, nullable=False),
)
oauth_tokens = Table(
    "oauth_tokens",
    metadata,
    Column("token", Text, primary_key=True),
    Column("kind", Text, nullable=False),  # access | refresh
    Column("client_id", Text, nullable=False),
    Column("user_id", Text, nullable=False),
    Column("scopes", Text, nullable=False),
    Column("expires_at", Text, nullable=True),
    Column("revoked", Integer, nullable=False, default=0),
    Column("created_at", Text, nullable=False),
)
credentials = Table(
    "credentials",
    metadata,
    Column("user_id", Text, primary_key=True),
    Column("password_hash", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
)
login_attempts = Table(
    "login_attempts",
    metadata,
    Column("key", Text, primary_key=True),
    Column("window_start", Text, nullable=False),
    Column("count", Integer, nullable=False),
)
events_cache = Table(
    "events_cache",
    metadata,
    Column("event_id", Text, primary_key=True),
    Column("json", Text, nullable=False),
    Column("received_at", Text, nullable=False),
)
odds_snapshots = Table(
    "odds_snapshots",
    metadata,
    Column("snapshot_id", Text, primary_key=True),
    Column("user_id", Text, nullable=True),
    Column("event_id", Text, nullable=False),
    Column("book", Text, nullable=False),
    Column("market_type", Text, nullable=False),
    Column("period", Text, nullable=False),
    Column("is_alternate", Integer, nullable=False),
    Column("side", Text, nullable=False),
    Column("line", Text, nullable=True),
    Column("player_id", Text, nullable=True),
    Column("odds_decimal", Text, nullable=False),
    Column("source_ts", Text, nullable=True),
    Column("received_at", Text, nullable=False),
    Column("data_mode", Text, nullable=False),
    Column("json", Text, nullable=False),
    Index("ix_odds_event_book_recv", "event_id", "book", "received_at"),
)
injury_snapshots = Table(
    "injury_snapshots",
    metadata,
    Column("snapshot_id", Text, primary_key=True),
    Column("report_ts", Text, nullable=True),
    Column("event_id", Text, nullable=False),
    Column("team_id", Text, nullable=True),
    Column("player_id", Text, nullable=True),
    Column("designation", Text, nullable=False),
    Column("json", Text, nullable=False),
    Column("received_at", Text, nullable=False),
    Index("ix_injury_event_recv", "event_id", "received_at"),
)
candidates = Table(
    "candidates",
    metadata,
    Column("candidate_id", Text, primary_key=True),
    Column("user_id", Text, nullable=False),
    Column("date_local", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("parlay_type", Text, nullable=False),
    Column("data_mode", Text, nullable=False),
    Column("json", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Column("expires_at", Text, nullable=False),
    Index("ix_candidates_user_date", "user_id", "date_local"),
)
candidate_history = Table(
    "candidate_history",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("candidate_id", Text, nullable=False),
    Column("user_id", Text, nullable=False),
    Column("from_state", Text, nullable=True),
    Column("to_state", Text, nullable=False),
    Column("reason", Text, nullable=True),
    Column("json", Text, nullable=True),
    Column("created_at", Text, nullable=False),
    Index("ix_candidate_history_cand", "candidate_id"),
)
book_quotes = Table(
    "book_quotes",
    metadata,
    Column("book_quote_id", Text, primary_key=True),
    Column("candidate_id", Text, nullable=False),
    Column("user_id", Text, nullable=False),
    Column("json", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)
reservations = Table(
    "reservations",
    metadata,
    Column("reservation_id", Text, primary_key=True),
    Column("user_id", Text, nullable=False),
    Column("date_local", Text, nullable=False),
    Column("candidate_id", Text, nullable=False),
    Column("stake_cents", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("expires_at", Text, nullable=False),
    Column("released_reason", Text, nullable=True),
    UniqueConstraint("user_id", "idempotency_key", name="uq_reservations_user_idem"),
    Index("ix_reservations_user_date", "user_id", "date_local"),
)
bets = Table(
    "bets",
    metadata,
    Column("bet_id", Text, primary_key=True),
    Column("user_id", Text, nullable=False),
    Column("date_local", Text, nullable=False),
    Column("candidate_id", Text, nullable=True),
    Column("reservation_id", Text, nullable=True),
    Column("stake_cents", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("payload_hash", Text, nullable=False),
    Column("external", Integer, nullable=False, default=0),
    Column("data_mode", Text, nullable=False, default="LIVE_PROVIDER"),
    Column("json", Text, nullable=False),
    Column("placed_at", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    UniqueConstraint("user_id", "idempotency_key", name="uq_bets_user_idem"),
    Index("ix_bets_user_date", "user_id", "date_local"),
)
settlements = Table(
    "settlements",
    metadata,
    Column("settlement_id", Text, primary_key=True),
    Column("bet_id", Text, nullable=False),
    Column("user_id", Text, nullable=False),
    Column("seq", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("cash_returned_cents", Integer, nullable=True),
    Column("bonus_returned_cents", Integer, nullable=True),
    Column("payload_hash", Text, nullable=False),
    Column("json", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    UniqueConstraint("bet_id", "seq", name="uq_settlements_bet_seq"),
    UniqueConstraint("bet_id", "payload_hash", name="uq_settlements_bet_payload"),
    Index("ix_settlements_user", "user_id"),
)
costs = Table(
    "costs",
    metadata,
    Column("cost_id", Text, primary_key=True),
    Column("user_id", Text, nullable=False),
    Column("date_local", Text, nullable=False),
    Column("category", Text, nullable=False),
    Column("amount_cents", Integer, nullable=False),
    Column("description", Text, nullable=False),
    Column("idempotency_key", Text, nullable=True),
    Column("created_at", Text, nullable=False),
    UniqueConstraint("user_id", "idempotency_key", name="uq_costs_user_idem"),
)
provider_usage = Table(
    "provider_usage",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Text, nullable=True),
    Column("provider", Text, nullable=False),
    Column("endpoint", Text, nullable=False),
    Column("credits_cost", Integer, nullable=True),
    Column("requests_remaining", Integer, nullable=True),
    Column("requests_used", Integer, nullable=True),
    Column("created_at", Text, nullable=False),
    Index("ix_provider_usage_created", "created_at"),
)
audit_log = Table(
    "audit_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("ref_id", Text, nullable=True),
    Column("json", Text, nullable=True),
    Column("created_at", Text, nullable=False),
    Index("ix_audit_user", "user_id"),
)

LEDGER_TABLES = (bets, settlements, reservations, costs)
USER_SCOPED_TABLES = (
    user_settings,
    user_days,
    candidates,
    candidate_history,
    book_quotes,
    reservations,
    bets,
    settlements,
    costs,
    audit_log,
    oauth_tokens,
    oauth_codes,
    credentials,
)

# --------------------------------------------------------------------------------------
# Scalar helpers
# --------------------------------------------------------------------------------------

_CENT = Decimal("0.01")


def cents(value: Decimal | int | str) -> int:
    d = Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)
    return int(d * 100)


def from_cents(value: int | None) -> Decimal | None:
    if value is None:
        return None
    return (Decimal(value) / Decimal(100)).quantize(_CENT)


def dec(value: str | None) -> Decimal | None:
    return None if value is None or value == "" else Decimal(value)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        raise ValueError("naive datetime")
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    if value is None or value == "":
        return None
    v = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def new_id(prefix: str) -> str:
    """Unguessable random id with a readable prefix (96 bits of entropy)."""
    return f"{prefix}_{secrets.token_urlsafe(12)}"


def dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))


def loads(s: str) -> Any:
    return json.loads(s)


class FixtureLedgerError(RuntimeError):
    """Raised when fixture-mode data would be written to a real ledger."""


# --------------------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------------------


class Database:
    def __init__(self, url: str, *, allow_fixture_ledger: bool = False) -> None:
        self.url = url
        self.allow_fixture_ledger = allow_fixture_ledger
        self.kind = (
            "postgresql" if url.startswith("postgres") else "sqlite" if url.startswith("sqlite") else "other"
        )
        if self.kind == "sqlite":
            _ensure_sqlite_parent(url)
            self.engine: Engine = create_engine(url, future=True)
            _install_sqlite_hooks(self.engine)
        else:
            self.engine = create_engine(url, future=True, pool_pre_ping=True)

    # ---- lifecycle ----
    def migrate(self) -> None:
        metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            applied = {row[0] for row in conn.execute(select(schema_migrations.c.version))}
            if SCHEMA_VERSION not in applied:
                conn.execute(
                    insert(schema_migrations).values(
                        version=SCHEMA_VERSION, applied_at=iso(datetime.now(UTC))
                    )
                )

    def ping(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def dispose(self) -> None:
        self.engine.dispose()

    @contextmanager
    def tx(self) -> Iterator[Connection]:
        """Short WRITE transaction: commit on success, rollback on error.

        On SQLite the transaction starts with BEGIN IMMEDIATE (writers serialise instead of deadlocking).
        Plain `engine.connect()` reads use a deferred BEGIN and never take the write lock.
        """
        conn = self.engine.connect().execution_options(hrnba_write=True)
        try:
            with conn.begin():
                yield conn
        finally:
            conn.close()

    # ---- locking ----
    def lock_user_day(self, conn: Connection, user_id: str, date_local: str, now: datetime) -> None:
        """Serialise budget mutations for one user-day.

        PostgreSQL: insert-if-missing then SELECT ... FOR UPDATE. SQLite: insert-if-missing only, because
        BEGIN IMMEDIATE already serialises all writers.
        """
        exists = conn.execute(
            select(user_days.c.user_id).where(
                user_days.c.user_id == user_id, user_days.c.date_local == date_local
            )
        ).first()
        if exists is None:
            if self.kind == "postgresql":
                conn.execute(
                    text(
                        "INSERT INTO user_days (user_id, date_local, created_at) VALUES (:u, :d, :c) "
                        "ON CONFLICT (user_id, date_local) DO NOTHING"
                    ),
                    {"u": user_id, "d": date_local, "c": iso(now)},
                )
            else:
                conn.execute(
                    insert(user_days).values(user_id=user_id, date_local=date_local, created_at=iso(now))
                )
        if self.kind == "postgresql":
            conn.execute(
                text("SELECT user_id FROM user_days WHERE user_id = :u AND date_local = :d FOR UPDATE"),
                {"u": user_id, "d": date_local},
            )

    # ---- guards ----
    def guard_ledger_mode(self, data_mode: str) -> None:
        if data_mode == "FIXTURE" and not self.allow_fixture_ledger:
            raise FixtureLedgerError("refusing to write FIXTURE data to a real ledger")

    # ---- export / delete (CLI and account page only; never an MCP tool) ----
    def export_user(self, user_id: str) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        with self.engine.connect() as conn:
            for table in USER_SCOPED_TABLES:
                if table.name in ("credentials", "oauth_tokens", "oauth_codes"):
                    continue
                rows = conn.execute(select(table).where(table.c.user_id == user_id)).mappings().all()
                out[table.name] = [dict(r) for r in rows]
        return out

    def import_user(
        self, user_id: str, bundle: dict[str, list[dict[str, Any]]], now: datetime
    ) -> dict[str, int]:
        """Import a previously exported bundle into `user_id` (e.g. day-one local SQLite records into the hosted DB).

        Rows keep their primary keys and idempotency keys so a second import is a no-op; `user_id` columns are
        rewritten to the target user; autoincrement ids are dropped. Credentials and OAuth rows are never imported.
        """
        counts: dict[str, int] = {}
        by_name = {t.name: t for t in USER_SCOPED_TABLES}
        with self.tx() as conn:
            if conn.execute(select(users.c.user_id).where(users.c.user_id == user_id)).first() is None:
                conn.execute(insert(users).values(user_id=user_id, created_at=iso(now)))
            for name, rows in bundle.items():
                table = by_name.get(name)
                if table is None or name in ("credentials", "oauth_tokens", "oauth_codes"):
                    continue
                inserted = 0
                for row in rows:
                    values = {k: v for k, v in row.items() if k in table.c and k != "id"}
                    if "user_id" in table.c:
                        values["user_id"] = user_id
                    if self.kind == "postgresql":
                        from sqlalchemy.dialects.postgresql import insert as pg_insert

                        pk = list(table.primary_key.columns)[0]
                        stmt = pg_insert(table).values(**values).on_conflict_do_nothing().returning(pk)
                        inserted += len(conn.execute(stmt).fetchall())
                    else:
                        stmt = insert(table).values(**values).prefix_with("OR IGNORE")
                        inserted += max(conn.execute(stmt).rowcount or 0, 0)
                counts[name] = inserted
        return counts

    def delete_user(self, user_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self.tx() as conn:
            for table in USER_SCOPED_TABLES:
                res = conn.execute(table.delete().where(table.c.user_id == user_id))
                counts[table.name] = res.rowcount or 0
            res = conn.execute(users.delete().where(users.c.user_id == user_id))
            counts["users"] = res.rowcount or 0
        return counts


def _ensure_sqlite_parent(url: str) -> None:
    """Create the folder that holds a file-backed SQLite database so a fresh install never fails on open."""
    from pathlib import Path

    path = url[len("sqlite:///") :] if url.startswith("sqlite:///") else ""
    if not path or path.startswith(":memory:") or path.startswith("file:"):
        return
    Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _install_sqlite_hooks(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:  # pragma: no cover - driver hook
        dbapi_connection.isolation_level = None  # let us control BEGIN
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn: Connection) -> None:  # pragma: no cover - driver hook
        if conn.get_execution_options().get("hrnba_write"):
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            conn.exec_driver_sql("BEGIN")


def open_database(url: str, *, allow_fixture_ledger: bool = False) -> Database:
    db = Database(url, allow_fixture_ledger=allow_fixture_ledger)
    db.migrate()
    return db
