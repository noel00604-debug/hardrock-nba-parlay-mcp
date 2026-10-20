"""``hrnba`` command-line interface (local mode: identity is ``settings.local_user_id``).

Every command prints JSON (``hrnba --json <command>``) or a readable summary. Errors print the reason codes
and exit non-zero. ``services`` is imported lazily by ``_services`` so this module imports before
``services.py`` exists; tests monkeypatch that helper.
"""

from __future__ import annotations

import csv
import getpass
import importlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit, urlunsplit

import typer
from pydantic import ValidationError

from . import auth, config, dashboard
from . import schemas as S
from .config import KEYCHAIN_SERVICE, Clock, Settings, SystemClock
from .db import Database, open_database
from .errors import InvalidInput, ServiceError
from .mcp_server import make_request_context, tool_error_from_validation

ERROR_TEXT_MAX = 500

app = typer.Typer(
    name="hrnba",
    help="Research exactly-three-leg NBA parlays on Hard Rock Bet Florida. The user places every wager; this tool never does.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    pretty_exceptions_enable=False,
)
db_app = typer.Typer(help="Database maintenance (migrate, backup, restore).", no_args_is_help=True)
user_app = typer.Typer(help="Hosted-mode user administration.", no_args_is_help=True)
secret_app = typer.Typer(
    help="Secrets in the macOS keychain (or data_dir/.env elsewhere).", no_args_is_help=True
)
app.add_typer(db_app, name="db")
app.add_typer(user_app, name="user")
app.add_typer(secret_app, name="secret")


# --------------------------------------------------------------------------------------
# Runtime plumbing (monkeypatched in tests)
# --------------------------------------------------------------------------------------


def _services() -> Any:
    """Import the services module on first use."""
    return importlib.import_module("hardrock_nba_parlay.services")


def _load_settings() -> Settings:
    return Settings()


def _open_db(settings: Settings) -> Database:
    return open_database(settings.effective_database_url, allow_fixture_ledger=settings.allow_fixture_ledger)


def _clock() -> Clock:
    return SystemClock()


def _getpass(prompt: str) -> str:
    return getpass.getpass(prompt)


@dataclass
class Runtime:
    json_output: bool = False
    _settings: Settings | None = field(default=None, repr=False)
    _db: Database | None = field(default=None, repr=False)
    _clock: Clock | None = field(default=None, repr=False)

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = _load_settings()
        return self._settings

    @property
    def db(self) -> Database:
        if self._db is None:
            self._db = _open_db(self.settings)
        return self._db

    @property
    def clock(self) -> Clock:
        if self._clock is None:
            self._clock = _clock()
        return self._clock

    def today(self) -> str:
        return config.local_date(self.clock.now_utc())


def _rt(ctx: typer.Context) -> Runtime:
    obj = ctx.find_object(Runtime)
    if obj is None:
        obj = Runtime()
        ctx.obj = obj
    return obj


@app.callback()
def main(
    ctx: typer.Context,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print JSON instead of a readable summary.")
    ] = False,
) -> None:
    """hrnba: NBA three-leg parlay research and a user-confirmed wager ledger."""
    ctx.obj = Runtime(json_output=json_output)


# --------------------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------------------


def _plain(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, Decimal):
        return str(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def _summary_lines(data: Any, indent: int = 0) -> list[str]:
    pad = "  " * indent
    lines: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)) and value:
                lines.append(f"{pad}{key}:")
                lines.extend(_summary_lines(value, indent + 1))
            else:
                shown = "(none)" if value in (None, [], {}) else value
                lines.append(f"{pad}{key}: {shown}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.extend(_summary_lines(item, indent + 1))
            else:
                lines.append(f"{pad}- {item}")
    else:
        lines.append(f"{pad}{data}")
    return lines


def _emit(rt: Runtime, obj: Any) -> None:
    data = _plain(obj)
    if rt.json_output:
        typer.echo(json.dumps(data, indent=2, default=str))
    else:
        typer.echo("\n".join(_summary_lines(data)))


def _safe_text(value: Any, limit: int = ERROR_TEXT_MAX) -> Any:
    """Redact a message that may carry a key and cap its length; non-strings pass through."""
    if not isinstance(value, str):
        return value
    cleaned = config.redact(value)
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 3] + "..."


