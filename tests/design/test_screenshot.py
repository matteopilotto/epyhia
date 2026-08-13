import asyncio
import shutil
from pathlib import Path

import pytest

from epyhia.design import screenshot
from epyhia.design.screenshot import VIEWPORTS, capture

# A page shaped like the output contract and saying nothing about any business. Nothing in
# this file renders it: the browser is faked throughout, so the suite stays offline, free and
# runnable on a machine with no Chromium at all.
PAGE = "<!doctype html><html lang='en'><head><title>Specimen</title></head><body></body></html>"

PNG = b"\x89PNG\r\n\x1a\n fake"


@pytest.fixture
def no_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PUPPETEER_EXECUTABLE_PATH", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)


@pytest.fixture
def binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUPPETEER_EXECUTABLE_PATH", "/usr/bin/chromium")
    monkeypatch.setattr(shutil, "which", lambda name: name)


class _Process:
    """Enough of `asyncio.subprocess.Process` for the two failure modes and the success."""

    def __init__(self, *, returncode: int = 0, writes: bytes | None = None, hangs: bool = False):
        self.returncode = returncode
        self._writes = writes
        self._hangs = hangs
        self.killed = False
        self.out: Path | None = None

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hangs:
            await asyncio.sleep(60)
        if self._writes is not None:
            self.out.write_bytes(self._writes)
        return b"", b"chromium said no"

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode


def _chromium(monkeypatch: pytest.MonkeyPatch, process: _Process) -> list[list[str]]:
    """Stand in for the browser, recording the argv it was invoked with."""
    invocations: list[list[str]] = []

    async def spawn(*args: str, **kwargs: object) -> _Process:
        invocations.append(list(args))
        process.out = Path(
            next(arg for arg in args if arg.startswith("--screenshot=")).split("=", 1)[1]
        )
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return invocations


async def test_no_binary_is_an_unavailable_result_not_an_exception(no_binary: None) -> None:
    """The degraded path FR-015 requires the stage to survive: a developer's machine, or a
    bare CI runner, has no browser and the run must complete regardless."""
    shots = await capture(PAGE)

    assert not shots.captured
    assert shots.images == () and shots.widths == ()
    assert "chromium" in shots.unavailable


async def test_a_failed_render_reports_unavailable(
    binary: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = _Process(returncode=1)
    _chromium(monkeypatch, process)

    shots = await capture(PAGE)

    assert not shots.captured
    assert "exited 1" in shots.unavailable


async def test_a_render_that_writes_nothing_reports_unavailable(
    binary: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zero exit with no file is the shape a browser that refused the page has, and it must
    not become an empty PNG handed to the critic as a broken render."""
    _chromium(monkeypatch, _Process(returncode=0))

    shots = await capture(PAGE)

    assert not shots.captured
    assert "no image" in shots.unavailable


async def test_a_hung_render_is_killed_and_reports_unavailable(
    binary: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wall clock is the point: a browser that never returns must not hold the site
    task's lease until the sweeper takes it away."""
    monkeypatch.setattr(screenshot, "TIMEOUT_SECONDS", 0.01)
    process = _Process(hangs=True)
    _chromium(monkeypatch, process)

    shots = await capture(PAGE)

    assert not shots.captured
    assert "did not finish" in shots.unavailable
    assert process.killed


async def test_a_successful_capture_returns_one_image_per_viewport(
    binary: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    invocations = _chromium(monkeypatch, _Process(writes=PNG))

    shots = await capture(PAGE)

    assert shots.captured
    assert shots.images == (PNG,) * len(VIEWPORTS)
    assert shots.widths == tuple(width for width, _ in VIEWPORTS)
    assert [
        next(arg for arg in argv if arg.startswith("--window-size=")) for argv in invocations
    ] == [f"--window-size={width},{height}" for width, height in VIEWPORTS]
    # The page is rendered from a file, so the capture reaches no network and no server.
    assert all(argv[-1].startswith("file://") for argv in invocations)
