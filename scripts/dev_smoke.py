"""Manual smoke test for the Phase 2d API surface — bypasses Auth0 since it isn't
configured locally, and stubs the guardrail's LLM call since no ANTHROPIC_API_KEY is
required to run this. Run: uv run python scripts/dev_smoke.py
"""

import json

from fastapi.testclient import TestClient

import epyhia.api.routers.briefs as briefs_module
from epyhia.api.app import app
from epyhia.api.auth import require_operator
from epyhia.ingest.guardrail import GuardrailResult

app.dependency_overrides[require_operator] = lambda: {"sub": "dev|smoke"}


async def _fake_screen(brief: dict) -> GuardrailResult:
    return GuardrailResult(decision="pass", reason="dev smoke test", model="fake")


briefs_module.screen_brief = _fake_screen

brief = json.loads(open("tests/fixtures/briefs/one.json").read())

with TestClient(app) as client:
    r = client.post("/briefs", json=brief)
    print("POST /briefs ->", r.status_code, r.json())

    if r.status_code == 201:
        run_id = r.json()["run_id"]
        print("GET /runs/{id} ->", client.get(f"/runs/{run_id}").json())
        print("GET /runs ->", client.get("/runs").status_code)

    print("POST /briefs (bad schema) ->", client.post("/briefs", json={}).json())