def _fail(rt: Runtime, payload: dict[str, Any], code: int = 1) -> None:
    """Print an error payload (``error``, ``reason_codes``, ``detail``) redacted, then exit non-zero."""
    safe = dict(payload)
    safe["error"] = _safe_text(safe.get("error"))
    safe["detail"] = _safe_text(safe.get("detail"))
    if rt.json_output:
        typer.echo(json.dumps(safe, default=str), err=True)
    else:
        codes = ", ".join(safe.get("reason_codes") or []) or "-"
        detail = safe.get("detail")
        typer.echo(f"error: {safe.get('error')} [{codes}]" + (f": {detail}" if detail else ""), err=True)
    raise typer.Exit(code=code)


def _run(rt: Runtime, fn: Callable[[], Any]) -> None:
    """Run a command body: print the result, or print reason codes and exit non-zero.

    ``ServiceError`` keeps its reason codes; pydantic errors surface the reason codes embedded in validator
    messages (``NOT_THREE_LEGS``, ...); anything else is an internal error. Subprocess errors are reported by
    class name only, because their messages repeat the whole argv.
    """
    try:
        result = fn()
    except typer.Exit:
        raise
    except ServiceError as exc:
        _fail(rt, exc.to_dict(), 1)
    except ValidationError as exc:
        _fail(rt, tool_error_from_validation(exc).model_dump(), 1)
    except (OSError, ValueError, InvalidOperation) as exc:
        _fail(
            rt,
            {"error": "invalid input", "reason_codes": ["INVALID_INPUT"], "detail": config.redact(str(exc))},
            1,
        )
    except Exception as exc:  # noqa: BLE001 - CLI must never print a raw traceback with secrets
        if isinstance(exc, subprocess.SubprocessError):
            detail = type(exc).__name__
        else:
            detail = config.redact(f"{type(exc).__name__}: {exc}")
        _fail(rt, {"error": "internal error", "reason_codes": ["PROVIDER_ERROR"], "detail": detail}, 2)
    else:
        _emit(rt, result)


def _svc_call(rt: Runtime, name: str, *args: Any, **kwargs: Any) -> Any:
    svc = _services()
    user_id = auth.current_user_id(rt.settings)
    auth.ensure_user(rt.db, user_id, rt.clock.now_utc(), rt.settings)
    ctx = make_request_context(svc, user_id=user_id, clock=rt.clock, db=rt.db, settings=rt.settings)
    return getattr(svc, name)(ctx, *args, **kwargs)


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InvalidInput(f"{path} is not valid JSON", detail=str(exc)) from exc


