"""Two headless renders of the finished page, for the eyes that judge it.

The worker image already carries Chromium — Remotion needs it — so this drives that binary
through its own CLI rather than adding a second rendering environment (FR-012). A local
render spends nothing and sends nothing, which is why it does not route through the Action
Gate (DESIGN.md §6.4), and why there is no credential anywhere in this module.

Nothing here raises. A missing binary, a failed subprocess and a timeout all come back as an
unavailable result, because the visual review is an improvement to the page and a run must
never fail for want of a browser (FR-015).
"""

import asyncio
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Phone and desktop, tall rather than full-page: Chromium's `--screenshot` captures the
# viewport, a tall window captures the page's establishing flow, and the critic is judging
# rhythm and hierarchy rather than auditing every pixel down to the footer (research R4).
VIEWPORTS = ((390, 2200), (1440, 2400))

# Wall clock for one capture. Generous against a page whose own script runs on load, short
# enough that two of them cannot eat a meaningful share of the site task's 15-minute lease.
TIMEOUT_SECONDS = 45.0

# `PUPPETEER_EXECUTABLE_PATH` is set in the worker image, where the binary certainly exists.
# The rest is for a developer's machine, and it is a fixed list rather than a config knob:
# absence is a recorded skip, so there is nothing here for an operator to tune.
FALLBACK_BINARIES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "chromium",
    "chromium-browser",
    "google-chrome",
)


@dataclass(frozen=True)
class Screenshots:
    """What the render step produced, or why it produced nothing."""

    images: tuple[bytes, ...] = ()
    widths: tuple[int, ...] = ()
    unavailable: str | None = None

    @property
    def captured(self) -> bool:
        return self.unavailable is None

    @classmethod
    def missing(cls, reason: str) -> "Screenshots":
        return cls(unavailable=reason)


def chromium_path() -> str | None:
    """The browser to drive, or `None` if this machine has none."""
    configured = os.environ.get("PUPPETEER_EXECUTABLE_PATH")
    candidates = ([configured] if configured else []) + list(FALLBACK_BINARIES)
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
    return None


async def _shoot(binary: str, page: Path, out: Path, width: int, height: int) -> None:
    process = await asyncio.create_subprocess_exec(
        binary,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        "--virtual-time-budget=5000",
        f"--window-size={width},{height}",
        f"--screenshot={out}",
        f"file://{page}",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), TIMEOUT_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError(f"the render did not finish within {TIMEOUT_SECONDS:g}s") from None
    if process.returncode != 0:
        raise RuntimeError(
            f"chromium exited {process.returncode}: "
            f"{stderr.decode('utf-8', 'replace')[-500:]}"
        )
    if not out.is_file() or out.stat().st_size == 0:
        raise RuntimeError("chromium wrote no image")


async def capture(html: str) -> Screenshots:
    """Render `html` at each viewport and return the PNG bytes.

    A blank or partial capture is returned as-is rather than judged here: the page's own
    script failing is something the critic reports as a `broken_render` finding, and this
    module has no opinion about what a good page looks like.
    """
    binary = chromium_path()
    if binary is None:
        return Screenshots.missing(
            "no chromium binary found (PUPPETEER_EXECUTABLE_PATH unset or absent)"
        )

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        page = workspace / "index.html"
        page.write_text(html, encoding="utf-8")

        images, widths = [], []
        for width, height in VIEWPORTS:
            out = workspace / f"{width}.png"
            try:
                await _shoot(binary, page, out, width, height)
            except (OSError, RuntimeError) as exc:
                logger.warning("screenshot at %dpx unavailable: %s", width, exc)
                return Screenshots.missing(f"render at {width}px failed: {exc}")
            images.append(out.read_bytes())
            widths.append(width)

    return Screenshots(images=tuple(images), widths=tuple(widths))
