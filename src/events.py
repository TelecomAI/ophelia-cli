from dataclasses import dataclass
from typing import Any

from src.listeners import ListenerRegistry
from src.tools import ToolRegistry


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
class InvalidContentSchema:
    """
    emitted when the content schema is invalid
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

    id: str
    task: str
    effort: str = "medium"


@dataclass(frozen=True)
class SubagentStop:
    """
    emitted when a subagent stops
    """

    id: str
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
    | InvalidContentSchema
)


class EventHandler:
    """Routes agent events to UI listeners and runs tool calls."""

    def __init__(
        self, tool_registry: ToolRegistry, listener_registry: ListenerRegistry
    ) -> None:
        """Initialize the handler.

        Args:
            tool_registry (ToolRegistry): Runs tool calls and holds the permission policy.
            listener_registry (ListenerRegistry): Dispatches events to the listeners for their type.
        """
        self.tool_registry = tool_registry
        self.listener_registry = listener_registry

    async def process(self, event: Event) -> list[Any] | None:
        """Handle one event from the agent.

        - PermissionRequest: returns [True] if the tool needs no approval. Otherwise
          returns the PermissionRequest listeners' answers, e.g. [True] or [False].
        - PreToolUse: notifies the listeners, runs the tool, and returns [result].
        - Any other event: returns the listeners' results, or None if every result is None.

        Args:
            event (Event): The event yielded by the agent.

        Returns:
            list[Any] | None: The result list described above, or None when there is nothing to report.
        """
        if isinstance(event, PermissionRequest):
            if not self.tool_registry.requires_permission(event.tool_name):
                return [True]
            return self._none_if_empty(await self.listener_registry.dispatch(event))

        if isinstance(event, PreToolUse):
            await self.listener_registry.dispatch(event)
            result = await self.tool_registry.execute(event.tool_name, event.args)
            return [result]

        return self._none_if_empty(await self.listener_registry.dispatch(event))

    @staticmethod
    def _none_if_empty(results: list[Any]) -> list[Any] | None:
        """Return None when every listener result is None, otherwise the results."""
        if all(result is None for result in results):
            return None
        return results
