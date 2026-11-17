from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from src.provider import (
    PROVIDER_CONFIGS,
    Provider,
    ProviderResponse,
    StreamChunk,
    ToolCall,
)


class AnswerSchema(BaseModel):
    answer: str
    confidence: float


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent local .env or host environment variables from leaking into tests."""
    monkeypatch.setattr("src.provider.load_dotenv", lambda *_args, **_kwargs: False)
    for config in PROVIDER_CONFIGS.values():
        monkeypatch.delenv(config.env_var, raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)


def make_completion_response(
    *,
    content: str | None = "hello",
    model: str = "openai/gpt-4o-mini",
    tool_calls: list[Any] | None = None,
    usage: dict[str, Any] | None = None,
    raw_message: dict[str, Any] | None = None,
) -> SimpleNamespace:
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls
    message.model_dump.return_value = raw_message or {
        "role": "assistant",
        "content": content,
    }
    return SimpleNamespace(
        model=model,
        choices=[SimpleNamespace(message=message)],
        usage=usage,
    )


def make_tool_call(call_id: str, name: str, arguments: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def make_stream_chunk(
    *,
    content: str | None = None,
    reasoning_content: str | None = None,
    tool_calls: list[Any] | None = None,
    finish_reason: str | None = None,
    empty_choices: bool = False,
    include_reasoning_attr: bool = True,
) -> SimpleNamespace:
    if empty_choices:
        return SimpleNamespace(choices=[])
    delta_kwargs: dict[str, Any] = {"content": content, "tool_calls": tool_calls}
    if include_reasoning_attr:
        delta_kwargs["reasoning_content"] = reasoning_content
    delta = SimpleNamespace(**delta_kwargs)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


async def async_iter(items: list[Any]) -> AsyncIterator[Any]:
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# detect_provider_from_key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("api_key", "expected"),
    [
        ("sk-ant-abc123", "anthropic"),
        ("sk-or-v1-abc123", "openrouter"),
        ("gsk_abc123", "groq"),
        ("AIzaSyD-abc123", "gemini"),
        ("xai-abc123", "xai"),
        ("sk-proj-abc123", "openai"),
        ("  gsk_padded  ", "groq"),
        ("unknown-prefix-123", None),
        ("", None),
        ("   ", None),
    ],
)
def test_detect_provider_from_key(api_key: str, expected: str | None) -> None:
    assert Provider.detect_provider_from_key(api_key) == expected


# ---------------------------------------------------------------------------
# Provider.__init__ & _resolve_config
# ---------------------------------------------------------------------------


def test_init_detects_provider_from_key_and_uses_default_model() -> None:
    provider = Provider(api_key="sk-ant-key", base_url="http://localhost:8000")

    assert provider.provider == "anthropic"
    assert provider.model == "anthropic/claude-sonnet-4-5"
    assert provider.api_key == "sk-ant-key"
    assert provider.base_url == "http://localhost:8000"


def test_init_reads_api_key_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "  gsk_env_key  ")
    provider = Provider()

    assert provider.provider == "groq"
    assert provider.model == "groq/openai/gpt-oss-120b"
    assert provider.api_key == "gsk_env_key"


def test_init_resolves_provider_from_model_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-secret")
    provider = Provider(model="mistral/mistral-large-latest")

    assert provider.provider == "mistral"
    assert provider.model == "mistral/mistral-large-latest"
    assert provider.api_key == "mistral-secret"


def test_init_prepends_provider_to_unprefixed_model() -> None:
    provider = Provider(api_key="sk-openai", model="gpt-4o")

    assert provider.provider == "openai"
    assert provider.model == "openai/gpt-4o"


def test_init_normalizes_whitespace_and_case_on_matching_provider_and_model() -> None:
    provider = Provider(
        api_key="  sk-123  ",
        provider="  OpenAI ",
        model=" openai/gpt-4o-mini ",
    )

    assert provider.provider == "openai"
    assert provider.model == "openai/gpt-4o-mini"
    assert provider.api_key == "sk-123"


def test_init_supports_custom_provider_with_env_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-token")
    provider = Provider(provider="ollama", model="llama3.2")

    assert provider.provider == "ollama"
    assert provider.model == "ollama/llama3.2"
    assert provider.api_key == "ollama-token"


@pytest.mark.parametrize("bad_key", ["", "   "])
def test_init_rejects_empty_api_key(bad_key: str) -> None:
    with pytest.raises(ValueError, match="api_key cannot be empty"):
        Provider(api_key=bad_key, provider="openai")


def test_init_prepends_provider_to_vendor_qualified_model_from_key() -> None:
    provider = Provider(api_key="gsk_test", model="openai/gpt-oss-20b")

    assert provider.provider == "groq"
    assert provider.model == "groq/openai/gpt-oss-20b"


def test_init_prepends_explicit_provider_to_vendor_qualified_model() -> None:
    provider = Provider(api_key="gsk_test", provider="groq", model="openai/gpt-oss-20b")

    assert provider.provider == "groq"
    assert provider.model == "groq/openai/gpt-oss-20b"


def test_init_does_not_double_prefix_provider_qualified_model() -> None:
    provider = Provider(api_key="gsk_test", provider="groq", model="groq/openai/gpt-oss-120b")

    assert provider.provider == "groq"
    assert provider.model == "groq/openai/gpt-oss-120b"


def test_init_fails_when_provider_cannot_be_determined() -> None:
    with pytest.raises(ValueError, match="Could not determine LLM provider"):
        Provider(api_key="opaque-key")


def test_init_fails_when_env_api_key_is_missing() -> None:
    with pytest.raises(ValueError, match="Missing API key for provider 'openai'"):
        Provider(provider="openai")


def test_init_fails_for_unknown_provider_without_model() -> None:
    with pytest.raises(ValueError, match="No default model configured"):
        Provider(api_key="custom-key", provider="custom")


# ---------------------------------------------------------------------------
# _build_response_format
# ---------------------------------------------------------------------------


def test_build_response_format_none() -> None:
    assert Provider._build_response_format(None) is None


def test_build_response_format_pydantic_model() -> None:
    assert Provider._build_response_format(AnswerSchema) is AnswerSchema


def test_build_response_format_preserves_wrapped_json_schema() -> None:
    wrapped = {
        "type": "json_schema",
        "json_schema": {"name": "custom", "schema": {"type": "object"}, "strict": False},
    }
    assert Provider._build_response_format(wrapped) is wrapped


def test_build_response_format_wraps_raw_schema_dict() -> None:
    raw_schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    result = Provider._build_response_format(raw_schema)

    assert result == {
        "type": "json_schema",
        "json_schema": {"name": "response", "schema": raw_schema, "strict": False},
    }


# ---------------------------------------------------------------------------
# _normalize_tools
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tools", [None, []])
def test_normalize_tools_empty_returns_none(tools: list[dict[str, Any]] | None) -> None:
    assert Provider._normalize_tools(tools) is None


def test_normalize_tools_converts_input_schema_and_keeps_openai_format() -> None:
    ophelia_tool = {
        "name": "run_bash",
        "description": "Execute a shell command",
        "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}},
    }
    no_desc_tool = {
        "name": "ping",
        "input_schema": {"type": "object", "properties": {}},
    }
    openai_tool = {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    original = [ophelia_tool, no_desc_tool, openai_tool]

    normalized = Provider._normalize_tools(original)

    assert normalized == [
        {
            "type": "function",
            "function": {
                "name": "run_bash",
                "description": "Execute a shell command",
                "parameters": ophelia_tool["input_schema"],
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ping",
                "description": "",
                "parameters": no_desc_tool["input_schema"],
            },
        },
        openai_tool,
    ]
    # Caller's input dicts must remain unmodified.
    assert "type" not in ophelia_tool


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


def test_parse_response_text_only_and_defaults() -> None:
    resp = make_completion_response(content=None, usage=None)
    parsed = Provider._parse_response(resp)

    assert parsed == ProviderResponse(
        content="",
        model="openai/gpt-4o-mini",
        tool_calls=[],
        parsed=None,
        raw_message={"role": "assistant", "content": None},
        usage={},
    )


def test_parse_response_extracts_multiple_tool_calls() -> None:
    resp = make_completion_response(
        content="",
        tool_calls=[
            make_tool_call("call_1", "run_bash", '{"command": "pwd"}'),
            make_tool_call("call_2", "ping", ""),
            make_tool_call("call_3", "noop", None),
        ],
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )

    parsed = Provider._parse_response(resp)

    assert parsed.tool_calls == [
        ToolCall(id="call_1", name="run_bash", arguments={"command": "pwd"}),
        ToolCall(id="call_2", name="ping", arguments={}),
        ToolCall(id="call_3", name="noop", arguments={}),
    ]
    assert parsed.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


def test_parse_response_validates_pydantic_schema() -> None:
    resp = make_completion_response(content='{"answer": "42", "confidence": 0.95}')
    parsed = Provider._parse_response(resp, output_schema=AnswerSchema)

    assert parsed.parsed == AnswerSchema(answer="42", confidence=0.95)


def test_parse_response_parses_dict_schema() -> None:
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    resp = make_completion_response(content='{"ok": true}')
    parsed = Provider._parse_response(resp, output_schema=schema)

    assert parsed.parsed == {"ok": True}


def test_parse_response_skips_schema_parsing_when_content_empty() -> None:
    resp = make_completion_response(
        content="",
        tool_calls=[make_tool_call("call_1", "run_bash", '{"command": "ls"}')],
    )
    parsed = Provider._parse_response(resp, output_schema=AnswerSchema)

    assert parsed.parsed is None
    assert len(parsed.tool_calls) == 1


# ---------------------------------------------------------------------------
# _build_kwargs
# ---------------------------------------------------------------------------


def test_build_kwargs_omits_unset_optional_values() -> None:
    provider = Provider(api_key="sk-test", model="openai/gpt-4o-mini")
    messages = [{"role": "user", "content": "hi"}]

    kwargs = provider._build_kwargs(messages, None, None, None, stream=False)

    assert kwargs == {
        "model": "openai/gpt-4o-mini",
        "messages": messages,
        "api_key": "sk-test",
        "stream": False,
    }


def test_build_kwargs_includes_optional_and_zero_temperature() -> None:
    provider = Provider(
        api_key="sk-test",
        model="openai/gpt-4o-mini",
        base_url="http://localhost:11434/v1",
    )
    messages = [{"role": "user", "content": "hi"}]
    tools = [{"name": "ping", "input_schema": {"type": "object"}}]

    kwargs = provider._build_kwargs(
        messages,
        AnswerSchema,
        tools,
        0.0,
        stream=False,
        max_tokens=256,
    )

    assert kwargs["base_url"] == "http://localhost:11434/v1"
    assert kwargs["temperature"] == 0.0
    assert kwargs["response_format"] is AnswerSchema
    assert kwargs["tools"][0]["type"] == "function"
    assert kwargs["max_tokens"] == 256


# ---------------------------------------------------------------------------
# complete()
# ---------------------------------------------------------------------------


async def test_complete_sends_normalized_kwargs_and_parses_response() -> None:
    provider = Provider(
        api_key="sk-test",
        model="openai/gpt-4o-mini",
        base_url="https://proxy.example/v1",
    )
    fake_resp = make_completion_response(
        content='{"answer": "done", "confidence": 1.0}',
        tool_calls=[make_tool_call("tc_1", "run_bash", '{"command": "echo hi"}')],
    )

    with patch("src.provider.acompletion", new=AsyncMock(return_value=fake_resp)) as mock_acomp:
        result = await provider.complete(
            [{"role": "user", "content": "go"}],
            output_schema=AnswerSchema,
            tools=[{"name": "run_bash", "description": "run", "input_schema": {"type": "object"}}],
            temperature=0.2,
            max_tokens=128,
        )

    call_kwargs = mock_acomp.call_args.kwargs
    assert call_kwargs["model"] == "openai/gpt-4o-mini"
    assert call_kwargs["api_key"] == "sk-test"
    assert call_kwargs["base_url"] == "https://proxy.example/v1"
    assert call_kwargs["stream"] is False
    assert call_kwargs["temperature"] == 0.2
    assert call_kwargs["response_format"] is AnswerSchema
    assert call_kwargs["tools"][0]["type"] == "function"
    assert call_kwargs["max_tokens"] == 128

    assert result.parsed == AnswerSchema(answer="done", confidence=1.0)
    assert result.tool_calls == [
        ToolCall(id="tc_1", name="run_bash", arguments={"command": "echo hi"})
    ]


# ---------------------------------------------------------------------------
# stream()
# ---------------------------------------------------------------------------


async def test_stream_yields_text_and_reasoning_and_skips_empty_choices() -> None:
    provider = Provider(api_key="sk-test", model="openai/gpt-4o-mini")
    chunks = [
        make_stream_chunk(empty_choices=True),
        make_stream_chunk(reasoning_content="thinking..."),
        make_stream_chunk(content="Hello ", include_reasoning_attr=False),
        make_stream_chunk(content="world", finish_reason="stop"),
    ]

    with patch(
        "src.provider.acompletion",
        new=AsyncMock(return_value=async_iter(chunks)),
    ) as mock_acomp:
        collected = [
            chunk
            async for chunk in provider.stream(
                [{"role": "user", "content": "hi"}],
                temperature=0.5,
            )
        ]

    assert mock_acomp.call_args.kwargs["stream"] is True
    assert mock_acomp.call_args.kwargs["temperature"] == 0.5
    assert collected == [
        StreamChunk(content="", reasoning="thinking...", finish_reason=None, tool_calls=[]),
        StreamChunk(content="Hello ", reasoning="", finish_reason=None, tool_calls=[]),
        StreamChunk(content="world", reasoning="", finish_reason="stop", tool_calls=[]),
    ]


async def test_stream_assembles_multi_chunk_and_parallel_tool_calls() -> None:
    provider = Provider(api_key="sk-test", model="openai/gpt-4o-mini")
    chunks = [
        # Tool index 1 arrives first to verify index sorting on assembly.
        make_stream_chunk(
            tool_calls=[
                SimpleNamespace(
                    index=1,
                    id="call_2",
                    function=SimpleNamespace(name="ping", arguments=""),
                )
            ]
        ),
        make_stream_chunk(
            tool_calls=[
                SimpleNamespace(
                    index=0,
                    id="call_1",
                    function=SimpleNamespace(name="run_", arguments='{"comm'),
                )
            ]
        ),
        make_stream_chunk(
            tool_calls=[
                SimpleNamespace(
                    index=0,
                    id=None,
                    function=SimpleNamespace(name="bash", arguments='and": "ls"}'),
                )
            ]
        ),
        make_stream_chunk(finish_reason="tool_calls"),
    ]

    with patch(
        "src.provider.acompletion",
        new=AsyncMock(return_value=async_iter(chunks)),
    ):
        collected = [
            chunk
            async for chunk in provider.stream(
                [{"role": "user", "content": "list files"}],
                tools=[{"name": "run_bash", "input_schema": {"type": "object"}}],
            )
        ]

    assert [c.tool_calls for c in collected[:-1]] == [[], [], []]
    assert collected[-1].finish_reason == "tool_calls"
    assert collected[-1].tool_calls == [
        ToolCall(id="call_1", name="run_bash", arguments={"command": "ls"}),
        ToolCall(id="call_2", name="ping", arguments={}),
    ]


async def test_stream_preserves_length_finish_reason_for_truncated_tool_arguments() -> None:
    provider = Provider(api_key="sk-test", model="openai/gpt-4o-mini")
    chunks = [
        make_stream_chunk(
            tool_calls=[
                SimpleNamespace(
                    index=0,
                    id="call_1",
                    function=SimpleNamespace(name="run_bash", arguments='{"command": "echo'),
                )
            ]
        ),
        make_stream_chunk(finish_reason="length"),
    ]

    with patch(
        "src.provider.acompletion",
        new=AsyncMock(return_value=async_iter(chunks)),
    ):
        collected = [
            chunk
            async for chunk in provider.stream(
                [{"role": "user", "content": "run echo"}],
                tools=[{"name": "run_bash", "input_schema": {"type": "object"}}],
            )
        ]

    assert len(collected) == 2
    assert collected[-1].finish_reason == "length"
    assert collected[-1].tool_calls == []
