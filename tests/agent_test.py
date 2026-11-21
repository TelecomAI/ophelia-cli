from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from src.agent import MAX_TURNS_MESSAGE, Agent
from src.events import (
    Event,
    InvalidContentSchema,
    MessageDisplay,
    PermissionRequest,
    PostToolUse,
    PreToolUse,
    Stop,
    ThinkingDisplay,
)
from src.provider import PROVIDER_CONFIGS, Provider, StreamChunk, ToolCall


class AnswerSchema(BaseModel):
    answer: str


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent local .env or host environment variables from leaking into tests."""
    monkeypatch.setattr("src.provider.load_dotenv", lambda *_args, **_kwargs: False)
    for config in PROVIDER_CONFIGS.values():
        monkeypatch.delenv(config.env_var, raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)


async def async_iter(items: list[Any]) -> AsyncIterator[Any]:
    for item in items:
        yield item


def make_mock_provider(turns: list[list[StreamChunk]]) -> MagicMock:
    """Create a mock Provider whose stream() yields the given chunks per turn."""
    provider = MagicMock(spec=Provider)
    turn_iter = iter(turns)
    provider.stream.side_effect = lambda **_kwargs: async_iter(next(turn_iter))
    return provider


def make_litellm_chunk(
    *,
    content: str | None = None,
    reasoning_content: str | None = None,
    tool_calls: list[Any] | None = None,
    finish_reason: str | None = None,
) -> SimpleNamespace:
    delta = SimpleNamespace(
        content=content,
        reasoning_content=reasoning_content,
        tool_calls=tool_calls,
    )
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)])


async def drive_agent(
    agent: Agent,
    user_input: str,
    *,
    permission_responses: dict[str, str] | None = None,
    tool_results: dict[str, str] | None = None,
) -> list[Event]:
    """Drive Agent.run() to completion, responding to PermissionRequest and PreToolUse."""
    events: list[Event] = []
    gen = agent.run(user_input)
    pending_send: str | None = None

    while True:
        try:
            event = await gen.asend(pending_send)  # type: ignore[arg-type]
        except StopAsyncIteration:
            break
        events.append(event)
        pending_send = None

        if isinstance(event, PermissionRequest):
            pending_send = (permission_responses or {}).get(event.id, "yes")
        elif isinstance(event, PreToolUse):
            pending_send = (tool_results or {}).get(event.id, "ok")

    return events


# ---------------------------------------------------------------------------
# Agent.__init__
# ---------------------------------------------------------------------------


def test_init_sets_defaults_and_system_history() -> None:
    provider = make_mock_provider([])
    agent = Agent(provider=provider, system_prompt="You are helpful.")

    assert agent.provider is provider
    assert agent.system_prompt == "You are helpful."
    assert agent.tools == []
    assert agent.max_turns == 20
    assert agent.config is None
    assert agent.output_schema is None
    assert agent.history == [{"role": "system", "content": "You are helpful."}]


def test_init_accepts_custom_tools_and_max_turns() -> None:
    provider = make_mock_provider([])
    tools = [{"type": "function", "function": {"name": "read_file"}}]
    agent = Agent(provider=provider, system_prompt="sys", tools=tools, max_turns=5)

    assert agent.tools == tools
    assert agent.max_turns == 5


@pytest.mark.parametrize("max_turns", [0, -1, -10])
def test_init_rejects_non_positive_max_turns(max_turns: int) -> None:
    provider = make_mock_provider([])
    with pytest.raises(ValueError, match="max_turns must be at least 1"):
        Agent(provider=provider, system_prompt="sys", max_turns=max_turns)


# ---------------------------------------------------------------------------
# Agent.run — streaming, thinking, messages, history
# ---------------------------------------------------------------------------


async def test_run_streams_thinking_and_message_events_and_stops() -> None:
    chunks = [
        StreamChunk(reasoning="pondering..."),
        StreamChunk(content='{"answer": '),
        StreamChunk(content='"42"}', finish_reason="stop"),
    ]
    provider = make_mock_provider([chunks])
    agent = Agent(provider=provider, system_prompt="sys")

    events = await drive_agent(agent, "What is the answer?")

    assert events == [
        ThinkingDisplay(text="pondering..."),
        MessageDisplay(text='{"answer": '),
        MessageDisplay(text='"42"}'),
        Stop(text='{"answer": "42"}'),
    ]
    assert agent.history == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "What is the answer?"},
        {"role": "assistant", "content": '{"answer": "42"}'},
    ]
    provider.stream.assert_called_once()
    call_kwargs = provider.stream.call_args.kwargs
    assert call_kwargs["tools"] == []
    assert call_kwargs["output_schema"] is None


async def test_run_allows_plain_text_when_output_schema_is_none() -> None:
    provider = make_mock_provider([[StreamChunk(content="plain text", finish_reason="stop")]])
    agent = Agent(provider=provider, system_prompt="sys")

    events = await drive_agent(agent, "hi")

    assert events == [
        MessageDisplay(text="plain text"),
        Stop(text="plain text"),
    ]


async def test_run_validates_dict_output_schema_success_and_failure() -> None:
    schema: dict[str, Any] = {"type": "object", "properties": {"answer": {"type": "string"}}}

    valid_provider = make_mock_provider(
        [[StreamChunk(content='{"answer": "yes"}', finish_reason="stop")]]
    )
    agent = Agent(provider=valid_provider, system_prompt="sys")
    agent.output_schema = schema

    valid_events = await drive_agent(agent, "question")
    assert valid_events == [
        MessageDisplay(text='{"answer": "yes"}'),
        Stop(text='{"answer": "yes"}'),
    ]

    invalid_provider = make_mock_provider([[StreamChunk(content="not json", finish_reason="stop")]])
    agent_invalid = Agent(provider=invalid_provider, system_prompt="sys")
    agent_invalid.output_schema = schema

    invalid_events = await drive_agent(agent_invalid, "question")
    assert invalid_events == [
        MessageDisplay(text="not json"),
        InvalidContentSchema(text="Invalid JSON content"),
        Stop(text="not json"),
    ]


async def test_run_validates_basemodel_output_schema_success_and_failure() -> None:
    valid_provider = make_mock_provider(
        [[StreamChunk(content='{"answer": "yes"}', finish_reason="stop")]]
    )
    agent = Agent(provider=valid_provider, system_prompt="sys")
    agent.output_schema = AnswerSchema

    valid_events = await drive_agent(agent, "question")
    assert valid_events == [
        MessageDisplay(text='{"answer": "yes"}'),
        Stop(text='{"answer": "yes"}'),
    ]

    invalid_provider = make_mock_provider(
        [[StreamChunk(content='{"wrong_field": 123}', finish_reason="stop")]]
    )
    agent_invalid = Agent(provider=invalid_provider, system_prompt="sys")
    agent_invalid.output_schema = AnswerSchema

    invalid_events = await drive_agent(agent_invalid, "question")
    assert invalid_events == [
        MessageDisplay(text='{"wrong_field": 123}'),
        InvalidContentSchema(text="Invalid JSON content"),
        Stop(text='{"wrong_field": 123}'),
    ]


# ---------------------------------------------------------------------------
# Agent.run — regular tool calls & permissions
# ---------------------------------------------------------------------------


async def test_run_executes_tool_call_and_continues_next_turn() -> None:
    tool_call = ToolCall(id="call_1", name="read_file", arguments={"path": "README.md"})
    turns = [
        [StreamChunk(content="", tool_calls=[tool_call], finish_reason="tool_calls")],
        [StreamChunk(content='{"done": true}', finish_reason="stop")],
    ]
    provider = make_mock_provider(turns)
    agent = Agent(provider=provider, system_prompt="sys")

    events = await drive_agent(
        agent,
        "Read README",
        tool_results={"call_1": "file contents"},
    )

    assert events == [
        PreToolUse(id="call_1", tool_name="read_file", args={"path": "README.md"}),
        PostToolUse(id="call_1", tool_name="read_file", result="file contents"),
        MessageDisplay(text='{"done": true}'),
        Stop(text='{"done": true}'),
    ]
    assert agent.history == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "Read README"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": json.dumps({"path": "README.md"}),
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "file contents"},
        {"role": "assistant", "content": '{"done": true}'},
    ]


async def test_run_permission_approved_and_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    call_approved = ToolCall(id="c1", name="write_file", arguments={"path": "a.txt"})
    call_denied = ToolCall(id="c2", name="run_bash", arguments={"command": "rm -rf /"})
    turns = [
        [
            StreamChunk(
                content='{"step": 1}',
                tool_calls=[call_approved, call_denied],
                finish_reason="tool_calls",
            )
        ],
        [StreamChunk(content='{"done": true}', finish_reason="stop")],
    ]
    provider = make_mock_provider(turns)
    agent = Agent(provider=provider, system_prompt="sys")
    config = MagicMock()
    config.require_permission.side_effect = lambda name: name in {"write_file", "run_bash"}
    monkeypatch.setattr(agent, "config", config)

    events = await drive_agent(
        agent,
        "Do both",
        permission_responses={"c1": "yes", "c2": ""},
        tool_results={"c1": "written"},
    )

    assert events == [
        MessageDisplay(text='{"step": 1}'),
        PermissionRequest(id="c1", tool_name="write_file", args={"path": "a.txt"}),
        PreToolUse(id="c1", tool_name="write_file", args={"path": "a.txt"}),
        PostToolUse(id="c1", tool_name="write_file", result="written"),
        PermissionRequest(id="c2", tool_name="run_bash", args={"command": "rm -rf /"}),
        PostToolUse(id="c2", tool_name="run_bash", result="Tool call denied by user"),
        MessageDisplay(text='{"done": true}'),
        Stop(text='{"done": true}'),
    ]
    tool_messages = [m for m in agent.history if m["role"] == "tool"]
    assert tool_messages == [
        {"role": "tool", "tool_call_id": "c1", "content": "written"},
        {"role": "tool", "tool_call_id": "c2", "content": "Tool call denied by user"},
    ]


async def test_run_skips_permission_request_when_config_does_not_require_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_call = ToolCall(id="c1", name="read_file", arguments={"path": "x.py"})
    turns = [
        [StreamChunk(content='{"ok": 1}', tool_calls=[tool_call], finish_reason="tool_calls")],
        [StreamChunk(content='{"ok": 2}', finish_reason="stop")],
    ]
    provider = make_mock_provider(turns)
    agent = Agent(provider=provider, system_prompt="sys")
    config = MagicMock()
    config.require_permission.return_value = False
    monkeypatch.setattr(agent, "config", config)

    events = await drive_agent(agent, "Read", tool_results={"c1": "data"})

    assert not any(isinstance(e, PermissionRequest) for e in events)
    assert PreToolUse(id="c1", tool_name="read_file", args={"path": "x.py"}) in events
    config.require_permission.assert_called_once_with("read_file")


# ---------------------------------------------------------------------------
# Agent.run — max_turns limit
# ---------------------------------------------------------------------------


async def test_run_stops_at_max_turns_when_tool_calls_continue() -> None:
    tool_call_1 = ToolCall(id="c1", name="read_file", arguments={"path": "1.txt"})
    tool_call_2 = ToolCall(id="c2", name="read_file", arguments={"path": "2.txt"})
    turns = [
        [StreamChunk(content='{"t": 1}', tool_calls=[tool_call_1], finish_reason="tool_calls")],
        [StreamChunk(content='{"t": 2}', tool_calls=[tool_call_2], finish_reason="tool_calls")],
    ]
    provider = make_mock_provider(turns)
    agent = Agent(provider=provider, system_prompt="sys", max_turns=2)

    events = await drive_agent(agent, "Loop", tool_results={"c1": "r1", "c2": "r2"})

    assert events[-1] == Stop(text=MAX_TURNS_MESSAGE.format(max_turns=2))
    assert provider.stream.call_count == 2


# ---------------------------------------------------------------------------
# End-to-end with real Provider and mocked litellm.acompletion
# ---------------------------------------------------------------------------


async def test_run_with_real_provider_and_mocked_litellm() -> None:
    provider = Provider(api_key="sk-proj-test")
    agent = Agent(provider=provider, system_prompt="You are a test assistant.")
    agent.output_schema = AnswerSchema

    stream_chunks = [
        make_litellm_chunk(reasoning_content="thinking"),
        make_litellm_chunk(content='{"answer": '),
        make_litellm_chunk(content='"hello"}', finish_reason="stop"),
    ]

    with patch("src.provider.acompletion", return_value=async_iter(stream_chunks)) as mock_acomp:
        events = await drive_agent(agent, "Say hello")

    mock_acomp.assert_awaited_once()
    assert events == [
        ThinkingDisplay(text="thinking"),
        MessageDisplay(text='{"answer": '),
        MessageDisplay(text='"hello"}'),
        Stop(text='{"answer": "hello"}'),
    ]
