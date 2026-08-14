"""Draw the plan stage N times per brief and measure how far the directions spread.

    uv run python scripts/sample_directions.py                          # stub model, free
    DATABASE_URL=…scratch ANTHROPIC_API_KEY=sk-… \
        uv run python scripts/sample_directions.py --real --samples 4 \
        tests/fixtures/briefs/one.json tests/fixtures/briefs/two.json

SC-001 asks whether two briefs produce distinct visual directions. That is a property of a
distribution, and it has twice been read off a single pair of runs and twice had to be
retracted. This draws the plan stage repeatedly through the real handler — same prompt
version, same model tier, same code path a client's run takes — and reports what the draws
actually look like: pairing and archetype distributions within each brief, and perceptual
palette distance across them.

`--real` calls Opus 5 and costs roughly $0.36 a sample. Everything else runs offline against
a stubbed Strategist, which exercises this harness and measures nothing about the model.

Two things worth knowing before reading a number out of this:

- The Strategist does not memoise, so repeated plan stages against one brief are genuinely
  fresh draws. Server-side prompt caching changes what they cost, not whether they are
  independent.
- Nothing is truncated between samples. Each draw is its own run row against its own plan
  task, so **point `DATABASE_URL` at a scratch database** — this leaves rows behind.
"""

import argparse
import asyncio
import json
import statistics
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import epyhia.queue.handlers  # noqa: F401  — registers every task handler
from epyhia.agents import strategist
from epyhia.config import settings
from epyhia.design.colour import (
    ACCENT_SAME_DELTA_E,
    BG_SAME_DELTA_E,
    delta_e,
    same_direction,
)
from epyhia.design.fonts import library
from epyhia.gate.keys import alias_for
from epyhia.ingest.catalogue import resolve_catalogue
from epyhia.ingest.grounding import build_grounding_set
from epyhia.ingest.hashing import content_sha256
from epyhia.models.agent_calls import AgentCall
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.prompts_service import prompt_service
from epyhia.queue.worker import run_once

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "samples"
FIXTURES = REPO / "tests/fixtures/briefs"

# What one plan stage has cost in the ledger to date, for the warning before spending it.
# The 4 × 2 draw of 2026-08-14 came to $2.912 over eight calls ($0.199–$0.538 each).
COST_PER_SAMPLE_USD = 0.36

PALETTE_SLOTS = ("bg", "fg", "accent", "muted")


# --- drawing ------------------------------------------------------------------------------


def stub_strategist(brief: dict, index: int) -> FunctionModel:
    """A Strategist that varies with the sample index and reads nothing.

    Its draws are a rotation, not a model's choice, so a stubbed report says only that the
    harness and the arithmetic work. The archetype ids and font ids are EPYHIA's own library
    names — infrastructure, not client data — and the client facts it carries are copied out
    of the brief it was handed, exactly as `preview_site.py`'s stub does.
    """
    displays = [face for face in library.faces if face.role in ("display", "both")]
    bodies = [face for face in library.faces if face.role in ("body", "both")]
    palettes = [
        {"bg": "#F3EBDF", "fg": "#241C16", "accent": "#B5451B", "muted": "#6B5D50"},
        {"bg": "#14161A", "fg": "#E8E4DC", "accent": "#4C7DE0", "muted": "#8A8F98"},
    ]
    archetypes = ["editorial_stack", "split_technical"]
    layouts = ["feature_rows", "offer_table"]
    calls: list[int] = []

    def respond(messages, info) -> ModelResponse:
        # The second turn ends the run. A stub that answered the tool call with the same tool
        # call would write a brand doc per turn, forever.
        calls.append(1)
        if len(calls) > 1:
            return ModelResponse(parts=[TextPart("planned")])
        doc = {
            "name": brief["business_name"],
            "descriptor": brief["one_liner"],
            "positioning": brief["positioning"]["why_them"],
            "palette": palettes[index % len(palettes)],
            "type": {
                "display": displays[index % len(displays)].id,
                "body": bodies[index % len(bodies)].id,
            },
            "motion_language": "stubbed",
            "composition_archetype": archetypes[index % len(archetypes)],
            "video_archetype": "technical_spec_sheet",
            "voice": brief["voice"],
            "offerings": [
                {k: v for k, v in product.items() if k != "currency_charge"}
                for product in brief["products"]
            ],
            "composition_plan": [
                {"section": "opening", "layout": "hero_stacked", "intent": "state what this is"},
                {
                    "section": "detail",
                    "layout": layouts[index % len(layouts)],
                    "intent": "the detail",
                },
            ],
        }
        return ModelResponse(parts=[ToolCallPart("write_brand_doc", {"doc": doc})])

    return FunctionModel(respond)


