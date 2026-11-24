from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from src.agent import MAX_TURNS_MESSAGE, SUBAGENT_TOOL_ERROR, Agent, _tool_schema_name
from src.events import (
    Event,
    InvalidContentSchema,
    MessageDisplay,
    PermissionRequest,
    PostToolUse,
    PreToolUse,
    Stop,
    SubagentStart,
    SubagentStop,
    ThinkingDisplay,
)
from src.prompts import SYSTEM_PROMPT
from src.provider import PROVIDER_CONFIGS, Provider, ProviderResponse, StreamChunk, ToolCall
from src.tools.spawn_agent import SCHEMA as SPAWN_AGENT_SCHEMA
from src.tools.spawn_agent import VALID_EFFORTS


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


def make_complete_provider(responses: list[ProviderResponse]) -> MagicMock:
    """Create a mock Provider whose complete() returns the given responses per turn."""
    provider = MagicMock(spec=Provider)
    provider.complete.side_effect = list(responses)
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
    permission_responses: dict[str, list[Any] | None] | None = None,
    tool_results: dict[str, str] | None = None,
    effort: str | None = None,
    stream: bool = True,
) -> list[Event]:
    """Drive Agent.run() to completion, responding to PermissionRequest and PreToolUse.

    The caller answers PermissionRequest with a list ([True] approves) and PreToolUse
    with [result], like EventHandler.process does.
    """
    events: list[Event] = []
    gen = agent.run(user_input, effort=effort, stream=stream)
    pending_send: Any = None

    while True:
        try:
            event = await gen.asend(pending_send)  # type: ignore[arg-type]
        except StopAsyncIteration:
            break
        events.append(event)
        pending_send = None

        if isinstance(event, PermissionRequest):
            pending_send = (permission_responses or {}).get(event.id, [True])
        elif isinstance(event, PreToolUse):
            pending_send = [(tool_results or {}).get(event.id, "ok")]

    return events


# ---------------------------------------------------------------------------
# Agent.__init__
# ---------------------------------------------------------------------------


def test_init_sets_defaults_and_system_history() -> None:
    provider = make_mock_provider([])
    agent = Agent(provider=provider)

    assert agent.provider is provider
    assert agent.system_prompt.startswith(SYSTEM_PROMPT)
    assert agent.tools == []
    assert agent.max_turns == 20
    assert agent.effort == "medium"
    assert agent.output_schema is None
    assert agent.history == [{"role": "system", "content": agent.system_prompt}]


def test_init_accepts_custom_tools_and_max_turns() -> None:
    provider = make_mock_provider([])
    tools = [{"type": "function", "function": {"name": "read_file"}}]
    agent = Agent(provider=provider, tools=tools, max_turns=5, effort="high")

    assert agent.tools == tools
    assert agent.max_turns == 5
    assert agent.effort == "high"


@pytest.mark.parametrize("max_turns", [0, -1, -10])
def test_init_rejects_non_positive_max_turns(max_turns: int) -> None:
    provider = make_mock_provider([])
    with pytest.raises(ValueError, match="max_turns must be at least 1"):
        Agent(provider=provider, max_turns=max_turns)


@pytest.mark.parametrize("effort", ["", "LOW", "High", "max", "none"])
def test_init_rejects_invalid_effort(effort: str) -> None:
    provider = make_mock_provider([])
    with pytest.raises(ValueError, match="effort must be one of"):
        Agent(provider=provider, effort=effort)


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
    agent = Agent(provider=provider)

    events = await drive_agent(agent, "What is the answer?")

    assert events == [
        ThinkingDisplay(text="pondering..."),
        MessageDisplay(text='{"answer": '),
        MessageDisplay(text='"42"}'),
        Stop(text='{"answer": "42"}'),
    ]
    assert agent.history == [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": "What is the answer?"},
        {"role": "assistant", "content": '{"answer": "42"}'},
    ]
    provider.stream.assert_called_once()
    call_kwargs = provider.stream.call_args.kwargs
    assert call_kwargs["tools"] == []
    assert call_kwargs["output_schema"] is None
    assert call_kwargs["reasoning_effort"] == "medium"


async def test_run_effort_override_applies_to_this_run_only() -> None:
    provider = make_mock_provider([[StreamChunk(content="ok", finish_reason="stop")]])
    agent = Agent(provider=provider, effort="low")

    await drive_agent(agent, "think hard", effort="high")

    assert provider.stream.call_args.kwargs["reasoning_effort"] == "high"
    assert agent.effort == "low"


async def test_run_rejects_invalid_effort_override() -> None:
    provider = make_mock_provider([])
    agent = Agent(provider=provider)
    gen = agent.run("hi", effort="max")

    with pytest.raises(ValueError, match="effort must be one of"):
        await gen.asend(None)

    # Validation happens before the user message is recorded or the model is called.
    assert agent.history == [{"role": "system", "content": agent.system_prompt}]
    provider.stream.assert_not_called()
    provider.complete.assert_not_called()


