"""Schema and helper utilities for the ``spawn_agent`` tool.

Actual sub-agent instantiation and concurrent execution happen inside
``Agent._run_subagents()`` (Issue #11).
"""

from collections.abc import Mapping
from typing import Any

VALID_EFFORTS = ("low", "medium", "high")
DEFAULT_EFFORT = "medium"

SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "spawn_agent",
        "description": (
            "Spawn a sub-agent with a fresh conversation context to handle a "
            "self-contained subtask independently and return its report. "
            "Sub-agents auto-approve tool calls and can run in parallel."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        "Complete, self-contained instructions for the sub-agent, "
                        "including the goal, relevant file paths, and what to report."
                    ),
                },
                "effort": {
                    "type": "string",
                    "enum": list(VALID_EFFORTS),
                    "default": DEFAULT_EFFORT,
                    "description": (
                        "Effort level for the sub-agent ('low', 'medium', or 'high'). "
                        "Defaults to 'medium'."
                    ),
                },
            },
            "required": ["task"],
        },
    },
}


def validate_spawn_agent_args(
    task: str,
    effort: str | None = DEFAULT_EFFORT,
) -> tuple[str, str]:
    """Validate and normalize arguments passed to ``spawn_agent``.

    Args:
        task: Complete, self-contained instructions for the sub-agent.
        effort: Effort level for the sub-agent ('low', 'medium', or 'high').

    Returns:
        A tuple containing the validated task and normalized effort.

    Raises:
        TypeError: If task is not a string or effort is not a string.
        ValueError: If task is empty or whitespace-only, or effort is not in VALID_EFFORTS.
    """
    if not isinstance(task, str):
        raise TypeError("task must be a string")
    if not task.strip():
        raise ValueError("task cannot be empty or whitespace-only")

    if effort is None:
        effort = DEFAULT_EFFORT
    if not isinstance(effort, str):
        raise TypeError("effort must be a string")
    if effort not in VALID_EFFORTS:
        raise ValueError(f"effort must be one of {VALID_EFFORTS}")

    return task, effort


def get_subagent_tools(tools: Mapping[str, Any]) -> dict[str, Any]:
    """Build the tool mapping for a child sub-agent without ``spawn_agent``.

    Args:
        tools: A mapping of tool names to tool implementations.

    Returns:
        A new dictionary containing all entries from ``tools`` except ``"spawn_agent"``.

    Raises:
        TypeError: If ``tools`` is not a mapping.
    """
    if not isinstance(tools, Mapping):
        raise TypeError("tools must be a mapping")
    return {k: v for k, v in tools.items() if k != "spawn_agent"}
