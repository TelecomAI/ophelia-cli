from src.events import MessageDisplay, Stop
from src.listeners import ListenerRegistry
from src.listeners.ui_listeners import register_ui_listeners


async def test_dispatch_with_no_listeners_returns_empty_list():
    assert await ListenerRegistry().dispatch(Stop(text="done")) == []


async def test_dispatch_calls_listeners_for_matching_type_in_order():
    registry = ListenerRegistry()
    calls: list[str] = []

    async def first(event: Stop) -> str:
        calls.append("first")
        return "a"

    async def second(event: Stop) -> str:
        calls.append("second")
        return "b"

    registry.register(Stop, first)
    registry.register(Stop, second)

    results = await registry.dispatch(Stop(text="done"))

    assert calls == ["first", "second"]
    assert results == ["a", "b"]


async def test_dispatch_ignores_listeners_for_other_types():
    registry = ListenerRegistry()
    calls: list[object] = []

    async def on_stop(event: Stop) -> None:
        calls.append(event)

    registry.register(Stop, on_stop)

    await registry.dispatch(MessageDisplay(text="hi"))

    assert calls == []


async def test_register_ui_listeners_registers_every_event_type():
    registry = ListenerRegistry()

    register_ui_listeners(registry)

    # Stubs return None, so each dispatch yields exactly one (None) result.
    assert await registry.dispatch(Stop(text="done")) == [None]
    assert await registry.dispatch(MessageDisplay(text="hi")) == [None]
