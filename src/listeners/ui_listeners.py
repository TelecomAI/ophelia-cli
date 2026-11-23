"""UI listeners for agent events. Bodies are placeholders until the UI is implemented (issue #9)."""

from src.events import (
    MessageDisplay,
    PermissionRequest,
    PostToolUse,
    PreToolUse,
    Stop,
    SubagentStart,
    SubagentStop,
    ThinkingDisplay,
)
from src.listeners import ListenerRegistry


async def on_thinking(event: ThinkingDisplay) -> None:
    """Render a thinking update."""


async def on_message(event: MessageDisplay) -> None:
    """Stream a message chunk to the user."""


async def on_pre_tool_use(event: PreToolUse) -> None:
    """Show that a tool is about to run."""


async def on_permission_request(event: PermissionRequest) -> bool:
    """Ask the user to approve a tool call. Returns True if approved."""


async def on_post_tool_use(event: PostToolUse) -> None:
    """Show the result of a tool call."""


async def on_stop(event: Stop) -> None:
    """Show that the agent has finished."""


async def on_subagent_start(event: SubagentStart) -> None:
    """Show that a subagent has started."""


async def on_subagent_stop(event: SubagentStop) -> None:
    """Show that a subagent has finished."""


def register_ui_listeners(registry: ListenerRegistry) -> None:
    """Register every UI listener on the registry, keyed by event type."""
    registry.register(ThinkingDisplay, on_thinking)
    registry.register(MessageDisplay, on_message)
    registry.register(PreToolUse, on_pre_tool_use)
    registry.register(PermissionRequest, on_permission_request)
    registry.register(PostToolUse, on_post_tool_use)
    registry.register(Stop, on_stop)
    registry.register(SubagentStart, on_subagent_start)
    registry.register(SubagentStop, on_subagent_stop)
