import datetime
import os
import re
from pathlib import Path

import pytest

from src.prompts import (
    SYSTEM_PROMPT,
    Environment,
    build_system_prompt,
    default_shell,
    tool_guidelines,
)
from src.tools import run_bash as run_bash_tool

# The tools Ophelia has or is about to get. Each of them needs a guidelines file.
KNOWN_TOOLS = ["edit_file", "read_file", "run_bash", "spawn_agent", "write_file"]

ENVIRONMENT = Environment(
    working_directory="/home/dev/project",
    operating_system="Linux 6.8",
    shell="/bin/sh",
    date="2026-01-31",
)


def test_main_prompt_names_no_tools() -> None:
    # Tool names only enter the prompt through the guidelines of tools the agent has.
    # The old placeholder described tools that didn't exist, which invites bad calls.
    for name in KNOWN_TOOLS:
        assert name not in SYSTEM_PROMPT


def test_sections_follow_the_designed_order() -> None:
    # Models follow early instructions more reliably, so how to work comes first
    # and style comes last.
    headers = ["# How you work", "# Using your tools", "# Safety", "# Communicating"]
    positions = [SYSTEM_PROMPT.index(header) for header in headers]

    assert positions == sorted(positions)


@pytest.mark.parametrize("tool", KNOWN_TOOLS)
def test_each_known_tool_has_guidelines(tool: str) -> None:
    text = tool_guidelines(tool)

    assert text is not None
    assert text.startswith(f"## {tool}\n")


@pytest.mark.parametrize("tool", KNOWN_TOOLS)
def test_prompt_only_mentions_the_tools_it_is_given(tool: str) -> None:
    prompt = build_system_prompt([tool], ENVIRONMENT)

    assert f"## {tool}" in prompt
    for other in KNOWN_TOOLS:
        if other != tool:
            assert other not in prompt


def test_prompt_without_tools_has_no_tool_section() -> None:
    assert "# Tool guidelines" not in build_system_prompt([], ENVIRONMENT)


def test_unknown_and_unsafe_tool_names_are_ignored() -> None:
    expected = build_system_prompt(["run_bash"], ENVIRONMENT)
    prompt = build_system_prompt(["run_bash", "no_such_tool", "../system_prompt"], ENVIRONMENT)

    assert prompt == expected


def test_tool_order_and_duplicates_do_not_change_the_prompt() -> None:
    first = build_system_prompt(["write_file", "run_bash"], ENVIRONMENT)
    second = build_system_prompt(["run_bash", "write_file", "run_bash"], ENVIRONMENT)

    assert first == second


def test_accepts_the_agent_tool_dictionary() -> None:
    tools = {"run_bash": object(), "read_file": object()}

    assert build_system_prompt(tools, ENVIRONMENT) == build_system_prompt(
        ["read_file", "run_bash"], ENVIRONMENT
    )


def test_environment_section_comes_last() -> None:
    prompt = build_system_prompt(KNOWN_TOOLS, ENVIRONMENT)

    assert prompt.endswith(ENVIRONMENT.render())


def test_only_the_environment_section_changes_between_machines() -> None:
    # Providers cache the start of a prompt, so everything before the Environment
    # section has to stay identical when the machine details change.
    other = Environment("C:\\work", "Windows 11", "C:\\Windows\\system32\\cmd.exe", "2027-06-01")
    first = build_system_prompt(KNOWN_TOOLS, ENVIRONMENT)
    second = build_system_prompt(KNOWN_TOOLS, other)

    fixed_part = first.removesuffix(ENVIRONMENT.render())
    assert second == fixed_part + other.render()


def test_environment_render_lists_every_detail() -> None:
    text = ENVIRONMENT.render()

    assert text.startswith("# Environment\n")
    for value in ("/home/dev/project", "Linux 6.8", "/bin/sh", "2026-01-31"):
        assert value in text


def test_detect_describes_the_current_machine() -> None:
    environment = Environment.detect()

    assert environment.working_directory == str(Path.cwd())
    assert environment.date == datetime.date.today().isoformat()
    assert environment.shell == default_shell()
    assert environment.operating_system


def test_default_shell_is_bash_when_run_bash_finds_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_bash_tool, "BASH_PATH", "/usr/bin/bash")
    monkeypatch.setattr(run_bash_tool, "USES_WSL", False)

    assert default_shell() == "bash"


def test_default_shell_names_a_wsl_bash(monkeypatch: pytest.MonkeyPatch) -> None:
    # Under WSL the model has to use /mnt/c paths, so the label says so.
    monkeypatch.setattr(run_bash_tool, "BASH_PATH", "C:\\Windows\\System32\\bash.exe")
    monkeypatch.setattr(run_bash_tool, "USES_WSL", True)

    assert default_shell() == "bash (WSL)"


def test_default_shell_on_windows_without_bash_is_cmd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_bash_tool, "BASH_PATH", None)
    monkeypatch.setattr(os, "name", "nt")

    assert default_shell() == "cmd.exe"


def test_default_shell_elsewhere_without_bash_is_sh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_bash_tool, "BASH_PATH", None)
    monkeypatch.setattr(os, "name", "posix")

    assert default_shell() == "sh"


def test_environment_working_directory_uses_the_shell_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_bash_tool, "shell_path", lambda _path: "/mnt/c/work")

    assert Environment.detect().working_directory == "/mnt/c/work"


def test_prompt_stays_within_its_size_budget() -> None:
    # Every word is sent again on every request. The main instructions are about 500
    # words and the whole prompt about 850 with every tool, which leaves room for a few
    # more tools. Raising this limit should be a deliberate decision, not something that
    # happens one sentence at a time.
    words = len(build_system_prompt(KNOWN_TOOLS, ENVIRONMENT).split())

    assert words < 1_000


def test_prompt_uses_calm_wording() -> None:
    # Recent models over-react to shouted rules such as "CRITICAL: you MUST",
    # so the prompt states its rules plainly.
    prompt = build_system_prompt(KNOWN_TOOLS, ENVIRONMENT)

    assert not re.search(r"\b(MUST|NEVER|ALWAYS|CRITICAL|IMPORTANT)\b", prompt)
