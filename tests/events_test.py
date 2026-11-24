from src.events import EventHandler, MessageDisplay, PermissionRequest, PostToolUse, PreToolUse
from src.listeners import ListenerRegistry
from src.tools import PermissionPolicy, ToolRegistry


def _schema(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "parameters": {}}}


async def _echo(text: str) -> str:
    return f"echo: {text}"


def _handler(
    permission_for: list[str] | None = None,
) -> tuple[EventHandler, ListenerRegistry]:
    tools = ToolRegistry(PermissionPolicy(permission_for or []))
    tools.register(_schema("echo"), _echo)
    listeners = ListenerRegistry()
    return EventHandler(tools, listeners), listeners


# --- PermissionRequest ---


async def test_permission_request_returns_true_without_asking_when_not_required():
    handler, listeners = _handler(permission_for=[])
    asked: list[object] = []

    async def on_permission_request(event: PermissionRequest) -> bool:
        asked.append(event)
        return False

    listeners.register(PermissionRequest, on_permission_request)

    result = await handler.process(
        PermissionRequest(id="call_1", tool_name="echo", args={"text": "hi"})
    )

    assert result == [True]
    assert asked == []


async def test_permission_request_returns_listener_approval():
    handler, listeners = _handler(permission_for=["echo"])

    async def approve(event: PermissionRequest) -> bool:
        return True

    listeners.register(PermissionRequest, approve)

    result = await handler.process(
        PermissionRequest(id="call_1", tool_name="echo", args={"text": "hi"})
    )

    assert result == [True]


async def test_permission_request_returns_listener_refusal():
    handler, listeners = _handler(permission_for=["echo"])

    async def refuse(event: PermissionRequest) -> bool:
        return False

    listeners.register(PermissionRequest, refuse)

    result = await handler.process(
        PermissionRequest(id="call_1", tool_name="echo", args={"text": "hi"})
    )

    assert result == [False]


async def test_permission_request_returns_none_when_no_listener_is_registered():
    handler, _ = _handler(permission_for=["echo"])

    result = await handler.process(
        PermissionRequest(id="call_1", tool_name="echo", args={"text": "hi"})
    )

    assert result is None


async def test_permission_request_returns_none_when_listener_returns_none():
    handler, listeners = _handler(permission_for=["echo"])

    async def unimplemented(event: PermissionRequest) -> None:
        return None

    listeners.register(PermissionRequest, unimplemented)

    result = await handler.process(
        PermissionRequest(id="call_1", tool_name="echo", args={"text": "hi"})
    )

    assert result is None


# --- PreToolUse ---


async def test_pre_tool_use_runs_tool_and_returns_its_result():
    handler, _ = _handler()

    result = await handler.process(PreToolUse(id="call_2", tool_name="echo", args={"text": "hi"}))

    assert result == ["echo: hi"]


async def test_pre_tool_use_notifies_listeners_before_running_tool():
    handler, listeners = _handler()
    order: list[str] = []

    async def on_pre_tool_use(event: PreToolUse) -> None:
        order.append("listener")

    async def echo_spy(text: str) -> str:
        order.append("tool")
        return text

    listeners.register(PreToolUse, on_pre_tool_use)
    handler.tool_registry.register(_schema("spy"), echo_spy)

    await handler.process(PreToolUse(id="call_3", tool_name="spy", args={"text": "hi"}))

    assert order == ["listener", "tool"]


async def test_pre_tool_use_returns_error_string_for_unknown_tool():
    handler, _ = _handler()

    result = await handler.process(PreToolUse(id="call_4", tool_name="missing", args={}))

    assert result == ["Error: unknown tool 'missing'"]


# --- Other events ---


async def test_other_event_returns_listener_results():
    handler, listeners = _handler()

    async def on_message(event: MessageDisplay) -> str:
        return "shown"

    listeners.register(MessageDisplay, on_message)

    result = await handler.process(MessageDisplay(text="hi"))

    assert result == ["shown"]


async def test_other_event_returns_none_when_all_listeners_return_none():
    handler, listeners = _handler()

    async def on_message(event: MessageDisplay) -> None:
        return None

    listeners.register(MessageDisplay, on_message)

    assert await handler.process(MessageDisplay(text="hi")) is None


async def test_other_event_returns_none_when_no_listener_is_registered():
    handler, _ = _handler()

    assert await handler.process(PostToolUse(id="call_5", tool_name="echo", result="x")) is None
