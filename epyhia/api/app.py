from pathlib import Path

import logfire
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from epyhia.api.errors import register_exception_handlers
from epyhia.api.routers import (
    actions,
    artifacts,
    brand_docs,
    briefs,
    checkout,
    cost,
    export,
    orders,
    runs,
    sink,
    tasks,
    webhooks,
)
from epyhia.gate.keys import ALIAS_ORIGIN_PATTERN
from epyhia.observability import configure_tracing

CONSOLE_DIST = Path(__file__).resolve().parent.parent.parent / "console" / "dist"

# Where the operator surface lives, so the console can own the root namespace it routes in.
# One origin still, therefore still no CORS between the two (DESIGN.md §11).
API_PREFIX = "/api"


def create_app() -> FastAPI:
    configure_tracing()

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

    # The operator surface is namespaced. The console is served from this same origin and
    # routes on the client, and its route strings — `/runs`, `/runs/{id}/cost`, … — are the
    # same strings as these. Sharing one namespace means the API wins every collision and a
    # console reload answers with JSON instead of the page (contracts/rest-api.md).
    for module in (briefs, runs, actions, tasks, artifacts, brand_docs, cost, orders, export):
        app.include_router(module.router, prefix=API_PREFIX)

    # Buyer-facing, and neither one an operator route: the buy click is authenticated by
    # nothing (it is a stranger on the generated site) and the webhook by its signature.
    # These keep their bare paths — both are held by systems outside this repository, in
    # Stripe's dashboard and in the bytes of every already-deployed site, so prefixing them
    # would move an address this app does not own. The sink is the same case (R4).
    app.include_router(checkout.router)
    app.include_router(webhooks.router)
    app.include_router(sink.router)

    # The built bundle. Everything else the console needs is `index.html`, served below.
    app.mount(
        "/assets",
        StaticFiles(directory=CONSOLE_DIST / "assets", check_dir=False),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def console_spa(full_path: str) -> FileResponse:
        """The console shell, for any path the API did not claim.

        The console routes on the client, so a reload of `/approvals` or `/runs/{id}` arrives
        here as a path with no file behind it and must still be answered with the shell.

        An unclaimed path *under the prefix* stays a 404 in the API's own shape: handing an
        API client 200 OK carrying HTML would surface a typo as a parse error somewhere far
        away from the mistake that caused it.
        """
        prefix = API_PREFIX.lstrip("/")
        if full_path == prefix or full_path.startswith(f"{prefix}/"):
            raise HTTPException(
                status_code=404, detail={"error": "not_found", "detail": "no such route"}
            )
        index = CONSOLE_DIST / "index.html"
        if not index.is_file():
            # A source checkout with no `npm run build` behind it. Legible beats a 500.
            raise HTTPException(
                status_code=404,
                detail={"error": "console_not_built", "detail": "console/dist is absent"},
            )
        return FileResponse(index)

    return app


app = create_app()