async def ensure_brief(session: AsyncSession, payload: dict) -> Brief:
    """The brief row for this fixture, inserted once.

    One row per fixture rather than one per sample: `briefs.content_sha256` is unique, and
    the same payload is the same brief by the system's own definition of one. Making N brief
    rows would mean perturbing the payload, which changes the thing being sampled. The draws
    stay independent — the Strategist reads the payload and nothing else, and it does not
    memoise.
    """
    brief_hash = content_sha256(payload)
    existing = await session.scalar(
        select(Brief).where(Brief.content_sha256 == brief_hash)
    )
    if existing is not None:
        return existing
    brief = Brief(
        id=uuid.uuid4(),
        payload=payload,
        content_sha256=brief_hash,
        # Seeded, so no sample pays for a guardrail decision on a fixture that has passed
        # one many times over.
        guardrail_decision="pass",
        guardrail_reason="direction sampling",
        guardrail_model="none",
    )
    session.add(brief)
    await session.flush()
    return brief


async def draw(session: AsyncSession, brief: Brief) -> tuple[dict, uuid.UUID]:
    """One plan stage through the real handler. Returns the brand doc it wrote."""
    run = Run(
        id=uuid.uuid4(),
        brief_id=brief.id,
        prompt_version=prompt_service.active_version("strategist"),
        grounding_set=build_grounding_set(brief.payload, datetime.now(UTC).year),
        resolved_catalogue=resolve_catalogue(brief.payload["products"]),
        budget_usd=25,
        status="running",
        alias=alias_for(brief.content_sha256),
    )
    session.add(run)
    await session.flush()
    task_id = uuid.uuid4()
    session.add(Task(id=task_id, run_id=run.id, kind="plan", state="pending"))
    await session.commit()

    if not await run_once(session, kind="plan"):
        raise RuntimeError("no plan task was claimable")
    # `run_once` records a handler failure on the row rather than raising, so a sample that
    # did not produce a direction has to be read back or it is silently counted as one.
    task = await session.get(Task, task_id)
    await session.refresh(task)
    if task.state != "done":
        raise RuntimeError(f"plan task {task.state}: {task.error}")

    doc = await session.scalar(
        select(BrandDoc)
        .where(BrandDoc.brief_id == brief.id)
        .order_by(BrandDoc.version.desc())
        .limit(1)
    )
    return doc.doc, run.id


# --- reading the draws --------------------------------------------------------------------


@dataclass
class Sampled:
    """One fixture's draws, and everything the report says about them on their own."""

    name: str
    docs: list[dict]

    @property
    def pairings(self) -> Counter:
        return Counter(f"{d['type']['display']}/{d['type']['body']}" for d in self.docs)

    @property
    def archetypes(self) -> Counter:
        return Counter(d["composition_archetype"] for d in self.docs)

    @property
    def layouts(self) -> Counter:
        return Counter(
            section["layout"] for d in self.docs for section in d["composition_plan"]
        )

    @property
    def medoid(self) -> dict:
        """The draw closest to the rest of its own — this fixture's typical palette.

        A mode is undefined over continuous values, and a mean palette is a colour no run
        ever chose. The medoid is one of the actual draws, which is what SC-001 is about.
        """
        palettes = [d["palette"] for d in self.docs]
        return min(
            palettes,
            key=lambda p: sum(
                delta_e(p["bg"], q["bg"]) + delta_e(p["accent"], q["accent"])
                for q in palettes
            ),
        )

    def spread(self, slot: str) -> list[float]:
        """Every pairwise distance within this fixture, for one palette slot."""
        colours = [d["palette"][slot] for d in self.docs]
        return [
            delta_e(first, second)
            for i, first in enumerate(colours)
            for second in colours[i + 1 :]
        ]


