import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_VERSION_RE = re.compile(r"^v(\d+)$")


class PromptNotFound(Exception):
    pass


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
        """The highest version number on disk for `agent` — there is no separate pointer
        to keep in sync, so the active version can never drift from what actually exists."""
        versions = self._versions(agent)
        if not versions:
            raise PromptNotFound(f"no prompt templates for agent: {agent}")
        return f"v{max(versions)}"

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
