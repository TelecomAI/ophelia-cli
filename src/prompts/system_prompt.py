"""Build the system prompt that tells Ophelia's agent how to behave.

The prompt is assembled from three parts, always in this order:

1. The main instructions in ``system_prompt.md``. They never change while Ophelia runs.
2. Guidelines for each tool the agent really has, from ``tools/<tool_name>.md``.
3. An Environment section (working directory, operating system, shell, date),
   built when Ophelia starts.

The order matters. LLM providers such as Groq reuse a cached prompt only when its
beginning matches exactly, so the parts that never change come first and the details
that change come last. Tool guidelines are added only for tools the agent can call,
so the prompt never describes a tool that doesn't exist.

See ``docs/system-prompt.md`` for the reasoning behind the prompt's content.
"""

import datetime
import os
import platform
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from src.tools import run_bash as run_bash_tool

PROMPT_DIR = Path(__file__).parent
TOOL_GUIDELINES_DIR = PROMPT_DIR / "tools"

# Tool names are used as file names, so only accept plain snake_case names.
# This stops a name like "../secrets" from reading a file outside the tools folder.
_TOOL_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*")

SYSTEM_PROMPT: str = (PROMPT_DIR / "system_prompt.md").read_text(encoding="utf-8").strip()
"""The main instructions only, without tool guidelines or the Environment section.

Agents should use ``build_system_prompt`` instead, which adds both.
"""


@dataclass(frozen=True)
class Environment:
    """Facts about the user's machine that the model can't know on its own."""

    working_directory: str
    operating_system: str
    shell: str
    date: str

    @classmethod
    def detect(cls) -> Self:
        """Describe the machine Ophelia is running on right now."""
        return cls(
            working_directory=str(Path.cwd()),
            operating_system=f"{platform.system()} {platform.release()}".strip(),
            shell=default_shell(),
            date=datetime.date.today().isoformat(),
        )

    def render(self) -> str:
        """Format these facts as the last section of the system prompt."""
        return (
            "# Environment\n"
            "\n"
            f"- Working directory: {self.working_directory}\n"
            f"- Operating system: {self.operating_system}\n"
            f"- Shell for commands: {self.shell}\n"
            f"- Today's date: {self.date}"
        )


def default_shell() -> str:
    """Return the shell that the run_bash tool runs commands in.

    run_bash uses bash when it finds bash on the PATH (its ``BASH_PATH``). Otherwise
    ``asyncio.create_subprocess_shell`` falls back to the system's default shell:
    ``COMSPEC`` (usually ``cmd.exe``) on Windows, and ``/bin/sh`` everywhere else.
    Telling the model which one it gets lets it write commands that actually work, and
    reading ``BASH_PATH`` from the tool itself keeps the two from drifting apart.
    """
    if run_bash_tool.BASH_PATH:
        return run_bash_tool.BASH_PATH
    if os.name == "nt":
        return os.environ.get("COMSPEC", "cmd.exe")
    return "/bin/sh"


def tool_guidelines(tool_name: str) -> str | None:
    """Return the guidelines written for a tool, or None if it has none."""
    if not _TOOL_NAME_PATTERN.fullmatch(tool_name):
        return None
    path = TOOL_GUIDELINES_DIR / f"{tool_name}.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip()


def build_system_prompt(tool_names: Iterable[str], environment: Environment | None = None) -> str:
    """Assemble the full system prompt for an agent that has the given tools.

    Args:
        tool_names: Names of the tools the agent can call, for example ``["run_bash"]``.
            Passing the agent's tool dictionary works too, since iterating over a
            dictionary gives its keys.
        environment: Machine details to include. Detected automatically when omitted.

    Returns:
        The main instructions, then the guidelines of each tool (sorted by name, so
        the same tools always give exactly the same text), then the Environment section.
    """
    guidelines = []
    for name in sorted(set(tool_names)):
        text = tool_guidelines(name)
        if text:
            guidelines.append(text)

    sections = [SYSTEM_PROMPT]
    if guidelines:
        sections.append("# Tool guidelines\n\n" + "\n\n".join(guidelines))
    sections.append((environment or Environment.detect()).render())
    return "\n\n".join(sections)
