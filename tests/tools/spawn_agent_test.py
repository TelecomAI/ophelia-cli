"""Unit tests for the ``spawn_agent`` tool schema and helpers."""

import json
from types import MappingProxyType
from typing import Any

import pytest

from src.tools.spawn_agent import (
    DEFAULT_EFFORT,
    SCHEMA,
    VALID_EFFORTS,
    get_subagent_tools,
    validate_spawn_agent_args,
)


def test_schema_contract() -> None:
    """Verify SCHEMA follows the OpenAI/LiteLLM function format with `task` and `effort`."""
    assert SCHEMA["type"] == "function"
    fn = SCHEMA["function"]
    assert fn["name"] == "spawn_agent"
    assert isinstance(fn["description"], str) and fn["description"].strip()

    params = fn["parameters"]
    assert params["type"] == "object"
    assert params["required"] == ["task"]
    assert set(params["properties"].keys()) == {"task", "effort"}

    task_prop = params["properties"]["task"]
    assert task_prop["type"] == "string"
    assert isinstance(task_prop["description"], str) and task_prop["description"].strip()

    effort_prop = params["properties"]["effort"]
    assert effort_prop["type"] == "string"
    assert effort_prop["enum"] == ["low", "medium", "high"]
    assert effort_prop["enum"] == list(VALID_EFFORTS)
    assert effort_prop["default"] == "medium"
    assert effort_prop["default"] == DEFAULT_EFFORT
    assert isinstance(effort_prop["description"], str) and effort_prop["description"].strip()


def test_schema_is_json_serializable() -> None:
    """Verify SCHEMA round-trips cleanly through JSON for LLM provider payloads."""
    serialized = json.dumps(SCHEMA)
    assert json.loads(serialized) == SCHEMA


def test_validate_args_with_defaults() -> None:
    """Verify valid `task` uses DEFAULT_EFFORT ('medium') when `effort` is omitted or None."""
    assert validate_spawn_agent_args("Inspect src/cli.py") == ("Inspect src/cli.py", "medium")
    assert validate_spawn_agent_args("Inspect src/cli.py", None) == (
        "Inspect src/cli.py",
        "medium",
    )
    assert validate_spawn_agent_args("Inspect src/cli.py", effort=None) == (
        "Inspect src/cli.py",
        "medium",
    )


@pytest.mark.parametrize(
    ("raw_json", "expected"),
    [
        ('{"task": "Find usages of SCHEMA"}', ("Find usages of SCHEMA", "medium")),
        (
            '{"task": "Audit error handling", "effort": "high"}',
            ("Audit error handling", "high"),
        ),
        ('{"task": "Quick check", "effort": null}', ("Quick check", "medium")),
    ],
)
def test_validate_args_kwargs_unpacking_from_tool_call(
    raw_json: str,
    expected: tuple[str, str],
) -> None:
    """Verify LLM JSON tool-call argument payloads unpack cleanly into validate_spawn_agent_args."""
    payload: dict[str, Any] = json.loads(raw_json)
    assert validate_spawn_agent_args(**payload) == expected


def test_validate_args_rejects_unexpected_tool_call_kwargs() -> None:
    """Verify unknown keyword arguments in a tool-call payload raise TypeError."""
    payload: dict[str, Any] = json.loads('{"task": "Check files", "timeout": 30}')
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        validate_spawn_agent_args(**payload)


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_validate_args_with_valid_efforts(effort: str) -> None:
    """Verify each allowed effort level is accepted and returned unchanged."""
    task, normalized_effort = validate_spawn_agent_args("Summarize module structure", effort=effort)
    assert task == "Summarize module structure"
    assert normalized_effort == effort


def test_validate_args_preserves_multiline_unicode_and_whitespace_padding() -> None:
    """Verify non-blank task strings keep exact formatting, newlines, and Unicode."""
    raw_task = "  Goal: vérifiez les fichiers 🚀\n  1. Read `src/cli.py`\n  2. Report findings\n"
    task, effort = validate_spawn_agent_args(raw_task, effort="low")
    assert task == raw_task
    assert effort == "low"


@pytest.mark.parametrize(
    "bad_task",
    [None, 0, 123, 3.14, True, False, b"task", ["task"], ("task",), {"task": "x"}],
)
def test_validate_args_invalid_task_type(bad_task: Any) -> None:
    """Verify non-string `task` values raise TypeError."""
    with pytest.raises(TypeError, match="task must be a string"):
        validate_spawn_agent_args(bad_task)  # type: ignore[arg-type]


@pytest.mark.parametrize("blank_task", ["", " ", "   ", "\t", "\n", "\r\n", "  \t\n  "])
def test_validate_args_empty_or_blank_task(blank_task: str) -> None:
    """Verify empty or whitespace-only `task` values raise ValueError."""
    with pytest.raises(ValueError, match="task cannot be empty"):
        validate_spawn_agent_args(blank_task)