async def test_run_allows_plain_text_when_output_schema_is_none() -> None:
    provider = make_mock_provider([[StreamChunk(content="plain text", finish_reason="stop")]])
    agent = Agent(provider=provider)

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
    agent = Agent(provider=valid_provider)
    agent.output_schema = schema

    valid_events = await drive_agent(agent, "question")
    assert valid_events == [
        MessageDisplay(text='{"answer": "yes"}'),
        Stop(text='{"answer": "yes"}'),
    ]

    invalid_provider = make_mock_provider([[StreamChunk(content="not json", finish_reason="stop")]])
    agent_invalid = Agent(provider=invalid_provider)
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
    agent = Agent(provider=valid_provider)
    agent.output_schema = AnswerSchema

    valid_events = await drive_agent(agent, "question")
    assert valid_events == [
        MessageDisplay(text='{"answer": "yes"}'),
        Stop(text='{"answer": "yes"}'),
    ]

    invalid_provider = make_mock_provider(
        [[StreamChunk(content='{"wrong_field": 123}', finish_reason="stop")]]
    )
    agent_invalid = Agent(provider=invalid_provider)
    agent_invalid.output_schema = AnswerSchema

    invalid_events = await drive_agent(agent_invalid, "question")
    assert invalid_events == [
        MessageDisplay(text='{"wrong_field": 123}'),
        InvalidContentSchema(text="Invalid JSON content"),
        Stop(text='{"wrong_field": 123}'),
    ]


# ---------------------------------------------------------------------------
# Agent.run — non-streaming mode
# ---------------------------------------------------------------------------


async def test_run_non_streaming_calls_complete_once_and_emits_one_message() -> None:
    provider = make_complete_provider([ProviderResponse(content="plain text", model="m")])
    agent = Agent(provider=provider)

    events = await drive_agent(agent, "hi", stream=False)

    assert events == [
        MessageDisplay(text="plain text"),
        Stop(text="plain text"),
    ]
    provider.complete.assert_awaited_once()
    provider.stream.assert_not_called()
    call_kwargs = provider.complete.call_args.kwargs
    assert call_kwargs["tools"] == []
    assert call_kwargs["output_schema"] is None
    assert call_kwargs["reasoning_effort"] == "medium"
    assert agent.history == [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "plain text"},
    ]


async def test_run_non_streaming_handles_tool_calls_and_permissions() -> None:
    tool_call = ToolCall(id="call_1", name="read_file", arguments={"path": "README.md"})
    provider = make_complete_provider(
        [
            ProviderResponse(content="", model="m", tool_calls=[tool_call]),
            ProviderResponse(content="done", model="m"),
        ]
    )
    agent = Agent(provider=provider)

    events = await drive_agent(
        agent,
        "Read",
        stream=False,
        tool_results={"call_1": "file contents"},
    )

    assert events == [
        PermissionRequest(id="call_1", tool_name="read_file", args={"path": "README.md"}),
        PreToolUse(id="call_1", tool_name="read_file", args={"path": "README.md"}),
        PostToolUse(id="call_1", tool_name="read_file", result="file contents"),
        MessageDisplay(text="done"),
        Stop(text="done"),
    ]
    assert provider.complete.await_count == 2
    provider.stream.assert_not_called()
    assert {"role": "tool", "tool_call_id": "call_1", "content": "file contents"} in (agent.history)


async def test_run_non_streaming_emits_no_message_for_empty_content() -> None:
    provider = make_complete_provider([ProviderResponse(content="", model="m")])
    agent = Agent(provider=provider)

    events = await drive_agent(agent, "hi", stream=False)

    assert events == [Stop(text="")]


