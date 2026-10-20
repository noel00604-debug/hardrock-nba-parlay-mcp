"""MCP server: the twenty research/ledger tools (docs/ARCHITECTURE.md section 6).

Every tool resolves the caller with ``auth.current_user_id`` (never from arguments), builds a
``services.RequestContext`` and delegates to ``services.<tool>``. ``errors.ServiceError`` becomes a
``schemas.ToolError`` result; any other exception is logged (redacted) and also returned as a ``ToolError``.
No tool places bets, moves money, runs shell commands, or runs arbitrary SQL.

``services`` is imported lazily so this module (and its tests) work before ``services.py`` exists; tests
inject a fake namespace with the contract signatures.
"""

from __future__ import annotations

import importlib
import logging
import re
from collections.abc import Callable
from decimal import Decimal
from types import ModuleType
from typing import Annotated, Any, Literal

from mcp.server.auth.provider import OAuthAuthorizationServerProvider
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from . import auth, config
from . import schemas as S
from .config import Clock, Settings
from .db import Database
from .errors import ServiceError

logger = logging.getLogger(__name__)

SERVER_NAME = "NBA Three-Leg Parlay Analyst"

INSTRUCTIONS = (
    "Research assistant for exactly-three-leg NBA parlays on Hard Rock Bet (Florida). "
    "AI disclosure: analysis is produced with AI assistance; the user decides and places every wager manually "
    "in the Hard Rock Bet app; this tool never places bets, moves money, or guarantees outcomes; the default "
    "budget ledger is $10 per America/New_York day. "
    "Typical flow: get_system_status -> check_data_coverage -> get_nba_slate -> build_three_leg_parlays (or "
    "analyze_my_parlay for a pasted slip) -> import_hardrock_quote with the sportsbook's combined odds -> "
    "select_ticket to reserve budget -> the user places the bet themselves -> record_actual_bet -> "
    "reconcile_settlement -> get_performance / generate_30_day_review. Every response carries data_mode "
    "(LIVE_PROVIDER, MANUAL_INPUT, or FIXTURE) and reason codes; FIXTURE data is never a real market."
)

REQUIRES_USER_INTERACTION = {"anthropic/requiresUserInteraction": True}

TOOL_NAMES: tuple[str, ...] = (
    "get_system_status",
    "check_data_coverage",
    "get_nba_slate",
    "get_injury_context",
    "analyze_leg",
    "build_three_leg_parlays",
    "analyze_my_parlay",
    "check_parlay_correlation",
    "import_hardrock_quote",
    "refresh_parlay",
    "select_ticket",
    "release_reservation",
    "get_daily_budget",
    "record_actual_bet",
    "reconcile_settlement",
    "get_performance",
    "generate_30_day_review",
    "set_user_settings",
    "add_cost",
    "export_my_data",
)

ParlayTypeArg = Literal["auto", "multi_game", "same_game", "mixed"]
ThreeSelections = Annotated[
    list[S.ManualSelectionInput],
    Field(min_length=3, max_length=3, description="Exactly three distinct selections from the pasted slip"),
]

ERROR_TEXT_MAX = 500
DETAIL_TEXT_MAX = 1000
_REASON_CODE_TOKEN = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")
_VALUE_ERROR_PREFIX = "Value error, "


def _annotations(
    title: str, *, read_only: bool, destructive: bool, idempotent: bool, open_world: bool
) -> ToolAnnotations:
    """All four hints set explicitly (Claude's directory review checks readOnlyHint/destructiveHint)."""
    return ToolAnnotations(
        title=title,
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=open_world,
    )


def load_services() -> ModuleType:
    """Import ``hardrock_nba_parlay.services`` on first use (it is built by another module owner)."""
    return importlib.import_module("hardrock_nba_parlay.services")


def make_request_context(svc: Any, *, user_id: str, clock: Clock, db: Database, settings: Settings) -> Any:
    """Build ``services.RequestContext(user_id, clock, db, settings, providers)``.

    ``providers`` comes from ``services.build_providers(ctx)`` when the module offers it, else ``None``.
    """
    factory = svc.RequestContext

    def build(providers: Any) -> Any:
        try:
            return factory(user_id=user_id, clock=clock, db=db, settings=settings, providers=providers)
        except TypeError:
            return factory(user_id, clock, db, settings, providers)

    ctx = build(None)
    build_providers = getattr(svc, "build_providers", None)
    if callable(build_providers):
        providers = build_providers(ctx)
        if providers is not None:
            try:
                ctx.providers = providers
            except (AttributeError, TypeError, ValueError):
                ctx = build(providers)
    return ctx


