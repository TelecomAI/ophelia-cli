from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PreToolUse:
    """
    emitted before the agent uses a tool
    """

    id: str
    tool_name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class PermissionRequest:
    """
    emitted when permission is requested from the user
    """

    id: str
    tool_name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class PostToolUse:
    """
    emitted after a tool is used
    """

    id: str
    tool_name: str
    result: str


@dataclass(frozen=True)
class MessageDisplay:
    """
    emitted for the ui to stream text
    """

    text: str = ""


@dataclass(frozen=True)
class ThinkingDisplay:
    """
    emitted when the agent is thinking
    """

    text: str = ""


@dataclass(frozen=True)
class SubagentStart:
    """
    emitted when a subagent starts
    """

    task: str
    effort: str = "medium"


@dataclass(frozen=True)
class SubagentStop:
    """
    emitted when a subagent stops
    """

    task: str
    result: str


@dataclass(frozen=True)
class Stop:
    """
    emitted when the agent finishes
    """

    text: str


type Event = (
    PreToolUse
    | PermissionRequest
    | PostToolUse
    | MessageDisplay
    | ThinkingDisplay
    | SubagentStart
    | SubagentStop
    | Stop
)
