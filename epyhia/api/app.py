from pathlib import Path

import logfire
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from epyhia.api.errors import register_exception_handlers

CONSOLE_DIST = Path(__file__).resolve().parent.parent.parent / "console" / "dist"


def create_app() -> FastAPI:
    logfire.configure(send_to_logfire="if-token-present")

    app = FastAPI(title="EPYHIA")
    logfire.instrument_fastapi(app)
    register_exception_handlers(app)

    # Routers are mounted here as they are implemented (briefs, runs, actions,
    # checkout, webhooks, sink) — every span they open carries run_id, per
    # DESIGN.md: "run_id ... is on every agent span".

    # Serves the built SPA from the same origin as the API — no CORS.
    app.mount(
        "/",
        StaticFiles(directory=CONSOLE_DIST, html=True, check_dir=False),
        name="console",
    )

    return app


app = create_app()