async def test_run_non_streaming_applies_effort_override() -> None:
    provider = make_complete_provider([ProviderResponse(content="ok", model="m")])
    agent = Agent(provider=provider, effort="low")

    await drive_agent(agent, "hi", effort="high", stream=False)

    assert provider.complete.call_args.kwargs["reasoning_effort"] == "high"
    assert agent.effort == "low"


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
    agent = Agent(provider=provider)

    events = await drive_agent(
        agent,
        "Read README",
        tool_results={"call_1": "file contents"},
    )

    assert events == [
        PermissionRequest(id="call_1", tool_name="read_file", args={"path": "README.md"}),
        PreToolUse(id="call_1", tool_name="read_file", args={"path": "README.md"}),
        PostToolUse(id="call_1", tool_name="read_file", result="file contents"),
        MessageDisplay(text='{"done": true}'),
        Stop(text='{"done": true}'),
    ]
    assert agent.history == [
        {"role": "system", "content": agent.system_prompt},
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


async def test_run_permission_approved_and_denied() -> None:
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
    agent = Agent(provider=provider)

    events = await drive_agent(
        agent,
        "Do both",
        permission_responses={"c1": [True], "c2": [False]},
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


async def test_run_always_yields_permission_request_before_pre_tool_use() -> None:
    tool_call = ToolCall(id="c1", name="read_file", arguments={"path": "x.py"})
    turns = [
        [StreamChunk(content='{"ok": 1}', tool_calls=[tool_call], finish_reason="tool_calls")],
        [StreamChunk(content='{"ok": 2}', finish_reason="stop")],
    ]
    provider = make_mock_provider(turns)
    agent = Agent(provider=provider)

    events = await drive_agent(agent, "Read", tool_results={"c1": "data"})

    permission_index = events.index(
        PermissionRequest(id="c1", tool_name="read_file", args={"path": "x.py"})
    )
    assert events[permission_index + 1] == PreToolUse(
        id="c1", tool_name="read_file", args={"path": "x.py"}
    )


async def test_run_denies_tool_when_permission_answer_is_none() -> None:
    tool_call = ToolCall(id="c1", name="write_file", arguments={"path": "a.txt"})
    turns = [
        [StreamChunk(content="", tool_calls=[tool_call], finish_reason="tool_calls")],
        [StreamChunk(content='{"done": true}', finish_reason="stop")],
    ]
    provider = make_mock_provider(turns)
    agent = Agent(provider=provider)

    events = await drive_agent(agent, "Write", permission_responses={"c1": None})

    assert not any(isinstance(e, PreToolUse) for e in events)
    assert PostToolUse(id="c1", tool_name="write_file", result="Tool call denied by user") in events


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
    agent = Agent(provider=provider, max_turns=2)

    events = await drive_agent(agent, "Loop", tool_results={"c1": "r1", "c2": "r2"})

    assert events[-1] == Stop(text=MAX_TURNS_MESSAGE.format(max_turns=2))
    assert provider.stream.call_count == 2


# ---------------------------------------------------------------------------
# Agent._run_subagents — spawn_agent tool calls
# ---------------------------------------------------------------------------


class FakeSubagent:
    """Stand-in for Agent that records its constructor args and replays canned events.

    ``script`` replaces the default single ``Stop`` event, ``fail_by_task`` makes
    ``run`` raise for a given task, and ``gate_by_task`` blocks ``run`` until the
    test releases the matching event. The autouse ``reset_fake_subagent`` fixture
    clears all class-level state between tests.
    """

    instances: ClassVar[list[FakeSubagent]] = []
    started: asyncio.Barrier | None = None
    script: ClassVar[list[Event] | None] = None
    fail_by_task: ClassVar[dict[str, BaseException]] = {}
    gate_by_task: ClassVar[dict[str, asyncio.Event]] = {}

    def __init__(
        self,
        provider: Any,
        tools: list[dict] | None = None,
        max_turns: int = 20,
        *,
        tool_executor: Any = None,
    ) -> None:
        self.provider = provider
        self.tool_executor = tool_executor
        self.tools = tools or []
        self.max_turns = max_turns
        self.run_efforts: list[str | None] = []
        self.run_stream_flags: list[bool] = []
        self.tasks: list[str] = []
        self.answers: list[Any] = []
        FakeSubagent.instances.append(self)

    async def run(
        self, user_input: str, *, effort: str | None = None, stream: bool = True
    ) -> AsyncIterator[Event]:
        self.run_efforts.append(effort)
        self.run_stream_flags.append(stream)
        self.tasks.append(user_input)

        if FakeSubagent.started is not None:
            await FakeSubagent.started.wait()
        gate = FakeSubagent.gate_by_task.get(user_input)
        if gate is not None:
            await gate.wait()

        failure = FakeSubagent.fail_by_task.get(user_input)
        if failure is not None:
            raise failure

        for event in FakeSubagent.script or [Stop(text=f"report for {user_input}")]:
            self.answers.append((yield event))


@pytest.fixture(autouse=True)
def reset_fake_subagent() -> None:
    """Clear FakeSubagent class state so scripted behaviour never leaks between tests."""
    FakeSubagent.instances = []
    FakeSubagent.started = None
    FakeSubagent.script = None
    FakeSubagent.fail_by_task = {}
    FakeSubagent.gate_by_task = {}


async def test_run_spawns_each_subagent_without_the_spawn_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = [
        ToolCall(id="s1", name="spawn_agent", arguments={"task": "Inspect a", "effort": "low"}),
        ToolCall(id="s2", name="spawn_agent", arguments={"task": "Inspect b"}),
    ]
    turns = [
        [StreamChunk(content="", tool_calls=calls, finish_reason="tool_calls")],
        [StreamChunk(content="all done", finish_reason="stop")],
    ]
    provider = make_mock_provider(turns)
    read_schema = {"type": "function", "function": {"name": "read_file"}}
    agent = Agent(
        provider=provider,
        tools=[read_schema, SPAWN_AGENT_SCHEMA],
    )

    FakeSubagent.instances = []
    # The barrier only releases once every sub-agent is running, so the test
    # hangs (and times out) if the sub-agents are not run concurrently.
    FakeSubagent.started = asyncio.Barrier(len(calls))
    monkeypatch.setattr("src.agent.Agent", FakeSubagent)

    events = await asyncio.wait_for(drive_agent(agent, "delegate"), timeout=5)

    starts = [event for event in events if isinstance(event, SubagentStart)]
    stops = [event for event in events if isinstance(event, SubagentStop)]
    assert starts == [
        SubagentStart(id="s1", task="Inspect a", effort="low"),
        SubagentStart(id="s2", task="Inspect b", effort="medium"),
    ]
    assert {stop.id: stop.result for stop in stops} == {
        "s1": "report for Inspect a",
        "s2": "report for Inspect b",
    }
    assert len(FakeSubagent.instances) == 2
    assert all(sub.provider is provider for sub in FakeSubagent.instances)
    assert all(sub.tools == [read_schema] for sub in FakeSubagent.instances)
    assert sorted(e for sub in FakeSubagent.instances for e in sub.run_efforts) == [  # type: ignore
        "low",
        "medium",
    ]
    assert [flag for sub in FakeSubagent.instances for flag in sub.run_stream_flags] == [
        False,
        False,
    ]
    assert [m for m in agent.history if m["role"] == "tool"] == [
        {"role": "tool", "tool_call_id": "s1", "content": "report for Inspect a"},
        {"role": "tool", "tool_call_id": "s2", "content": "report for Inspect b"},
    ]
    assert events[-1] == Stop(text="all done")


async def test_run_subagents_reports_invalid_arguments_without_spawning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = Agent(provider=make_mock_provider([]))

    FakeSubagent.instances = []
    FakeSubagent.started = None
    monkeypatch.setattr("src.agent.Agent", FakeSubagent)

    calls = [ToolCall(id="s1", name="spawn_agent", arguments={"task": "   "})]
    events = [event async for event in agent._run_subagents(calls)]

    assert events == [
        SubagentStop(
            id="s1",
            task="   ",
            result="Error: task cannot be empty or whitespace-only",
        )
    ]
    assert FakeSubagent.instances == []


# ---------------------------------------------------------------------------
# Agent._tool_schema_name — tool name extraction from both schema formats
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        ({"type": "function", "function": {"name": "read_file"}}, "read_file"),
        ({"name": "run_bash", "input_schema": {"type": "object"}}, "run_bash"),
        ({"function": "not-a-dict", "name": "write_file"}, "write_file"),
        ({"type": "function", "function": {"description": "nameless"}}, None),
        ({"type": "function", "function": {"name": 123}}, None),
        ({"input_schema": {"type": "object"}}, None),
        ({"type": "function", "function": None}, None),
        ({}, None),
    ],
)
def test_tool_schema_name_extracts_openai_and_anthropic_names(
    schema: dict[str, Any], expected: str | None
) -> None:
    assert _tool_schema_name(schema) == expected


