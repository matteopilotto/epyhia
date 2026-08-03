from pathlib import Path

import logfire
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from epyhia.api.errors import register_exception_handlers
from epyhia.api.routers import actions, briefs, runs

CONSOLE_DIST = Path(__file__).resolve().parent.parent.parent / "console" / "dist"


def create_app() -> FastAPI:
    logfire.configure(send_to_logfire="if-token-present")

    app = FastAPI(title="EPYHIA")
    logfire.instrument_fastapi(app)
    register_exception_handlers(app)

    # More routers are mounted here as they are implemented (checkout, webhooks, sink) —
    # every span they open carries run_id, per DESIGN.md: "run_id ... is on every agent span".
    app.include_router(briefs.router)
    app.include_router(runs.router)
    app.include_router(actions.router)

    # Serves the built SPA from the same origin as the API — no CORS.
    app.mount(
        "/",
        StaticFiles(directory=CONSOLE_DIST, html=True, check_dir=False),
        name="console",
    )

    return app


app = create_app()
