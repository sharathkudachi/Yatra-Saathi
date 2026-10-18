"""App startup, routers, wiring (Developer 1). Refuses to start against an
unsafe database configuration (section 3.1)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

for candidate in [Path(__file__).parent.parent / ".env.backend", Path(".env.backend"), Path("backend/.env.backend")]:
    if candidate.exists():
        load_dotenv(candidate)
        break
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api import errors as api_errors
from src.api.routes.human import audit as human_audit
from src.api.routes.human import auth, auth_demo, bookings as human_bookings, cart as human_cart
from src.api.routes.human import confirmations as human_confirmations, health, sessions as human_sessions
from src.api.routes.human import search as human_search
from src.api.routes.human import trips as human_trips
from src.api.routes.human import itineraries as human_itineraries
from src.api.routes.human import notifications as human_notifications
from src.api.routes.human import preferences as human_preferences
from src.api.routes.human import destinations as human_destinations
from src.api.routes.human import hotels as human_hotels
from src.api.routes.human import language as human_language
from src.api.routes.human import voice as human_voice
from src.api.routes.human import phase6_notifications as human_phase6_notifications
from src.api.routes.human import emergency as human_emergency
from src.services import notify_scheduler
from src.api.routes.internal_agent import booking_requests, budget_checks, cart as agent_cart
from src.api.routes.internal_agent import catalog as agent_catalog
from src.api.routes.internal_agent import clarifications, context, plan, replans, results, run_outcome, state
from src.api.routes.internal_agent import tool_calls
from src.api.routes.internal_agent import comparison as agent_comparison
from src.api.routes.internal_agent import preferences as agent_preferences
from src.core.clock import SystemClock
from src.core.config import Settings, cors_origins_from_env
from src.core.errors import SafetyError
from src.db.working_copy_guard import assert_working_copy
from src.middleware.actor_context import ActorContextMiddleware
from src.middleware.request_id import RequestIdMiddleware
from src.middleware.request_logging import RequestLoggingMiddleware

HUMAN_PREFIX = "/api/v1"
AGENT_PREFIX = "/internal/agent/v1"


def _validate_startup_db(settings: Settings) -> None:
    path = settings.require_db_path()
    try:
        assert_working_copy(path, settings.original_db_path)
    except SafetyError:
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    _validate_startup_db(settings)
    app.state.settings = settings
    app.state.clock = SystemClock()
    stop = notify_scheduler.start(settings) if settings.notify_scheduler else None
    yield
    if stop is not None:
        stop.set()


def create_app(settings: Settings | None = None, clock=None, agent_dispatcher=None) -> FastAPI:
    app = FastAPI(title="Tech4ce Travel Agent Backend", lifespan=lifespan if settings is None else None)
    if settings is not None:
        # Test/embedding path: settings supplied directly instead of read from the environment.
        _validate_startup_db(settings)
        app.state.settings = settings
        app.state.clock = clock or SystemClock()
        app.state.agent_dispatcher = agent_dispatcher

    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(ActorContextMiddleware)
    app.add_middleware(RequestIdMiddleware)
    # Middleware must be registered before the lifespan runs, so CORS comes from the supplied
    # settings or straight from the environment.
    cors_origins = settings.cors_allow_origins if settings is not None else cors_origins_from_env()
    if cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(cors_origins), allow_credentials=False,
                           allow_methods=["*"], allow_headers=["*"])

    api_errors.register(app)

    app.include_router(health.router, prefix=HUMAN_PREFIX)
    app.include_router(auth.router, prefix=HUMAN_PREFIX)
    app.include_router(auth_demo.router, prefix=HUMAN_PREFIX)
    app.include_router(human_sessions.router, prefix=HUMAN_PREFIX)
    app.include_router(human_cart.router, prefix=HUMAN_PREFIX)
    app.include_router(human_confirmations.router, prefix=HUMAN_PREFIX)
    app.include_router(human_bookings.router, prefix=HUMAN_PREFIX)
    app.include_router(human_audit.router, prefix=HUMAN_PREFIX)
    app.include_router(human_search.router, prefix=HUMAN_PREFIX)
    app.include_router(human_trips.router, prefix=HUMAN_PREFIX)
    app.include_router(human_itineraries.router, prefix=HUMAN_PREFIX)
    app.include_router(human_notifications.router, prefix=HUMAN_PREFIX)
    app.include_router(human_preferences.router, prefix=HUMAN_PREFIX)
    app.include_router(human_destinations.router, prefix=HUMAN_PREFIX)
    app.include_router(human_hotels.router, prefix=HUMAN_PREFIX)
    app.include_router(human_language.router, prefix=HUMAN_PREFIX)
    app.include_router(human_voice.router, prefix=HUMAN_PREFIX)
    app.include_router(human_phase6_notifications.router, prefix=HUMAN_PREFIX)
    app.include_router(human_emergency.router, prefix=HUMAN_PREFIX)

    app.include_router(context.router, prefix=AGENT_PREFIX)
    app.include_router(plan.router, prefix=AGENT_PREFIX)
    app.include_router(tool_calls.router, prefix=AGENT_PREFIX)
    app.include_router(agent_catalog.router, prefix=AGENT_PREFIX)
    app.include_router(results.router, prefix=AGENT_PREFIX)
    app.include_router(agent_cart.router, prefix=AGENT_PREFIX)
    app.include_router(budget_checks.router, prefix=AGENT_PREFIX)
    app.include_router(replans.router, prefix=AGENT_PREFIX)
    app.include_router(clarifications.router, prefix=AGENT_PREFIX)
    app.include_router(booking_requests.router, prefix=AGENT_PREFIX)
    app.include_router(state.router, prefix=AGENT_PREFIX)
    app.include_router(run_outcome.router, prefix=AGENT_PREFIX)
    app.include_router(agent_comparison.router, prefix=AGENT_PREFIX)
    app.include_router(agent_preferences.router, prefix=AGENT_PREFIX)

    return app


app = create_app()
