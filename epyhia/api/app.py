from pathlib import Path

import logfire
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from epyhia.api.errors import register_exception_handlers
from epyhia.api.routers import actions, artifacts, briefs, checkout, runs, sink, webhooks
from epyhia.gate.keys import ALIAS_ORIGIN_PATTERN

CONSOLE_DIST = Path(__file__).resolve().parent.parent.parent / "console" / "dist"


def create_app() -> FastAPI:
    logfire.configure(send_to_logfire="if-token-present")

    app = FastAPI(title="EPYHIA")
    logfire.instrument_fastapi(app)
    register_exception_handlers(app)

    # The console shares this origin and needs no CORS. The generated site does not: it is
    # served from the run's own alias, so its buy button is cross-origin by construction.
    # Scoped to the alias shape, one method and one header — not a wildcard.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=ALIAS_ORIGIN_PATTERN,
        allow_methods=["POST"],
        allow_headers=["content-type"],
    )

    app.include_router(briefs.router)
    app.include_router(runs.router)
    app.include_router(actions.router)
    app.include_router(artifacts.router)
    app.include_router(sink.router)
    # Buyer-facing, and neither one an operator route: the buy click is authenticated by
    # nothing (it is a stranger on the generated site) and the webhook by its signature.
    app.include_router(checkout.router)
    app.include_router(webhooks.router)

    # Serves the built SPA from the same origin as the API — no CORS.
    app.mount(
        "/",
        StaticFiles(directory=CONSOLE_DIST, html=True, check_dir=False),
        name="console",
    )

    return app


app = create_app()