def _money(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise InvalidInput(f"not a money amount: {value}") from exc


# --------------------------------------------------------------------------------------
# Research commands
# --------------------------------------------------------------------------------------


@app.command()
def status(ctx: typer.Context) -> None:
    """System status: version, clock, database, provider, daily cap."""
    rt = _rt(ctx)
    _run(rt, lambda: _svc_call(rt, "get_system_status"))


@app.command()
def coverage(
    ctx: typer.Context,
    date: Annotated[
        str | None, typer.Option("--date", help="YYYY-MM-DD in America/New_York (default today).")
    ] = None,
    probe_props: Annotated[
        bool, typer.Option("--probe-props", help="Spend provider credits probing player-prop markets.")
    ] = False,
) -> None:
    """What the data sources cover for the day."""
    rt = _rt(ctx)
    _run(rt, lambda: _svc_call(rt, "check_data_coverage", date or rt.today(), probe_props=probe_props))


@app.command()
def slate(ctx: typer.Context, date: Annotated[str | None, typer.Option("--date")] = None) -> None:
    """NBA games for the day."""
    rt = _rt(ctx)
    _run(rt, lambda: _svc_call(rt, "get_nba_slate", date or rt.today()))


@app.command()
def build(
    ctx: typer.Context,
    date: Annotated[str | None, typer.Option("--date")] = None,
    parlay_type: Annotated[
        str, typer.Option("--type", help="auto | multi_game | same_game | mixed")
    ] = "auto",
    max_candidates: Annotated[int, typer.Option("--max", min=1, max=10)] = 3,
    include_props: Annotated[bool, typer.Option("--props/--no-props", help="Include player props.")] = True,
) -> None:
    """Research candidate three-leg tickets for the day."""
    rt = _rt(ctx)
    if parlay_type not in ("auto", "multi_game", "same_game", "mixed"):
        _fail(rt, {"error": "invalid --type", "reason_codes": ["INVALID_INPUT"], "detail": parlay_type})
    _run(
        rt,
        lambda: _svc_call(
            rt,
            "build_three_leg_parlays",
            date or rt.today(),
            parlay_type=parlay_type,
            max_candidates=max_candidates,
            include_props=include_props,
        ),
    )


@app.command("analyze-leg")
def analyze_leg(
    ctx: typer.Context, selection_id: str, date: Annotated[str | None, typer.Option("--date")] = None
) -> None:
    """Analyze one selection."""
    rt = _rt(ctx)
    _run(rt, lambda: _svc_call(rt, "analyze_leg", selection_id, date))


@app.command()
def correlation(ctx: typer.Context, candidate_id: str) -> None:
    """Correlation report for a candidate."""
    rt = _rt(ctx)
    _run(rt, lambda: _svc_call(rt, "check_parlay_correlation", candidate_id))


@app.command("import-quote")
def import_quote(
    ctx: typer.Context,
    candidate_id: str,
    json_file: Annotated[Path, typer.Option("--json", help="ManualQuoteInput JSON file.")],
) -> None:
    """Attach the combined odds shown by Hard Rock Bet to a candidate."""
    rt = _rt(ctx)

    def body() -> Any:
        quote = S.ManualQuoteInput.model_validate(_read_json_file(json_file))
        return _svc_call(rt, "import_hardrock_quote", candidate_id, quote)

    _run(rt, body)


@app.command()
def refresh(ctx: typer.Context, candidate_id: str) -> None:
    """Re-validate a candidate against fresh data."""
    rt = _rt(ctx)
    _run(rt, lambda: _svc_call(rt, "refresh_parlay", candidate_id))


@app.command()
def select(
    ctx: typer.Context,
    candidate_id: str,
    stake: Annotated[str, typer.Option("--stake", help="Stake in USD.")] = "10",
    key: Annotated[str | None, typer.Option("--key", help="Idempotency key.")] = None,
) -> None:
    """Reserve budget for a candidate you intend to place yourself."""
    rt = _rt(ctx)
    _run(rt, lambda: _svc_call(rt, "select_ticket", candidate_id, _money(stake), key))


@app.command()
def release(
    ctx: typer.Context, reservation_id: str, reason: Annotated[str, typer.Option("--reason")]
) -> None:
    """Release an active reservation."""
    rt = _rt(ctx)
    _run(rt, lambda: _svc_call(rt, "release_reservation", reservation_id, reason))


@app.command()
def budget(
    ctx: typer.Context,
    date: Annotated[str | None, typer.Option("--date")] = None,
    proposed: Annotated[str | None, typer.Option("--proposed", help="Proposed stake in USD.")] = None,
) -> None:
    """Daily budget ledger for a date."""
    rt = _rt(ctx)
    _run(
        rt,
        lambda: _svc_call(rt, "get_daily_budget", date or rt.today(), _money(proposed) if proposed else None),
    )


@app.command("record-bet")
def record_bet(
    ctx: typer.Context,
    json_file: Annotated[Path, typer.Option("--json", help="ConfirmedTicketInput JSON file.")],
    key: Annotated[str, typer.Option("--key", help="Idempotency key.")],
) -> None:
    """Record a wager you placed in the Hard Rock Bet app."""
    rt = _rt(ctx)

    def body() -> Any:
        ticket = S.ConfirmedTicketInput.model_validate(_read_json_file(json_file))
        if not ticket.legs:
            raise InvalidInput("a bet needs at least one leg")
        if not ticket.external and len(ticket.legs) != 3:
            raise InvalidInput(
                "a tool-prepared bet must have exactly three legs (set external=true for any other wager)",
                ["NOT_THREE_LEGS"],
                f"{len(ticket.legs)} legs in {json_file}",
            )
        return _svc_call(rt, "record_actual_bet", ticket, key)

    _run(rt, body)


@app.command()
def settle(
    ctx: typer.Context,
    bet_id: str,
    json_file: Annotated[Path, typer.Option("--json", help="SettlementInput JSON file.")],
) -> None:
    """Append a settlement record for a bet."""
    rt = _rt(ctx)

    def body() -> Any:
        settlement = S.SettlementInput.model_validate(_read_json_file(json_file))
        return _svc_call(rt, "reconcile_settlement", bet_id, settlement)

    _run(rt, body)


@app.command()
def performance(
    ctx: typer.Context,
    start: Annotated[str, typer.Option("--start")],
    end: Annotated[str, typer.Option("--end")],
) -> None:
    """Performance report for a date range."""
    rt = _rt(ctx)
    _run(rt, lambda: _svc_call(rt, "get_performance", start, end))


@app.command("review-30")
def review_30(ctx: typer.Context) -> None:
    """The 30-day review for the configured window."""
    rt = _rt(ctx)
    _run(rt, lambda: _svc_call(rt, "generate_30_day_review"))


@app.command("dashboard")
def dashboard_cmd(
    ctx: typer.Context,
    out: Annotated[
        Path | None, typer.Option("--out", help="Output HTML file (default data_dir/dashboard.html).")
    ] = None,
    open_browser: Annotated[
        bool, typer.Option("--open", help="Open the file in the default browser.")
    ] = False,
) -> None:
    """Write the local HTML dashboard."""
    rt = _rt(ctx)

    def body() -> Any:
        review = _svc_call(rt, "generate_30_day_review")
        today_budget = _svc_call(rt, "get_daily_budget", rt.today(), None)
        html_text: str | None = None
        try:
            reports = importlib.import_module("hardrock_nba_parlay.reports")
            html_text = reports.dashboard_html(review.performance, today_budget)
        except Exception:  # noqa: BLE001 - fall back to the generic renderer
            html_text = None
        if not html_text:
            html_text = dashboard.render_report_html("30-day review", review)
        target = out or (rt.settings.data_dir / "dashboard.html")
        path = dashboard.write_dashboard(html_text, target)
        if open_browser:
            dashboard.open_in_browser(path)
        return {"written": str(path), "opened": open_browser}

    _run(rt, body)


def _load_selection_inputs(path: Path) -> list[S.ManualSelectionInput]:
    """Load ManualSelectionInput rows from CSV or JSON (providers.manual when available, else built-in parsing)."""
    suffix = path.suffix.lower()
    try:
        manual = importlib.import_module("hardrock_nba_parlay.providers.manual")
    except ImportError:
        manual = None
    if manual is not None:
        loader = getattr(manual, "load_csv" if suffix == ".csv" else "load_json", None)
        if callable(loader):
            loaded = loader(path)
            return [
                item
                if isinstance(item, S.ManualSelectionInput)
                else S.ManualSelectionInput.model_validate(item)
                for item in loaded
            ]
    if suffix == ".csv":
        rows: list[dict[str, Any]] = []
        with path.open(newline="", encoding="utf-8") as fh:
            for raw in csv.DictReader(fh):
                row = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in raw.items() if k}
                rows.append({k: (None if v == "" else v) for k, v in row.items()})
    else:
        data = _read_json_file(path)
        rows = data if isinstance(data, list) else data.get("selections", [])
    return [S.ManualSelectionInput.model_validate(row) for row in rows]


