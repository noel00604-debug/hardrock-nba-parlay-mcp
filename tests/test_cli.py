"""CLI smoke tests with typer's CliRunner and a FIXTURE services fake. No keychain, no network."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from hardrock_nba_parlay import cli, config
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.errors import NotFound

runner = CliRunner()


@dataclass
class RequestContext:
    user_id: str
    clock: Any
    db: Any
    settings: Any
    providers: Any = None


def _budget(date_local: str, recorded: Decimal = Decimal("0")) -> S.DailyBudget:
    return S.DailyBudget(
        date_local=date_local,
        cap_usd=Decimal("10"),
        recorded_stake_usd=recorded,
        reserved_stake_usd=Decimal("0"),
        remaining_usd=max(Decimal("0"), Decimal("10") - recorded),
        raw_remaining_usd=Decimal("10") - recorded,
    )


@pytest.fixture
def calls() -> list[tuple[str, Any]]:
    return []


@pytest.fixture(autouse=True)
def fake_runtime(monkeypatch, settings, db, clock, calls):
    def get_system_status(ctx: Any) -> S.SystemStatus:
        calls.append(("get_system_status", ctx.user_id))
        return S.SystemStatus(
            app_version="0.1.0",
            now_utc=ctx.clock.now_utc(),
            now_display="2026-10-20T15:00:00-04:00",
            display_tz="America/New_York",
            auth_mode="none",
            user_id_masked="loca***er",
            database_ok=True,
            database_kind="sqlite",
            provider_configured=False,
            data_modes_available=[S.DataMode.FIXTURE],
            target_book="hardrockbet_fl",
            jurisdiction="US-FL",
            daily_cap_usd=Decimal("10.00"),
            onboarding_complete=False,
        )

    def get_daily_budget(ctx: Any, date_local: str, proposed: Decimal | None) -> S.DailyBudget:
        calls.append(("get_daily_budget", (date_local, proposed)))
        budget = _budget(date_local)
        budget.proposed_stake_usd = proposed
        return budget

    def record_actual_bet(ctx: Any, ticket: S.ConfirmedTicketInput, idempotency_key: str) -> S.RecordResponse:
        calls.append(("record_actual_bet", (ticket, idempotency_key)))
        now = ctx.clock.now_utc()
        bet = S.ActualBet(
            bet_id="bet_cli1",
            user_id=ctx.user_id,
            date_local="2026-10-20",
            book=ticket.book,
            legs=ticket.legs,
            external=ticket.external,
            stake_usd=ticket.stake_usd,
            placed_at_utc=ticket.placed_at_utc or now,
            source=ticket.source,
            idempotency_key=idempotency_key,
            payload_hash="hash",
            created_at_utc=now,
        )
        return S.RecordResponse(bet=bet, budget=_budget("2026-10-20", ticket.stake_usd))

    def check_parlay_correlation(ctx: Any, candidate_id: str) -> S.CorrelationReport:
        raise NotFound("candidate not found", detail=candidate_id)

    fake = SimpleNamespace(
        RequestContext=RequestContext,
        get_system_status=get_system_status,
        get_daily_budget=get_daily_budget,
        record_actual_bet=record_actual_bet,
        check_parlay_correlation=check_parlay_correlation,
    )
    monkeypatch.setattr(cli, "_services", lambda: fake)
    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(cli, "_open_db", lambda _settings: db)
    monkeypatch.setattr(cli, "_clock", lambda: clock)
    return fake


def _legs() -> list[dict[str, Any]]:
    return [
        {
            "description": "DET +3.5",
            "market_type": "SPREAD",
            "side": "HOME",
            "line": "3.5",
            "accepted_decimal": "1.91",
        },
        {
            "description": "PHI/NYK over 224.5",
            "market_type": "TOTAL",
            "side": "OVER",
            "line": "224.5",
            "accepted_decimal": "1.91",
        },
        {"description": "OKC ML", "market_type": "MONEYLINE", "side": "AWAY", "accepted_decimal": "1.67"},
    ]


def test_status_json_and_summary(calls, settings):
    result = runner.invoke(cli.app, ["--json", "status"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["app_version"] == "0.1.0" and payload["daily_cap_usd"] == "10.00"
    assert calls[-1] == ("get_system_status", settings.local_user_id)
    plain = runner.invoke(cli.app, ["status"])
    assert plain.exit_code == 0
    assert "app_version: 0.1.0" in plain.stdout and "target_book: hardrockbet_fl" in plain.stdout


def test_budget_defaults_to_today_et_and_accepts_proposed(calls):
    result = runner.invoke(cli.app, ["--json", "budget", "--proposed", "7.50"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["proposed_stake_usd"] == "7.50"
    assert calls[-1] == ("get_daily_budget", ("2026-10-20", Decimal("7.50")))
    dated = runner.invoke(cli.app, ["budget", "--date", "2026-11-01"])
    assert dated.exit_code == 0 and "date_local: 2026-11-01" in dated.stdout


def test_record_bet_from_json_file(tmp_path, calls):
    ticket = {
        "candidate_id": "cand_1",
        "ticket_ref": "HR-77",
        "legs": _legs(),
        "accepted_combined_decimal": "6.10",
        "stake_usd": "10",
        "placed_at_utc": "2026-10-20T18:30:00Z",
        "source": "USER_CONFIRMATION",
    }
    path = tmp_path / "ticket.json"
    path.write_text(json.dumps(ticket))
    result = runner.invoke(cli.app, ["--json", "record-bet", "--json", str(path), "--key", "cli-key-1"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["bet"]["idempotency_key"] == "cli-key-1" and payload["bet"]["stake_usd"] == "10.00"
    name, (parsed, key) = calls[-1]
    assert name == "record_actual_bet" and key == "cli-key-1" and parsed.ticket_ref == "HR-77"

    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"legs": _legs()}))  # stake_usd missing
    bad = runner.invoke(cli.app, ["--json", "record-bet", "--json", str(broken), "--key", "k2"])
    assert bad.exit_code == 1
    assert "INVALID_INPUT" in bad.output and "Traceback" not in bad.output


def test_service_error_prints_reason_codes_and_exits_nonzero():
    result = runner.invoke(cli.app, ["correlation", "cand_missing"])
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output and "candidate not found" in result.output
    as_json = runner.invoke(cli.app, ["--json", "correlation", "cand_missing"])
    assert as_json.exit_code == 1
    assert json.loads(as_json.output.strip().splitlines()[-1])["reason_codes"] == ["NOT_FOUND"]


def test_secret_check_never_touches_keychain_or_prints_value(monkeypatch):
    looked_up: list[str] = []

    def fake_get_secret(name: str) -> str | None:
        looked_up.append(name)
        return "super-secret-value-123456" if name == "ODDS_API_KEY" else None

    monkeypatch.setattr(config, "get_secret", fake_get_secret)
    monkeypatch.setattr(config, "_keychain_lookup", lambda name: pytest.fail("keychain must not be touched"))
    found = runner.invoke(cli.app, ["--json", "secret", "check", "odds_api_key"])
    assert found.exit_code == 0, found.output
    assert json.loads(found.stdout) == {"name": "ODDS_API_KEY", "resolves": True}
    assert "super-secret-value" not in found.output
    missing = runner.invoke(cli.app, ["secret", "check", "NOPE"])
    assert missing.exit_code == 0 and "resolves: False" in missing.stdout
    assert looked_up == ["ODDS_API_KEY", "NOPE"]


def test_secret_set_writes_dotenv_with_0600_off_darwin(monkeypatch, settings):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    monkeypatch.setattr(cli, "_getpass", lambda prompt: "dotenv-secret-value")
    result = runner.invoke(cli.app, ["--json", "secret", "set", "odds_api_key"])
    assert result.exit_code == 0, result.output
    env_path = settings.data_dir / ".env"
    assert env_path.read_text() == "HRNBA_ODDS_API_KEY=dotenv-secret-value\n"
    assert oct(env_path.stat().st_mode & 0o777) == "0o600"
    assert "dotenv-secret-value" not in result.output


def test_db_backup_and_restore_sqlite(tmp_path, settings, db):
    backup = tmp_path / "backup" / "copy.db"
    result = runner.invoke(cli.app, ["--json", "db", "backup", str(backup)])
    assert result.exit_code == 0, result.output
    assert backup.is_file() and json.loads(result.stdout)["database"] == "sqlite"
    restored = runner.invoke(cli.app, ["--json", "db", "restore", str(backup)])
    assert restored.exit_code == 0, restored.output
    migrate = runner.invoke(cli.app, ["db", "migrate"])
    assert migrate.exit_code == 0 and "migrated: True" in migrate.stdout


def test_user_create_export_delete(tmp_path, monkeypatch, db):
    monkeypatch.setattr(cli, "_getpass", lambda prompt: "correct horse battery")
    created = runner.invoke(cli.app, ["--json", "user", "create", "Admin@Example.com"])
    assert created.exit_code == 0, created.output
    user_id = json.loads(created.stdout)["user_id"]
    assert "correct horse" not in created.output
    out = tmp_path / "export.json"
    exported = runner.invoke(cli.app, ["--json", "user", "export", user_id, "--out", str(out)])
    assert exported.exit_code == 0, exported.output
    assert json.loads(out.read_text())["tables"]["user_settings"][0]["user_id"] == user_id
    refused = runner.invoke(cli.app, ["user", "delete", user_id])
    assert refused.exit_code == 1
    deleted = runner.invoke(cli.app, ["--json", "user", "delete", user_id, "--confirm"])
    assert deleted.exit_code == 0 and json.loads(deleted.stdout)["deleted"]["user_settings"] == 1


def test_dashboard_writes_html_without_opening(tmp_path, monkeypatch, fake_runtime):
    def generate_30_day_review(ctx: Any) -> dict[str, Any]:
        return {
            "window_start": "2026-10-20",
            "window_end": "2026-11-18",
            "observed_results": ["no bets <yet>"],
        }

    fake_runtime.generate_30_day_review = generate_30_day_review
    monkeypatch.setattr(
        cli.dashboard, "open_in_browser", lambda path: pytest.fail("browser must not open in tests")
    )
    out = tmp_path / "dash.html"
    result = runner.invoke(cli.app, ["--json", "dashboard", "--out", str(out)])
    assert result.exit_code == 0, result.output
    html = out.read_text()
    assert "<!DOCTYPE html>" in html and "&lt;yet&gt;" in html and "<yet>" not in html
    assert "AI-assisted" in html


def test_help_lists_every_command():
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for name in (
        "status",
        "coverage",
        "slate",
        "build",
        "analyze-leg",
        "correlation",
        "import-quote",
        "refresh",
        "select",
        "release",
        "budget",
        "record-bet",
        "settle",
        "performance",
        "review-30",
        "dashboard",
        "import-selections",
        "serve",
        "db",
        "user",
        "secret",
    ):
        assert name in result.stdout, name


# ---- secrets never reach the terminal; reason codes survive; serve refuses an open authless bind ----


def test_secret_set_keychain_failure_never_prints_the_value(monkeypatch):
    import subprocess

    monkeypatch.setattr(cli.sys, "platform", "darwin")
    secret_value = "kc-secret-value-ABC123"
    monkeypatch.setattr(cli, "_getpass", lambda prompt: secret_value)
    seen_cmds: list[list[str]] = []

    def failing(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen_cmds.append(cmd)
        assert kwargs.get("check") is False
        return subprocess.CompletedProcess(
            cmd, 1, stdout=b"", stderr=f"keychain locked for {secret_value}".encode()
        )

    monkeypatch.setattr(cli.subprocess, "run", failing)
    result = runner.invoke(cli.app, ["secret", "set", "odds_api_key"])
    assert result.exit_code == 1
    assert secret_value not in result.output, result.output
    assert "PROVIDER_ERROR" in result.output and "status 1" in result.output and "[REDACTED]" in result.output
    assert seen_cmds and seen_cmds[0][-1] == secret_value  # the value went to `security`, not to the terminal

    def raising(cmd: list[str], **kwargs: Any) -> None:
        raise subprocess.CalledProcessError(2, cmd, output=b"", stderr=b"denied")

    monkeypatch.setattr(cli.subprocess, "run", raising)
    raised = runner.invoke(cli.app, ["--json", "secret", "set", "odds_api_key"])
    assert (
        raised.exit_code == 1 and secret_value not in raised.output and "CalledProcessError" in raised.output
    )

    def timing_out(cmd: list[str], **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(cmd, 15)

    monkeypatch.setattr(cli.subprocess, "run", timing_out)
    slow = runner.invoke(cli.app, ["secret", "set", "odds_api_key"])
    assert slow.exit_code == 1 and secret_value not in slow.output and "15 seconds" in slow.output

    def ok(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(cli.subprocess, "run", ok)
    stored = runner.invoke(cli.app, ["--json", "secret", "set", "odds_api_key"])
    assert stored.exit_code == 0, stored.output
    assert json.loads(stored.stdout)["stored_in"] == "macos-keychain" and secret_value not in stored.output


def test_service_error_output_is_redacted(fake_runtime):
    from hardrock_nba_parlay.errors import ProviderError

    def get_system_status(ctx: Any) -> S.SystemStatus:
        raise ProviderError(
            "provider rejected Bearer SECRET123VALUE",
            ["PROVIDER_AUTH_FAILED"],
            detail="GET https://api.the-odds-api.com/v4/sports?apiKey=SECRET123VALUE -> 401",
        )

    fake_runtime.get_system_status = get_system_status
    for args in (["status"], ["--json", "status"]):
        result = runner.invoke(cli.app, args)
        assert result.exit_code == 1
        assert "PROVIDER_AUTH_FAILED" in result.output and "SECRET123VALUE" not in result.output
        assert "[REDACTED]" in result.output


def test_validation_errors_keep_schema_reason_codes(capsys):
    import typer

    with pytest.raises(typer.Exit):
        cli._run(cli.Runtime(json_output=True), lambda: S.ThreeLegTicket(legs=[]))
    payload = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert payload["reason_codes"] == ["NOT_THREE_LEGS", "INVALID_INPUT"]
    assert "exactly three selections" in payload["detail"]


def test_subprocess_errors_in_the_catch_all_report_only_the_class(capsys):
    import subprocess

    import typer

    def body() -> None:
        raise subprocess.CalledProcessError(1, ["security", "-w", "argv-secret-XYZ"])

    with pytest.raises(typer.Exit):
        cli._run(cli.Runtime(json_output=False), body)
    err = capsys.readouterr().err
    assert "argv-secret-XYZ" not in err and "CalledProcessError" in err and "PROVIDER_ERROR" in err


def test_record_bet_requires_three_legs_unless_external(tmp_path, calls):
    short = {"legs": _legs()[:2], "stake_usd": "5", "source": "USER_CONFIRMATION"}
    path = tmp_path / "short.json"
    path.write_text(json.dumps(short))
    result = runner.invoke(cli.app, ["record-bet", "--json", str(path), "--key", "k-short"])
    assert result.exit_code == 1 and "NOT_THREE_LEGS" in result.output
    assert [name for name, _ in calls if name == "record_actual_bet"] == []
    path.write_text(json.dumps({**short, "external": True}))
    ok = runner.invoke(cli.app, ["--json", "record-bet", "--json", str(path), "--key", "k-ext"])
    assert ok.exit_code == 0, ok.output
    assert json.loads(ok.stdout)["bet"]["external"] is True


def test_serve_http_refuses_non_loopback_host_without_oauth(monkeypatch):
    import uvicorn

    started: list[dict[str, Any]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: started.append(kw))
    refused = runner.invoke(cli.app, ["serve", "--transport", "http", "--host", "0.0.0.0"])
    assert refused.exit_code == 1, refused.output
    assert "FORBIDDEN" in refused.output and "0.0.0.0" in refused.output and started == []
    as_json = runner.invoke(cli.app, ["--json", "serve", "--transport", "http", "--host", "::"])
    assert as_json.exit_code == 1 and json.loads(as_json.output.strip().splitlines()[-1])["reason_codes"] == [
        "FORBIDDEN"
    ]
    local = runner.invoke(
        cli.app, ["--json", "serve", "--transport", "http", "--host", "127.0.0.1", "--port", "8765"]
    )
    assert local.exit_code == 0, local.output
    assert started[-1]["host"] == "127.0.0.1" and started[-1]["port"] == 8765