def _safe_text(text: str | None, limit: int) -> str | None:
    """Redact anything that may carry a key and cap the length; None stays None."""
    if text is None:
        return None
    cleaned = config.redact(str(text))
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 3] + "..."


def reason_codes_from_validation(exc: ValidationError) -> list[str]:
    """Section-7 reason codes that ``schemas.py`` validators prefix their messages with, in order of appearance.

    ``INVALID_INPUT`` is always last, so a caller can act on the specific code (``NOT_THREE_LEGS``,
    ``QUOTE_SIGN_AMBIGUOUS``, ...) and still see the category.
    """
    codes: list[str] = []
    for err in exc.errors():
        for token in _REASON_CODE_TOKEN.findall(str(err.get("msg", ""))):
            if token in S.REASON_CODES and token != "INVALID_INPUT" and token not in codes:
                codes.append(token)
    codes.append("INVALID_INPUT")
    return codes


def tool_error_from_validation(exc: ValidationError) -> S.ToolError:
    """``ToolError`` for a pydantic ``ValidationError``: field paths plus the (redacted) validator messages."""
    parts: list[str] = []
    for err in exc.errors():
        path = ".".join(str(p) for p in err.get("loc", ())) or "input"
        msg = str(err.get("msg", "")).removeprefix(_VALUE_ERROR_PREFIX)
        entry = f"{path}: {msg}" if msg else path
        if entry not in parts:
            parts.append(entry)
    return S.ToolError(
        error="invalid input",
        reason_codes=reason_codes_from_validation(exc),
        detail=_safe_text("; ".join(parts) or "fields: unknown", DETAIL_TEXT_MAX),
    )


def _tool_error_from_exception(exc: BaseException) -> S.ToolError:
    """Convert any failure into a ``ToolError`` that never carries a secret or a traceback.

    ``ServiceError`` keeps its reason codes with message and detail redacted; ``ValidationError`` and
    ``ValueError`` are the caller's input (``INVALID_INPUT``); everything else, including ``TypeError`` from a
    services signature mismatch, is an internal error reported by class name only.
    """
    if isinstance(exc, ServiceError):
        return S.ToolError(
            error=_safe_text(exc.message, ERROR_TEXT_MAX) or "error",
            reason_codes=list(exc.reason_codes) or ["PROVIDER_ERROR"],
            detail=_safe_text(exc.detail, DETAIL_TEXT_MAX),
        )
    if isinstance(exc, ValidationError):
        return tool_error_from_validation(exc)
    if isinstance(exc, ValueError):
        return S.ToolError(
            error="invalid input", reason_codes=["INVALID_INPUT"], detail=_safe_text(str(exc), ERROR_TEXT_MAX)
        )
    return S.ToolError(error="internal error", reason_codes=["PROVIDER_ERROR"], detail=type(exc).__name__)


def three_leg_error(count: int, what: str = "a ticket") -> S.ToolError:
    """The ``NOT_THREE_LEGS`` rejection for a slip or tool-prepared bet that is not exactly three legs."""
    return S.ToolError(
        error=f"{what} must contain exactly three selections",
        reason_codes=["NOT_THREE_LEGS"],
        detail=f"{count} selections given",
    )