@app.command("import-selections")
def import_selections(
    ctx: typer.Context, file: Path, date: Annotated[str | None, typer.Option("--date")] = None
) -> None:
    """Analyze three selections from a CSV or JSON file as a user ticket."""
    rt = _rt(ctx)

    def body() -> Any:
        inputs = _load_selection_inputs(file)
        if len(inputs) != 3:
            raise InvalidInput(
                "a ticket must contain exactly three selections",
                ["NOT_THREE_LEGS"],
                f"{len(inputs)} found in {file}",
            )
        return _svc_call(rt, "analyze_my_parlay", inputs, None, date or rt.today())

    _run(rt, body)


# --------------------------------------------------------------------------------------
# Serving
# --------------------------------------------------------------------------------------


@app.command()
def serve(
    ctx: typer.Context,
    transport: Annotated[str, typer.Option("--transport", help="stdio | http")] = "stdio",
    host: Annotated[str | None, typer.Option("--host")] = None,
    port: Annotated[int | None, typer.Option("--port")] = None,
) -> None:
    """Run the MCP server (stdio for local clients, http for the hosted app).

    With HTTP and auth_mode "none" the bind host must be loopback (127.0.0.1 / localhost); any other host
    needs auth_mode builtin_oauth and is refused with reason code FORBIDDEN.
    """
    rt = _rt(ctx)
    if transport == "stdio":
        from .mcp_server import run_stdio

        config.configure_logging(rt.settings.log_level)
        run_stdio(rt.settings, rt.db, rt.clock)
    elif transport == "http":
        from .web import run_http

        def body() -> Any:
            run_http(rt.settings, host=host, port=port)
            return {"transport": "http", "stopped": True}

        _run(rt, body)
    else:
        _fail(rt, {"error": "unknown transport", "reason_codes": ["INVALID_INPUT"], "detail": transport})