# ---------------------------------------------------------------------------
# Agent._run_subagents — child tools, validation, failures, live streaming
# ---------------------------------------------------------------------------


async def test_run_subagents_with_no_calls_yields_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = Agent(provider=make_mock_provider([]))
    monkeypatch.setattr("src.agent.Agent", FakeSubagent)

    assert [event async for event in agent._run_subagents([])] == []
    assert FakeSubagent.instances == []


async def test_run_subagents_filters_child_tools_from_both_schema_formats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    openai_read = {"type": "function", "function": {"name": "read_file"}}
    anthropic_bash = {"name": "run_bash", "input_schema": {"type": "object"}}
    nameless = {"type": "function", "function": {"description": "no name"}}
    monkeypatch.setattr("src.agent.Agent", FakeSubagent)
    agent = Agent(
        provider=make_mock_provider([]),
        tools=[openai_read, anthropic_bash, nameless, SPAWN_AGENT_SCHEMA],
    )

    events = [
        event
        async for event in agent._run_subagents(
            [ToolCall(id="s1", name="spawn_agent", arguments={"task": "Inspect"})]
        )
    ]

    assert isinstance(events[-1], SubagentStop)
    assert FakeSubagent.instances[0].tools == [openai_read, anthropic_bash]


async def test_run_subagents_forwards_executor_to_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.agent.Agent", FakeSubagent)
    executor = AsyncMock(return_value="ok")
    agent = Agent(provider=make_mock_provider([]), tool_executor=executor)

    [
        event
        async for event in agent._run_subagents(
            [ToolCall(id="s1", name="spawn_agent", arguments={"task": "Inspect"})]
        )
    ]

    assert FakeSubagent.instances[0].tool_executor is executor


