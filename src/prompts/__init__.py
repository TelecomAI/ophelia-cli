"""Prompts that tell Ophelia's agent how to behave."""

from .system_prompt import (
    SYSTEM_PROMPT,
    Environment,
    build_system_prompt,
    default_shell,
    tool_guidelines,
)

__all__ = [
    "SYSTEM_PROMPT",
    "Environment",
    "build_system_prompt",
    "default_shell",
    "tool_guidelines",
]
