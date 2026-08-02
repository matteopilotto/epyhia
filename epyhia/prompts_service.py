import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_VERSION_RE = re.compile(r"^v(\d+)$")


class PromptNotFound(Exception):
    """Raised by `render()` for a template that does not exist. `active_version()` never
    raises this — 1-based versioning starts at v1 whether or not the file exists yet."""


class PromptService:
    """Renders `prompts/<agent>/<version>.jinja` (research.md "Prompts"). No prompt text
    exists as a string literal in source — every agent's instructions live in this
    versioned tree so CI can grep the rendered output for client data (FR-060)."""

    def __init__(self, prompts_dir: Path = PROMPTS_DIR) -> None:
        self._dir = prompts_dir
        self._env = Environment(
            loader=FileSystemLoader(str(prompts_dir)),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )

    def active_version(self, agent: str) -> str:
        """The highest version number on disk for `agent`, or `v1` before anything has
        been authored — there is no separate pointer to keep in sync, so a run opened
        before an agent's prompt exists still gets a coherent, single-sourced tag."""
        versions = self._versions(agent)
        return f"v{max(versions)}" if versions else "v1"

    def render(self, agent: str, version: str, **context: object) -> str:
        template = self._env.get_template(f"{agent}/{version}.jinja")
        return template.render(**context)

    def _versions(self, agent: str) -> list[int]:
        agent_dir = self._dir / agent
        if not agent_dir.is_dir():
            return []
        found = []
        for path in agent_dir.glob("v*.jinja"):
            match = _VERSION_RE.match(path.stem)
            if match:
                found.append(int(match.group(1)))
        return found


prompt_service = PromptService()