async def test_run_subagents_without_tools_passes_empty_tool_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.agent.Agent", FakeSubagent)
    agent = Agent(provider=make_mock_provider([]))

    events = [
        event
        async for event in agent._run_subagents(
            [ToolCall(id="s1", name="spawn_agent", arguments={"task": "Inspect"})]
        )
    ]

    assert isinstance(events[-1], SubagentStop)
    assert FakeSubagent.instances[0].tools == []


@pytest.mark.parametrize(
    ("arguments", "expected_task", "expected_result"),
    [
        ({"task": 123}, "", "Error: task must be a string"),
        (
            {"task": "Inspect", "effort": "max"},
            "Inspect",
            f"Error: effort must be one of {VALID_EFFORTS}",
        ),
    ],
)
async def test_run_subagents_rejects_invalid_spawn_arguments(
    arguments: dict[str, Any],
    expected_task: str,
    expected_result: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.agent.Agent", FakeSubagent)
    agent = Agent(provider=make_mock_provider([]))

    events = [
        event
        async for event in agent._run_subagents(
            [ToolCall(id="s1", name="spawn_agent", arguments=arguments)]
        )
    ]

    assert events == [SubagentStop(id="s1", task=expected_task, result=expected_result)]
    assert not any(isinstance(event, SubagentStart) for event in events)
    assert FakeSubagent.instances == []


async def test_run_subagents_rejects_unknown_spawn_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.agent.Agent", FakeSubagent)
    agent = Agent(provider=make_mock_provider([]))

    events = [
        event
        async for event in agent._run_subagents(
            [
                ToolCall(
                    id="s1",
                    name="spawn_agent",
                    arguments={"task": "Inspect", "timeout": 30},
                )
            ]
        )
    ]

    assert len(events) == 1
    stop = events[0]
    assert isinstance(stop, SubagentStop)
    assert stop.task == "Inspect"
    assert stop.result.startswith("Error: ")
    assert "unexpected keyword argument 'timeout'" in stop.result
    assert FakeSubagent.instances == []


async def test_run_subagents_reports_failures_alongside_successful_siblings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.agent.Agent", FakeSubagent)
    FakeSubagent.fail_by_task = {"Inspect a": RuntimeError("boom")}
    agent = Agent(provider=make_mock_provider([]))

    calls = [
        ToolCall(id="s1", name="spawn_agent", arguments={"task": "Inspect a"}),
        ToolCall(id="s2", name="spawn_agent", arguments={"task": "Inspect b", "effort": "high"}),
    ]
    events = [event async for event in agent._run_subagents(calls)]

    assert [event for event in events if isinstance(event, SubagentStart)] == [
        SubagentStart(id="s1", task="Inspect a", effort="medium"),
        SubagentStart(id="s2", task="Inspect b", effort="high"),
    ]
    assert {event.id: event.result for event in events if isinstance(event, SubagentStop)} == {
        "s1": "Error: sub-agent failed: boom",
        "s2": "report for Inspect b",
    }


async def test_run_subagents_answers_child_permission_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_args = {"path": "src/agent.py"}
    FakeSubagent.script = [
        PermissionRequest(id="c1", tool_name="read_file", args=tool_args),
        PreToolUse(id="c1", tool_name="read_file", args=tool_args),
        PostToolUse(id="c1", tool_name="read_file", result=SUBAGENT_TOOL_ERROR),
        MessageDisplay(text="partial"),
        Stop(text="child report"),
    ]
    monkeypatch.setattr("src.agent.Agent", FakeSubagent)
    agent = Agent(provider=make_mock_provider([]))

    events = [
        event
        async for event in agent._run_subagents(
            [ToolCall(id="s1", name="spawn_agent", arguments={"task": "Inspect"})]
        )
    ]

    # Child permission/tool/message events are consumed internally; only the
    # sub-agent lifecycle events reach the parent.
    assert events == [
        SubagentStart(id="s1", task="Inspect", effort="medium"),
        SubagentStop(id="s1", task="Inspect", result="child report"),
    ]
    assert FakeSubagent.instances[0].answers == [
        [True],
        [SUBAGENT_TOOL_ERROR],
        None,
        None,
    ]


async def test_run_subagents_streams_events_as_children_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()
    monkeypatch.setattr("src.agent.Agent", FakeSubagent)
    FakeSubagent.gate_by_task = {"Inspect slow": release}
    agent = Agent(provider=make_mock_provider([]))

    calls = [
        ToolCall(id="s1", name="spawn_agent", arguments={"task": "Inspect slow"}),
        ToolCall(id="s2", name="spawn_agent", arguments={"task": "Inspect fast"}),
    ]
    runner = agent._run_subagents(calls)
    try:
        first = await asyncio.wait_for(runner.__anext__(), timeout=5)
        second = await asyncio.wait_for(runner.__anext__(), timeout=5)

        assert [first, second] == [
            SubagentStart(id="s1", task="Inspect slow", effort="medium"),
            SubagentStart(id="s2", task="Inspect fast", effort="medium"),
        ]

        # The fast child reports while the slow one is still blocked, so events
        # are streamed as they happen instead of after every child finishes.
        third = await asyncio.wait_for(runner.__anext__(), timeout=5)
        assert third == SubagentStop(id="s2", task="Inspect fast", result="report for Inspect fast")

        release.set()
        fourth = await asyncio.wait_for(runner.__anext__(), timeout=5)
        assert fourth == SubagentStop(
            id="s1", task="Inspect slow", result="report for Inspect slow"
        )

        with pytest.raises(StopAsyncIteration):
            await runner.__anext__()
    finally:
        release.set()
        await runner.aclose()


# ---------------------------------------------------------------------------
# Agent._drive_subagent — child event handling with a MagicMock sub-agent
# ---------------------------------------------------------------------------


class RunnerSpy:
    """Wrap an async generator so tests can assert on ``asend()``/``aclose()``."""

    def __init__(self, inner: AsyncIterator[Event]) -> None:
        self.inner = inner
        self.asend = MagicMock(side_effect=self._asend)

        async def close() -> None:
            await inner.aclose()  # type: ignore

        self.aclose = AsyncMock(side_effect=close)

    async def _asend(self, value: Any) -> Event:
        return await self.inner.asend(value)  # type: ignore


def make_scripted_subagent(events: list[Event]) -> MagicMock:
    """Build a MagicMock sub-agent whose ``run`` replays events and records answers."""
    received: list[Any] = []
    calls: list[tuple[str, str | None, bool]] = []
    runners: list[RunnerSpy] = []

    async def scripted_run(
        task: str, *, effort: str | None = None, stream: bool = True
    ) -> AsyncIterator[Event]:
        calls.append((task, effort, stream))
        for event in events:
            received.append((yield event))

    def run(*args: Any, **kwargs: Any) -> RunnerSpy:
        runner = RunnerSpy(scripted_run(*args, **kwargs))
        runners.append(runner)
        return runner

    subagent = MagicMock(spec=Agent)
    subagent.run = MagicMock(side_effect=run)
    subagent.received = received
    subagent.calls = calls
    subagent.runners = runners
    return subagent


async def test_drive_subagent_auto_approves_and_blocks_child_tools() -> None:
    tool_args = {"path": "a.py"}
    subagent = make_scripted_subagent(
        [
            PermissionRequest(id="c1", tool_name="read_file", args=tool_args),
            PreToolUse(id="c1", tool_name="read_file", args=tool_args),
            PostToolUse(id="c1", tool_name="read_file", result=SUBAGENT_TOOL_ERROR),
            ThinkingDisplay(text="thinking"),
            MessageDisplay(text="partial"),
            Stop(text="final report"),
        ]
    )

    result = await Agent._drive_subagent(subagent, "inspect a.py", "high")

    assert result == "final report"
    assert subagent.calls == [("inspect a.py", "high", False)]
    subagent.run.assert_called_once_with("inspect a.py", effort="high", stream=False)
    # Permission is auto-approved, tool use is refused, and non-actionable
    # events (thinking/messages) get no answer.
    assert subagent.received == [[True], [SUBAGENT_TOOL_ERROR], None, None, None]
    subagent.runners[0].aclose.assert_awaited_once()


async def test_drive_subagent_runs_child_tools_through_executor() -> None:
    tool_args = {"command": "uv run kmeans.py"}
    subagent = make_scripted_subagent(
        [
            PermissionRequest(id="c1", tool_name="run_bash", args=tool_args),
            PreToolUse(id="c1", tool_name="run_bash", args=tool_args),
            PostToolUse(id="c1", tool_name="run_bash", result="Exit code: 0"),
            Stop(text="verified"),
        ]
    )
    executor = AsyncMock(return_value="Exit code: 0")

    result = await Agent._drive_subagent(subagent, "verify kmeans.py", "medium", executor)

    assert result == "verified"
    executor.assert_awaited_once_with("run_bash", tool_args)
    # Permission auto-approved, tool result forwarded, non-actionable events unanswered.
    assert subagent.received == [[True], ["Exit code: 0"], None]
    subagent.runners[0].aclose.assert_awaited_once()


async def test_drive_subagent_propagates_executor_failures() -> None:
    tool_args = {"file_path": "kmeans.py", "content": "print('hi')"}
    subagent = make_scripted_subagent(
        [
            PreToolUse(id="c1", tool_name="write_file", args=tool_args),
            Stop(text="done"),
        ]
    )
    executor = AsyncMock(side_effect=OSError("disk full"))

    # _run_subagents turns this into "Error: sub-agent failed: ...".
    with pytest.raises(OSError, match="disk full"):
        await Agent._drive_subagent(subagent, "write kmeans.py", "low", executor)


async def test_drive_subagent_returns_empty_text_when_child_ends_without_stop() -> None:
    subagent = make_scripted_subagent([MessageDisplay(text="only a message")])

    result = await Agent._drive_subagent(subagent, "task", "medium")

    assert result == ""
    assert subagent.received == [None]
    subagent.runners[0].aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# Agent.run — spawning sub-agents end to end
# ---------------------------------------------------------------------------


async def test_run_handles_regular_and_spawn_calls_in_one_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    regular = ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})
    spawn = ToolCall(id="s1", name="spawn_agent", arguments={"task": "Inspect", "effort": "high"})
    turns = [
        [StreamChunk(content="", tool_calls=[regular, spawn], finish_reason="tool_calls")],
        [StreamChunk(content="finished", finish_reason="stop")],
    ]
    monkeypatch.setattr("src.agent.Agent", FakeSubagent)
    agent = Agent(
        provider=make_mock_provider(turns),
        tools=[SPAWN_AGENT_SCHEMA],
    )

    events = await drive_agent(agent, "do both", tool_results={"c1": "data"})

    assert events == [
        PermissionRequest(id="c1", tool_name="read_file", args={"path": "a.py"}),
        PreToolUse(id="c1", tool_name="read_file", args={"path": "a.py"}),
        PostToolUse(id="c1", tool_name="read_file", result="data"),
        SubagentStart(id="s1", task="Inspect", effort="high"),
        SubagentStop(id="s1", task="Inspect", result="report for Inspect"),
        MessageDisplay(text="finished"),
        Stop(text="finished"),
    ]
    # spawn_agent never asks for permission; it is handled by the sub-agent runner.
    assert not any(
        isinstance(event, PermissionRequest) and event.tool_name == "spawn_agent"
        for event in events
    )
    assert [m for m in agent.history if m["role"] == "tool"] == [
        {"role": "tool", "tool_call_id": "c1", "content": "data"},
        {"role": "tool", "tool_call_id": "s1", "content": "report for Inspect"},
    ]