# --------------------------------------------------------------------------------------
# db
# --------------------------------------------------------------------------------------


def _sqlite_path(url: str) -> Path | None:
    if not url.startswith("sqlite:"):
        return None
    raw = url[len("sqlite:") :]
    raw = raw[3:] if raw.startswith("///") else raw
    return Path(raw)


def _masked_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.password:
        netloc = parts.netloc.replace(f":{parts.password}@", ":***@")
        return urlunsplit(parts._replace(netloc=netloc))
    return url


@db_app.command("migrate")
def db_migrate(ctx: typer.Context) -> None:
    """Create or upgrade the database schema (idempotent)."""
    rt = _rt(ctx)

    def body() -> Any:
        rt.db.migrate()
        return {"database": rt.settings.database_kind, "migrated": True}

    _run(rt, body)


@db_app.command("backup")
def db_backup(ctx: typer.Context, file: Path) -> None:
    """Copy the SQLite database to FILE after a WAL checkpoint (PostgreSQL: prints the pg_dump command)."""
    rt = _rt(ctx)

    def body() -> Any:
        url = rt.settings.effective_database_url
        src = _sqlite_path(url)
        if src is None:
            return {
                "database": rt.settings.database_kind,
                "command": f"pg_dump --format=custom --file {file} '{_masked_url(url)}'",
            }
        file.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(src) as source:
            source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            with sqlite3.connect(file) as dest:
                source.backup(dest)
        return {"database": "sqlite", "source": str(src), "backup": str(file.resolve())}

    _run(rt, body)


@db_app.command("restore")
def db_restore(ctx: typer.Context, file: Path) -> None:
    """Restore the SQLite database from FILE (PostgreSQL: prints the pg_restore command)."""
    rt = _rt(ctx)

    def body() -> Any:
        url = rt.settings.effective_database_url
        dest_path = _sqlite_path(url)
        if dest_path is None:
            return {
                "database": rt.settings.database_kind,
                "command": f"pg_restore --clean --if-exists --no-owner --dbname '{_masked_url(url)}' {file}",
            }
        if not file.is_file():
            raise InvalidInput(f"backup file not found: {file}")
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if dest_path.exists():
            with sqlite3.connect(dest_path) as current:
                current.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            shutil.copy2(dest_path, dest_path.with_suffix(dest_path.suffix + ".pre-restore"))
        with sqlite3.connect(file) as source, sqlite3.connect(dest_path) as dest:
            source.backup(dest)
        return {"database": "sqlite", "restored_from": str(file.resolve()), "target": str(dest_path)}

    _run(rt, body)


# --------------------------------------------------------------------------------------
# user (hosted)
# --------------------------------------------------------------------------------------


@user_app.command("create")
def user_create(ctx: typer.Context, email: str) -> None:
    """Create a hosted-mode user; the password is read without echo."""
    rt = _rt(ctx)

    def body() -> Any:
        password = _getpass("Password: ")
        again = _getpass("Repeat password: ")
        if password != again:
            raise InvalidInput("passwords do not match")
        user_id = auth.signup(rt.db, email, password, rt.clock.now_utc(), rt.settings)
        return {"user_id": user_id, "email": auth.normalize_email(email)}

    _run(rt, body)


@user_app.command("export")
def user_export(ctx: typer.Context, user_id: str, out: Annotated[Path, typer.Option("--out")]) -> None:
    """Export every record of a user to a JSON file."""
    rt = _rt(ctx)

    def body() -> Any:
        bundle = rt.db.export_user(user_id)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {"user_id_masked": config.mask_user_id(user_id), "tables": bundle}, indent=2, default=str
            ),
            encoding="utf-8",
        )
        return {
            "user_id_masked": config.mask_user_id(user_id),
            "file": str(out.resolve()),
            "rows": {k: len(v) for k, v in bundle.items()},
        }

    _run(rt, body)


