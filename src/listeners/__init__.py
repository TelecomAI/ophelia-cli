"""Registry that routes each event to the listeners registered for its type."""

from collections.abc import Awaitable, Callable
from typing import Any

ListenerFunc = Callable[[Any], Awaitable[Any]]


class ListenerRegistry:
    """Maps event types to async listeners and dispatches events to them."""

    def __init__(self) -> None:
        self._listeners: dict[type, list[ListenerFunc]] = {}

    def register(self, event_type: type, listener: ListenerFunc) -> None:
        """Register a listener for an event type.

        Args:
            event_type (type): The event class the listener handles.
            listener (ListenerFunc): Async callable that receives the event.
        """
        self._listeners.setdefault(event_type, []).append(listener)

    async def dispatch(self, event: object) -> list[Any]:
        """Run every listener registered for the event's type, in registration order.

        Args:
            event (object): The event to dispatch.

        Returns:
            list[Any]: The return value of each listener, in order. Empty if none are registered.
        """
        return [await listener(event) for listener in self._listeners.get(type(event), [])]