def build_server(
    settings: Settings,
    db: Database,
    clock: Clock,
    services: Any | None = None,
    *,
    auth_provider: OAuthAuthorizationServerProvider[Any, Any, Any] | None = None,
) -> MCPServer:
    """Create the MCPServer with every tool registered.

    ``services`` is any object exposing the contract functions and ``RequestContext`` (the real module when
    None). In hosted mode (``auth_mode == "builtin_oauth"``) the server carries the OAuth authorization
    server provider and AuthSettings so ``streamable_http_app`` wires bearer auth and the OAuth routes.
    """
    kwargs: dict[str, Any] = {}
    if settings.auth_mode == "builtin_oauth":
        provider = auth_provider or auth.DbOAuthProvider(db, settings, clock)
        kwargs["auth_server_provider"] = provider
        kwargs["auth"] = auth.build_auth_settings(settings)
    elif settings.auth_mode == "external_jwt":
        raise NotImplementedError("auth_mode external_jwt is not implemented; use builtin_oauth or none")

    server = MCPServer(
        name=SERVER_NAME,
        title=SERVER_NAME,
        description="Research tool for exactly-three-leg NBA parlays on Hard Rock Bet Florida; the user places every wager.",
        instructions=INSTRUCTIONS,
        version=settings.version,
        **kwargs,
    )
    server.hrnba_services = services  # type: ignore[attr-defined]

    def svc_module() -> Any:
        return services if services is not None else load_services()

    def today() -> str:
        return config.local_date(clock.now_utc())

    def call(name: str, *args: Any, **kw: Any) -> Any:
        """Resolve identity, build the request context, call the service; convert failures to ToolError."""
        try:
            user_id = auth.current_user_id(settings)
            auth.ensure_user(db, user_id, clock.now_utc(), settings)
            svc = svc_module()
            ctx = make_request_context(svc, user_id=user_id, clock=clock, db=db, settings=settings)
            fn: Callable[..., Any] = getattr(svc, name)
            return fn(ctx, *args, **kw)
        except ServiceError as exc:
            logger.info("tool %s rejected: %s %s", name, exc.reason_codes, config.redact(exc.message))
            return _tool_error_from_exception(exc)
        except ValidationError as exc:
            logger.info("tool %s invalid input: %s", name, config.redact(str(exc))[:300])
            return _tool_error_from_exception(exc)
        except Exception as exc:  # noqa: BLE001 - every failure must become a ToolError, never a traceback
            logger.error("tool %s failed: %s: %s", name, type(exc).__name__, config.redact(str(exc))[:300])
            return _tool_error_from_exception(exc)

    # ---- read-only status and data tools ----

    @server.tool(
        name="get_system_status",
        title="System status",
        annotations=_annotations(
            "System status", read_only=True, destructive=False, idempotent=True, open_world=False
        ),
    )
    def get_system_status() -> S.SystemStatus | S.ToolError:
        """Version, clock, auth mode, database and provider status, daily cap, and the AI disclosure."""
        return call("get_system_status")

    @server.tool(
        name="check_data_coverage",
        title="Check data coverage",
        annotations=_annotations(
            "Check data coverage", read_only=True, destructive=False, idempotent=True, open_world=True
        ),
    )
    def check_data_coverage(
        date_local: S.LocalDate | None = None, probe_props: bool = False
    ) -> S.CoverageReport | S.ToolError:
        """What this tool can and cannot see for the day: Hard Rock single-leg markets, reference books, injuries, quota. probe_props spends provider credits."""
        return call("check_data_coverage", date_local or today(), probe_props=probe_props)

    @server.tool(
        name="get_nba_slate",
        title="NBA slate",
        annotations=_annotations(
            "NBA slate", read_only=True, destructive=False, idempotent=True, open_world=True
        ),
    )
    def get_nba_slate(date_local: S.LocalDate | None = None) -> S.SlateResponse | S.ToolError:
        """NBA games for an America/New_York date with tip-off times, status, and data_mode."""
        return call("get_nba_slate", date_local or today())

    @server.tool(
        name="get_injury_context",
        title="Injury context",
        annotations=_annotations(
            "Injury context", read_only=True, destructive=False, idempotent=True, open_world=True
        ),
    )
    def get_injury_context(event_id: str) -> S.InjuryResponse | S.ToolError:
        """Official NBA injury-report entries for one event, with report timestamp and staleness warnings."""
        return call("get_injury_context", event_id)

    @server.tool(
        name="analyze_leg",
        title="Analyze one leg",
        annotations=_annotations(
            "Analyze one leg", read_only=True, destructive=False, idempotent=True, open_world=True
        ),
    )
    def analyze_leg(selection_id: str, date_local: S.LocalDate | None = None) -> S.LegAnalysis | S.ToolError:
        """Facts, interpretations, strongest reason against, injury context, data quality, reference probability, and price value for one selection."""
        return call("analyze_leg", selection_id, date_local)

    # ---- candidate construction ----

    @server.tool(
        name="build_three_leg_parlays",
        title="Build three-leg parlays",
        annotations=_annotations(
            "Build three-leg parlays", read_only=False, destructive=False, idempotent=False, open_world=True
        ),
    )
    def build_three_leg_parlays(
        date_local: S.LocalDate | None = None,
        parlay_type: ParlayTypeArg = "auto",
        max_candidates: int = 3,
        include_props: bool = True,
    ) -> S.BuildResponse | S.ToolError:
        """Research candidate exactly-three-leg tickets for the day (creates candidate records). Returns NO SUITABLE TICKET when evidence is inadequate."""
        if not 1 <= max_candidates <= 10:
            return S.ToolError(
                error="max_candidates must be between 1 and 10", reason_codes=["INVALID_INPUT"], detail=None
            )
        return call(
            "build_three_leg_parlays",
            date_local or today(),
            parlay_type=parlay_type,
            max_candidates=max_candidates,
            include_props=include_props,
        )

    @server.tool(
        name="analyze_my_parlay",
        title="Analyze my parlay",
        annotations=_annotations(
            "Analyze my parlay", read_only=False, destructive=False, idempotent=False, open_world=True
        ),
    )
    def analyze_my_parlay(
        three_selections: ThreeSelections,
        combined_odds: S.ManualQuoteInput | None = None,
        date_local: S.LocalDate | None = None,
    ) -> S.Candidate | S.ToolError:
        """Analyze a slip the user pasted (exactly three legs) and, optionally, the combined odds shown by Hard Rock Bet. Creates one candidate record."""
        selections = list(three_selections)
        if len(selections) != 3:
            return three_leg_error(len(selections), "a slip")
        return call("analyze_my_parlay", selections, combined_odds, date_local or today())

    @server.tool(
        name="check_parlay_correlation",
        title="Check parlay correlation",
        annotations=_annotations(
            "Check parlay correlation", read_only=True, destructive=False, idempotent=True, open_world=False
        ),
    )
    def check_parlay_correlation(candidate_id: str) -> S.CorrelationReport | S.ToolError:
        """Correlation flags between the three legs of a candidate and whether a joint probability may be multiplied."""
        return call("check_parlay_correlation", candidate_id)

    @server.tool(
        name="import_hardrock_quote",
        title="Import Hard Rock quote",
        annotations=_annotations(
            "Import Hard Rock quote", read_only=False, destructive=False, idempotent=True, open_world=False
        ),
    )
    def import_hardrock_quote(
        candidate_id: str, quote_fields: S.ManualQuoteInput
    ) -> S.Candidate | S.ToolError:
        """Attach the combined odds Hard Rock Bet actually shows for a candidate; replaces the indicative multiplied price."""
        return call("import_hardrock_quote", candidate_id, quote_fields)

    @server.tool(
        name="refresh_parlay",
        title="Refresh parlay",
        annotations=_annotations(
            "Refresh parlay", read_only=False, destructive=False, idempotent=True, open_world=True
        ),
    )
    def refresh_parlay(candidate_id: str) -> S.Candidate | S.ToolError:
        """Re-validate a candidate against fresh odds and injuries; may move it to EXPIRED or REJECTED."""
        return call("refresh_parlay", candidate_id)

    # ---- budget and ledger ----

    @server.tool(
        name="select_ticket",
        title="Select ticket (reserve budget)",
        annotations=_annotations(
            "Select ticket (reserve budget)",
            read_only=False,
            destructive=True,
            idempotent=True,
            open_world=False,
        ),
        meta=dict(REQUIRES_USER_INTERACTION),
    )
    def select_ticket(
        candidate_id: str, stake_usd: Decimal, idempotency_key: str | None = None
    ) -> S.SelectResponse | S.ToolError:
        """Reserve stake against today's budget ledger for a candidate the user intends to place themselves. Does not place a bet."""
        return call("select_ticket", candidate_id, Decimal(stake_usd), idempotency_key)

    @server.tool(
        name="release_reservation",
        title="Release reservation",
        annotations=_annotations(
            "Release reservation", read_only=False, destructive=True, idempotent=True, open_world=False
        ),
    )
    def release_reservation(reservation_id: str, reason: str) -> S.BudgetReservation | S.ToolError:
        """Release an active budget reservation the user decided not to place."""
        return call("release_reservation", reservation_id, reason)

    @server.tool(
        name="get_daily_budget",
        title="Daily budget",
        annotations=_annotations(
            "Daily budget", read_only=True, destructive=False, idempotent=True, open_world=False
        ),
    )
    def get_daily_budget(
        date_local: S.LocalDate | None = None, proposed_stake_usd: Decimal | None = None
    ) -> S.DailyBudget | S.ToolError:
        """Cap, recorded stake, reserved stake, and remaining for an America/New_York day (app ledger, not a sportsbook limit)."""
        proposed = Decimal(proposed_stake_usd) if proposed_stake_usd is not None else None
        return call("get_daily_budget", date_local or today(), proposed)

    @server.tool(
        name="record_actual_bet",
        title="Record actual bet",
        annotations=_annotations(
            "Record actual bet", read_only=False, destructive=True, idempotent=True, open_world=False
        ),
        meta=dict(REQUIRES_USER_INTERACTION),
    )
    def record_actual_bet(
        confirmed_ticket_fields: S.ConfirmedTicketInput, idempotency_key: str
    ) -> S.RecordResponse | S.ToolError:
        """Record a wager the user confirms they placed in the Hard Rock Bet app (append-only ledger; replays by idempotency key). Tool-prepared bets have exactly three legs; set external=true for any other wager you report."""
        legs = confirmed_ticket_fields.legs
        if not legs:
            return S.ToolError(
                error="a bet needs at least one leg", reason_codes=["INVALID_INPUT"], detail=None
            )
        if not confirmed_ticket_fields.external and len(legs) != 3:
            return three_leg_error(len(legs), "a tool-prepared bet")
        return call("record_actual_bet", confirmed_ticket_fields, idempotency_key)

    @server.tool(
        name="reconcile_settlement",
        title="Reconcile settlement",
        annotations=_annotations(
            "Reconcile settlement", read_only=False, destructive=True, idempotent=True, open_world=False
        ),
        meta=dict(REQUIRES_USER_INTERACTION),
    )
    def reconcile_settlement(
        bet_id: str, settlement_fields: S.SettlementInput
    ) -> S.SettlementResponse | S.ToolError:
        """Append a settlement record (won/lost/void/repriced/cashed out/disputed/corrected) for a recorded bet."""
        return call("reconcile_settlement", bet_id, settlement_fields)

    # ---- reports ----

    @server.tool(
        name="get_performance",
        title="Performance report",
        annotations=_annotations(
            "Performance report", read_only=True, destructive=False, idempotent=True, open_world=False
        ),
    )
    def get_performance(start_date: S.LocalDate, end_date: S.LocalDate) -> S.PerformanceReport | S.ToolError:
        """Stake, returns, net, hit rates, accepted-vs-recommended odds, and calibration for a date range."""
        return call("get_performance", start_date, end_date)

    @server.tool(
        name="generate_30_day_review",
        title="30-day review",
        annotations=_annotations(
            "30-day review", read_only=True, destructive=False, idempotent=True, open_world=False
        ),
    )
    def generate_30_day_review() -> S.ReviewReport | S.ToolError:
        """The review for the configured window (2026-10-20 to 2026-11-18): observed results, not evidence of skill."""
        return call("generate_30_day_review")

    # ---- settings and costs ----

    @server.tool(
        name="set_user_settings",
        title="Set user settings",
        annotations=_annotations(
            "Set user settings", read_only=False, destructive=True, idempotent=True, open_world=False
        ),
    )
    def set_user_settings(
        daily_cap_usd: Decimal | None = None,
        display_tz: str | None = None,
        odds_api_key: str | None = None,
        confirm_onboarding: bool = False,
    ) -> S.UserSettings | S.ToolError:
        """Update the daily cap, display time zone, a personal The Odds API key (stored encrypted, never returned), or confirm onboarding."""
        cap = Decimal(daily_cap_usd) if daily_cap_usd is not None else None
        return call("set_user_settings", cap, display_tz, odds_api_key, confirm_onboarding)

    @server.tool(
        name="add_cost",
        title="Add cost",
        annotations=_annotations(
            "Add cost", read_only=False, destructive=False, idempotent=True, open_world=False
        ),
    )
    def add_cost(cost: S.CostInput) -> S.CostEntry | S.ToolError:
        """Record a data, software, hosting, or other cost so performance can be shown after costs."""
        return call("add_cost", cost)

    @server.tool(
        name="export_my_data",
        title="Export my data",
        annotations=_annotations(
            "Export my data", read_only=True, destructive=False, idempotent=True, open_world=False
        ),
    )
    def export_my_data() -> dict[str, Any] | S.ToolError:
        """Every record stored for the current user (candidates, reservations, bets, settlements, costs, settings)."""
        result = call("export_my_data")
        if isinstance(result, S.ToolError):
            return result
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        return dict(result)

    return server


def run_stdio(settings: Settings, db: Database, clock: Clock, services: Any | None = None) -> None:
    """Run the server on stdio (local mode, auth_mode none)."""
    build_server(settings, db, clock, services).run(transport="stdio")