@user_app.command("delete")
def user_delete(
    ctx: typer.Context,
    user_id: str,
    confirm: Annotated[bool, typer.Option("--confirm", help="Required.")] = False,
) -> None:
    """Delete every record of a user (requires --confirm)."""
    rt = _rt(ctx)
    if not confirm:
        _fail(
            rt,
            {
                "error": "refusing to delete without --confirm",
                "reason_codes": ["INVALID_INPUT"],
                "detail": None,
            },
        )

    def body() -> Any:
        counts = rt.db.delete_user(user_id)
        return {"user_id_masked": config.mask_user_id(user_id), "deleted": counts}

    _run(rt, body)


# --------------------------------------------------------------------------------------
# secret
# --------------------------------------------------------------------------------------


def _write_dotenv_secret(path: Path, name: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    key = f"HRNBA_{name}"
    lines: list[str] = []
    if path.is_file():
        lines = [
            ln
            for ln in path.read_text(encoding="utf-8").splitlines()
            if not ln.strip().startswith((f"{key}=", f"{name}="))
        ]
    lines.append(f"{key}={value}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)


def _scrub(text: bytes | str | None, value: str, limit: int = 300) -> str:
    """Error output with the secret value removed (then the usual redaction), capped for the terminal."""
    raw = text.decode("utf-8", errors="replace") if isinstance(text, bytes) else (text or "")
    cleaned = config.redact(raw.replace(value, "[REDACTED]"), extra_secrets=[value]).strip()
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 3] + "..."


def _keychain_store(key: str, value: str) -> None:
    """Store ``value`` with ``security add-generic-password``. Failures never repeat the value.

    ``subprocess`` errors embed the whole argv (including ``-w <value>``) in their message, so they are caught
    here and re-raised as a ``ServiceError`` that carries only the exit status and the scrubbed stderr.
    """
    cmd = ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", key, "-w", value]
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        raise ServiceError(
            "could not store the secret in the macOS keychain",
            ["PROVIDER_ERROR"],
            "the security command did not finish within 15 seconds",
        ) from None
    except subprocess.SubprocessError as exc:
        raise ServiceError(
            "could not store the secret in the macOS keychain",
            ["PROVIDER_ERROR"],
            f"{type(exc).__name__}: " + _scrub(getattr(exc, "stderr", None), value),
        ) from None
    except OSError as exc:
        raise ServiceError(
            "could not run the macOS security command", ["PROVIDER_ERROR"], _scrub(str(exc), value)
        ) from None
    if proc.returncode != 0:
        raise ServiceError(
            "could not store the secret in the macOS keychain",
            ["PROVIDER_ERROR"],
            f"security exited with status {proc.returncode}: " + (_scrub(proc.stderr, value) or "no output"),
        )


@secret_app.command("set")
def secret_set(ctx: typer.Context, name: str) -> None:
    """Store a secret (value read without echo) in the macOS keychain, or data_dir/.env (0600) elsewhere."""
    rt = _rt(ctx)

    def body() -> Any:
        key = name.strip().upper()
        if not key or not key.replace("_", "").isalnum():
            raise InvalidInput("secret NAME must be letters, digits, and underscores")
        value = _getpass(f"Value for {key}: ")
        if not value:
            raise InvalidInput("empty value")
        if sys.platform == "darwin":
            _keychain_store(key, value)
            return {"name": key, "stored_in": "macos-keychain", "service": KEYCHAIN_SERVICE}
        env_path = rt.settings.data_dir / ".env"
        _write_dotenv_secret(env_path, key, value)
        return {"name": key, "stored_in": str(env_path), "mode": "0600"}

    _run(rt, body)


@secret_app.command("check")
def secret_check(ctx: typer.Context, name: str) -> None:
    """Report whether a secret resolves (never prints the value)."""
    rt = _rt(ctx)

    def body() -> Any:
        key = name.strip().upper()
        return {"name": key, "resolves": config.get_secret(key) is not None}

    _run(rt, body)


if __name__ == "__main__":  # pragma: no cover
    app()