async def test_run_non_streaming_spawns_subagents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawn = ToolCall(id="s1", name="spawn_agent", arguments={"task": "Inspect"})
    provider = make_complete_provider(
        [
            ProviderResponse(content="", model="m", tool_calls=[spawn]),
            ProviderResponse(content="final", model="m"),
        ]
    )
    monkeypatch.setattr("src.agent.Agent", FakeSubagent)
    agent = Agent(provider=provider)

    events = await drive_agent(agent, "delegate", stream=False)

    assert events == [
        SubagentStart(id="s1", task="Inspect", effort="medium"),
        SubagentStop(id="s1", task="Inspect", result="report for Inspect"),
        MessageDisplay(text="final"),
        Stop(text="final"),
    ]
    assert provider.complete.await_count == 2
    provider.stream.assert_not_called()


async def test_run_with_real_subagent_isolates_history_and_forwards_effort() -> None:
    spawn = ToolCall(
        id="s1", name="spawn_agent", arguments={"task": "Inspect src", "effort": "low"}
    )
    provider = make_mock_provider(
        [
            [StreamChunk(content="", tool_calls=[spawn], finish_reason="tool_calls")],
            [StreamChunk(content="all done", finish_reason="stop")],
        ]
    )
    provider.complete.side_effect = [ProviderResponse(content="child report", model="m")]
    agent = Agent(provider=provider, tools=[SPAWN_AGENT_SCHEMA])

    events = await drive_agent(agent, "delegate")

    assert events == [
        SubagentStart(id="s1", task="Inspect src", effort="low"),
        SubagentStop(id="s1", task="Inspect src", result="child report"),
        MessageDisplay(text="all done"),
        Stop(text="all done"),
    ]
    provider.complete.assert_awaited_once()
    complete_kwargs = provider.complete.call_args.kwargs
    assert complete_kwargs["reasoning_effort"] == "low"
    assert complete_kwargs["tools"] == []
    # The provider keeps a reference to the history list, which the child keeps
    # appending to, so only the opening messages are checked here.
    assert complete_kwargs["messages"][1] == {"role": "user", "content": "Inspect src"}
    # The child builds its own prompt, so it does not inherit the parent's tool guidelines.
    assert complete_kwargs["messages"][0]["role"] == "system"
    assert complete_kwargs["messages"][0]["content"].startswith(SYSTEM_PROMPT)
    assert complete_kwargs["messages"][0]["content"] != agent.system_prompt
    # The child's turn stays in the child's own history, not the parent's.
    assert agent.history[-2:] == [
        {"role": "tool", "tool_call_id": "s1", "content": "child report"},
        {"role": "assistant", "content": "all done"},
    ]