def _counts(counter: Counter) -> str:
    return ", ".join(f"{name} ×{count}" for name, count in counter.most_common())


def _modes(counter: Counter) -> set[str]:
    """Every value tied for most frequent, not an arbitrary one of them.

    `most_common(1)` on an all-distinct sample returns whichever the dict happened to hold
    first, and a verdict decided by insertion order is worse than no verdict. A tie is a
    real answer — it says this brief has no settled choice — so it is reported as one.
    """
    top = max(counter.values())
    return {name for name, count in counter.items() if count == top}


def _matrix(first: Sampled, second: Sampled, slot: str) -> list[str]:
    """Every cross-fixture pair for one slot. The matrix rather than one number, because a
    single summary of sixteen distances is where the last two readings went wrong."""
    header = "        " + " ".join(f"{i:>6}" for i in range(len(second.docs)))
    rows = [header]
    for i, left in enumerate(first.docs):
        cells = " ".join(
            f"{delta_e(left['palette'][slot], right['palette'][slot]):6.1f}"
            for right in second.docs
        )
        rows.append(f"    {i:<4}{cells}")
    return rows


def report(samples: list[Sampled], *, real: bool, spend_usd: float) -> str:
    lines = [
        f"# Direction sample — {datetime.now(UTC).date().isoformat()}",
        "",
        f"strategist prompt {prompt_service.active_version('strategist')} · "
        f"{'REAL model' if real else 'STUBBED — this measures the harness, not the model'} · "
        f"{len(samples[0].docs)} samples × {len(samples)} fixtures · ${spend_usd:.2f}",
    ]

    for sampled in samples:
        modal_pairings = _modes(sampled.pairings)
        repeats = max(sampled.pairings.values())
        accents = sampled.spread("accent")
        grounds = sampled.spread("bg")
        lines += [
            "",
            f"## Within {sampled.name} (n={len(sampled.docs)})",
            "",
            f"    pairing     {_counts(sampled.pairings)}",
            f"                modal {', '.join(sorted(modal_pairings))} — "
            f"{repeats}/{len(sampled.docs)} draws each",
            f"    archetype   {_counts(sampled.archetypes)}",
            f"    layouts     {_counts(sampled.layouts)}",
            f"    palette ΔE  accent max {max(accents, default=0.0):.1f}, "
            f"median {statistics.median(accents) if accents else 0.0:.1f}"
            f" · bg max {max(grounds, default=0.0):.1f}, "
            f"median {statistics.median(grounds) if grounds else 0.0:.1f}",
            f"    medoid      {json.dumps(sampled.medoid, sort_keys=True)}",
        ]

    lines += ["", "## Across fixtures", ""]
    for i, first in enumerate(samples):
        for second in samples[i + 1 :]:
            shared_pairings = set(first.pairings) & set(second.pairings)
            shared_archetypes = set(first.archetypes) & set(second.archetypes)
            lines += [
                f"### {first.name} × {second.name}",
                "",
                f"    shared pairings   {', '.join(sorted(shared_pairings)) or 'none'}",
                f"    shared archetypes {', '.join(sorted(shared_archetypes)) or 'none'}",
            ]
            for slot in PALETTE_SLOTS:
                lines += ["", f"    ΔE {slot}", *_matrix(first, second, slot)]
            lines += ["", *_verdict(first, second), ""]

    return "\n".join(lines) + "\n"