@pytest.mark.parametrize(
    "bad_effort",
    [0, 1, 1.5, True, False, b"medium", ["medium"], ("medium",), {"effort": "medium"}],
)
def test_validate_args_invalid_effort_type(bad_effort: Any) -> None:
    """Verify non-string `effort` values (other than None) raise TypeError."""
    with pytest.raises(TypeError, match="effort must be a string"):
        validate_spawn_agent_args("Valid task", effort=bad_effort)


@pytest.mark.parametrize(
    "bad_effort",
    [
        "",
        " ",
        "LOW",
        "MEDIUM",
        "High",
        " medium",
        "medium ",
        "medium\n",
        "minimal",
        "max",
        "none",
        "null",
    ],
)
def test_validate_args_invalid_effort_value(bad_effort: str) -> None:
    """Verify unsupported `effort` strings raise ValueError (strict case and whitespace)."""
    with pytest.raises(ValueError, match="effort must be one of"):
        validate_spawn_agent_args("Valid task", effort=bad_effort)


def test_validate_args_validates_task_before_effort() -> None:
    """Verify `task` errors take precedence when both `task` and `effort` are invalid."""
    with pytest.raises(TypeError, match="task must be a string"):
        validate_spawn_agent_args(123, effort=456)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="task cannot be empty"):
        validate_spawn_agent_args("   ", effort="invalid")


def test_get_subagent_tools_strips_spawn_agent_without_mutating_input() -> None:
    """Verify `spawn_agent` is removed, other tools remain intact, and parent dict is isolated."""
    read_entry = {"function": object(), "schema": {"name": "read_file"}}
    bash_entry = {"function": object(), "schema": {"name": "run_bash"}}
    spawn_entry = {"function": None, "schema": SCHEMA}
    parent_tools = {
        "read_file": read_entry,
        "spawn_agent": spawn_entry,
        "run_bash": bash_entry,
    }

    sub_tools = get_subagent_tools(parent_tools)

    assert "spawn_agent" not in sub_tools
    assert list(sub_tools.keys()) == ["read_file", "run_bash"]
    assert sub_tools["read_file"] is read_entry
    assert sub_tools["run_bash"] is bash_entry

    # Parent mapping is untouched
    assert "spawn_agent" in parent_tools
    assert len(parent_tools) == 3

    # Mutating returned dict does not affect parent_tools
    sub_tools["extra_tool"] = {"function": None, "schema": {}}
    del sub_tools["read_file"]
    assert "extra_tool" not in parent_tools
    assert "read_file" in parent_tools


def test_get_subagent_tools_when_only_spawn_agent_present() -> None:
    """Verify a toolset containing only `spawn_agent` filters down to an empty dict."""
    parent_tools = {"spawn_agent": {"function": None, "schema": SCHEMA}}
    sub_tools = get_subagent_tools(parent_tools)

    assert sub_tools == {}
    assert "spawn_agent" in parent_tools


def test_get_subagent_tools_when_spawn_agent_absent_or_empty() -> None:
    """Verify filtering returns a new shallow copy when `spawn_agent` is absent or dict is empty."""
    tools_without_spawn = {"read_file": object(), "write_file": object()}
    copied = get_subagent_tools(tools_without_spawn)
    assert copied == tools_without_spawn
    assert copied is not tools_without_spawn

    empty: dict[str, Any] = {}
    empty_copy = get_subagent_tools(empty)
    assert empty_copy == {}
    assert empty_copy is not empty


def test_get_subagent_tools_preserves_similarly_named_tools() -> None:
    """Verify only exact `'spawn_agent'` key is removed, not prefix/case variants."""
    tools = {
        "spawn_agent": object(),
        "spawn_agent_v2": object(),
        "SPAWN_AGENT": object(),
    }
    sub_tools = get_subagent_tools(tools)
    assert set(sub_tools.keys()) == {"spawn_agent_v2", "SPAWN_AGENT"}


def test_get_subagent_tools_accepts_readonly_mapping_proxy() -> None:
    """Verify read-only Mapping implementations are accepted and return a plain dict."""
    readonly_tools = MappingProxyType(
        {
            "read_file": "reader",
            "spawn_agent": "spawner",
        }
    )
    sub_tools = get_subagent_tools(readonly_tools)

    assert isinstance(sub_tools, dict)
    assert sub_tools == {"read_file": "reader"}


@pytest.mark.parametrize(
    "bad_tools",
    [None, 0, 42, True, "spawn_agent", ["read_file"], ("read_file",), {"read_file"}],
)
def test_get_subagent_tools_invalid_input_type(bad_tools: Any) -> None:
    """Verify non-mapping `tools` inputs raise TypeError."""
    with pytest.raises(TypeError, match="tools must be a mapping"):
        get_subagent_tools(bad_tools)