async def test_run_falls_back_when_subagent_stop_is_missing() -> None:
    spawn = ToolCall(id="s1", name="spawn_agent", arguments={"task": "Inspect"})
    provider = make_mock_provider(
        [
            [StreamChunk(content="", tool_calls=[spawn], finish_reason="tool_calls")],
            [StreamChunk(content="done", finish_reason="stop")],
        ]
    )
    agent = Agent(provider=provider)

    async def fake_run_subagents(self: Agent, spawn_calls: list[ToolCall]) -> AsyncIterator[Event]:
        yield SubagentStart(id="other", task="x", effort="low")
        yield SubagentStop(id="other", task="x", result="y")

    with patch.object(Agent, "_run_subagents", fake_run_subagents):
        events = await drive_agent(agent, "delegate")

    assert events == [
        SubagentStart(id="other", task="x", effort="low"),
        SubagentStop(id="other", task="x", result="y"),
        MessageDisplay(text="done"),
        Stop(text="done"),
    ]
    assert [m for m in agent.history if m["role"] == "tool"] == [
        {
            "role": "tool",
            "tool_call_id": "s1",
            "content": "Error: sub-agent returned no result.",
        }
    ]


# ---------------------------------------------------------------------------
# Agent.run — additional streaming / non-streaming coverage
# ---------------------------------------------------------------------------