def _verdict(first: Sampled, second: Sampled) -> list[str]:
    """SC-001 restated as something a distribution can answer: across N samples per fixture,
    the two fixtures' modal directions differ — no shared pairing mode, modal palettes not
    same-direction under the calibrated thresholds, no shared archetype mode."""
    pairings = (_modes(first.pairings), _modes(second.pairings))
    archetypes = (_modes(first.archetypes), _modes(second.archetypes))
    checks = [
        (
            "modal pairings differ",
            not pairings[0] & pairings[1],
            f"{{{', '.join(sorted(pairings[0]))}}} vs {{{', '.join(sorted(pairings[1]))}}}",
        ),
        (
            "modal palettes are different directions",
            not same_direction(first.medoid, second.medoid),
            f"ΔE accent {delta_e(first.medoid['accent'], second.medoid['accent']):.1f} "
            f"(bar {ACCENT_SAME_DELTA_E:g}), "
            f"bg {delta_e(first.medoid['bg'], second.medoid['bg']):.1f} "
            f"(bar {BG_SAME_DELTA_E:g})",
        ),
        (
            "modal archetypes differ",
            not archetypes[0] & archetypes[1],
            f"{{{', '.join(sorted(archetypes[0]))}}} vs "
            f"{{{', '.join(sorted(archetypes[1]))}}}",
        ),
    ]
    lines = ["    SC-001, measured over the samples:"]
    for name, passed, detail in checks:
        lines.append(f"      [{'PASS' if passed else 'FAIL'}] {name} — {detail}")
    lines.append(
        f"    verdict: {'MET' if all(passed for _, passed, _ in checks) else 'NOT MET'}"
    )
    return lines


# --- driving ------------------------------------------------------------------------------


async def main(brief_paths: list[Path], samples: int, real: bool, out: Path) -> int:
    if real and not settings.anthropic_api_key:
        print("--real needs ANTHROPIC_API_KEY set", file=sys.stderr)
        return 1
    if not settings.database_url:
        print(
            "set DATABASE_URL to a scratch database — this script leaves its runs behind",
            file=sys.stderr,
        )
        return 1

    engine = create_async_engine(settings.database_url)
    session = async_sessionmaker(bind=engine, expire_on_commit=False)()

    total = samples * len(brief_paths)
    print(f"database {settings.database_url.rsplit('@', 1)[-1]}")
    print(f"fixtures {', '.join(path.name for path in brief_paths)}")
    estimate = f"REAL — about ${total * COST_PER_SAMPLE_USD:.2f} for {total} samples"
    print(f"models   {estimate if real else 'stubbed (offline, free)'}\n")

    drawn: list[Sampled] = []
    run_ids: list[uuid.UUID] = []
    for path in brief_paths:
        payload = json.loads(path.read_text())
        brief = await ensure_brief(session, payload)
        docs: list[dict] = []
        for index in range(samples):
            if real:
                doc, run_id = await draw(session, brief)
            else:
                with strategist.agent.override(model=stub_strategist(payload, index)):
                    doc, run_id = await draw(session, brief)
            docs.append(doc)
            run_ids.append(run_id)
            destination = out / path.stem / f"{index}.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
            print(
                f"  {path.stem} {index}  {doc['type']['display']}/{doc['type']['body']}"
                f"  {doc['composition_archetype']}  {doc['palette']['accent']}"
            )
        drawn.append(Sampled(name=path.stem, docs=docs))

    spend = await session.scalar(
        select(func.coalesce(func.sum(AgentCall.cost_usd), 0)).where(
            AgentCall.run_id.in_(run_ids)
        )
    )
    written = report(drawn, real=real, spend_usd=float(spend))
    (out / "report.md").write_text(written)
    print("\n" + written)
    print(f"written  {out / 'report.md'}")

    await session.close()
    await engine.dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "briefs",
        nargs="*",
        type=Path,
        default=[FIXTURES / "one.json", FIXTURES / "two.json"],
        help="brief fixtures to sample (default: every fixture the suite ships)",
    )
    parser.add_argument("--samples", type=int, default=4, help="draws per brief")
    parser.add_argument("--real", action="store_true", help="call Opus 5 (costs money)")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.briefs, args.samples, args.real, args.out)))
