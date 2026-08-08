"""Open a run against the database the app is pointed at, then leave it to the worker.

    uv run python scripts/submit_brief.py --brief my-brief.json

This is `POST /briefs` without the bearer token. Every operator route is Auth0-guarded and
there is deliberately no bypass key (FR-057), so a curl against a running API needs a token
minted by the console's own login — which is a browser flow, not something a terminal can
do. The router function itself is called here instead, so the run is opened by exactly the
code the endpoint runs: same schema validation, same guardrail call, same grounding set,
same `plan` task. Nothing about the run differs from one submitted through the console.

The guardrail is a real model call (a few tenths of a cent). Everything after this point
belongs to the worker process, which will spend real money on the crew — so start the
worker only when you mean to.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from epyhia.api.routers.briefs import submit_brief
from epyhia.config import settings

REPO = Path(__file__).resolve().parent.parent


async def main(brief_path: Path) -> int:
    engine = create_async_engine(settings.database_url)
    try:
        async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
            result = await submit_brief(json.loads(brief_path.read_text()), session)
    finally:
        await engine.dispose()

    if isinstance(result, JSONResponse):
        print(result.body.decode("utf-8"), file=sys.stderr)
        return 1

    print(f"run      {result['run_id']}")
    print(f"brief    {brief_path}  ({result['content_sha256'][:12]}…)")
    print(f"alias    {result['alias']}")
    print("\nplan task is pending — start the worker to run it.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--brief", type=Path, default=REPO / "my-brief.json")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.brief)))