async def test_run_accumulates_tool_calls_across_stream_chunks() -> None:
    call_1 = ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})
    call_2 = ToolCall(id="c2", name="read_file", arguments={"path": "b.py"})
    turns = [
        [
            StreamChunk(tool_calls=[call_1]),
            StreamChunk(tool_calls=[call_2], finish_reason="tool_calls"),
        ],
        [StreamChunk(content="done", finish_reason="stop")],
    ]
    agent = Agent(provider=make_mock_provider(turns))

    events = await drive_agent(agent, "read both", tool_results={"c1": "a", "c2": "b"})

    assert events == [
        PermissionRequest(id="c1", tool_name="read_file", args={"path": "a.py"}),
        PreToolUse(id="c1", tool_name="read_file", args={"path": "a.py"}),
        PostToolUse(id="c1", tool_name="read_file", result="a"),
        PermissionRequest(id="c2", tool_name="read_file", args={"path": "b.py"}),
        PreToolUse(id="c2", tool_name="read_file", args={"path": "b.py"}),
        PostToolUse(id="c2", tool_name="read_file", result="b"),
        MessageDisplay(text="done"),
        Stop(text="done"),
    ]


async def test_run_non_streaming_validates_output_schema() -> None:
    # The mocked provider returns the payload untouched, so this exercises the
    # agent-level validation branch of the non-streaming path.
    provider = make_complete_provider([ProviderResponse(content="not json", model="m")])
    agent = Agent(provider=provider)
    agent.output_schema = AnswerSchema

    events = await drive_agent(agent, "hi", stream=False)

    assert events == [
        MessageDisplay(text="not json"),
        InvalidContentSchema(text="Invalid JSON content"),
        Stop(text="not json"),
    ]


async def test_run_with_real_provider_and_mocked_litellm() -> None:
    provider = Provider(api_key="sk-proj-test")
    agent = Agent(provider=provider)
    agent.output_schema = AnswerSchema

    stream_chunks = [
        make_litellm_chunk(reasoning_content="thinking"),
        make_litellm_chunk(content='{"answer": '),
        make_litellm_chunk(content='"hello"}', finish_reason="stop"),
    ]

    with patch("src.provider.acompletion", return_value=async_iter(stream_chunks)) as mock_acomp:
        events = await drive_agent(agent, "Say hello")

    mock_acomp.assert_awaited_once()
    assert mock_acomp.call_args.kwargs["reasoning_effort"] == "medium"
    assert events == [
        ThinkingDisplay(text="thinking"),
        MessageDisplay(text='{"answer": '),
        MessageDisplay(text='"hello"}'),
        Stop(text='{"answer": "hello"}'),
    ]


async def test_run_non_streaming_with_real_provider_and_mocked_litellm() -> None:
    provider = Provider(api_key="sk-proj-test")
    agent = Agent(provider=provider)

    message = SimpleNamespace(
        content="hello",
        tool_calls=None,
        model_dump=lambda: {"role": "assistant", "content": "hello"},
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        model="gpt-4o-mini",
        usage=None,
    )

    with patch("src.provider.acompletion", return_value=response) as mock_acomp:
        events = await drive_agent(agent, "Say hello", effort="high", stream=False)

    mock_acomp.assert_awaited_once()
    assert mock_acomp.call_args.kwargs["stream"] is False
    assert mock_acomp.call_args.kwargs["reasoning_effort"] == "high"
    assert events == [MessageDisplay(text="hello"), Stop(text="hello")]
