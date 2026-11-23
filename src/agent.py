import json
from collections.abc import AsyncGenerator
from typing import Any

from pydantic import BaseModel, ValidationError

from src.events import (
    Event,
    InvalidContentSchema,
    MessageDisplay,
    PermissionRequest,
    PostToolUse,
    PreToolUse,
    Stop,
    SubagentStart,  # noqa: F401
    SubagentStop,
    ThinkingDisplay,
)
from src.provider import Provider, ToolCall

MAX_TURNS_MESSAGE = "Maximum agent turns reached ({max_turns})."


class Agent:
    def __init__(
        self,
        provider: Provider,
        system_prompt: str,
        tools: list[dict] | None = None,
        max_turns: int = 20,
    ) -> None:
        """Initialize the agent.

        Args:
            provider (Provider): The provider to use.
            system_prompt (str): The system prompt.
            tools (list[dict], optional): Tool schemas sent to the provider.
            max_turns (int, optional): Max number of turns. Defaults to 20.
        """

        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")

        self.provider = provider
        self.tools = tools or []
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.output_schema: type[BaseModel] | dict[str, Any] | None = (
            None  # FIXME: Define the output schema for the agent's responses
        )
        self.history: list[dict] = [
            {"role": "system", "content": self.system_prompt}
        ]  # TODO: possibly forgets ...

    async def run(self, user_input: str) -> AsyncGenerator[Event, Any]:
        """
        Run one turn of the agent.
        """

        self.history.append({"role": "user", "content": user_input})

        turn: int = 0
        while True:
            turn += 1
            full_content: str = ""
            tool_calls: list[ToolCall] = []
            async for chunk in self.provider.stream(
                messages=self.history,
                tools=self.tools,
                output_schema=self.output_schema,
            ):
                full_content += chunk.content

                if chunk.reasoning:
                    yield ThinkingDisplay(text=chunk.reasoning)

                if chunk.content:
                    yield MessageDisplay(text=chunk.content)

                tool_calls.extend(chunk.tool_calls)
            if self.output_schema is not None:
                try:
                    if isinstance(self.output_schema, type) and issubclass(
                        self.output_schema, BaseModel
                    ):
                        self.output_schema.model_validate_json(full_content)
                    elif isinstance(self.output_schema, dict):
                        json.loads(full_content)
                except json.JSONDecodeError, ValidationError:
                    yield InvalidContentSchema(text="Invalid JSON content")

            regular_calls = [t for t in tool_calls if t.name != "spawn_agent"]
            spawn_calls = [t for t in tool_calls if t.name == "spawn_agent"]

            assistant_message: dict = {"role": "assistant", "content": full_content}
            if tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": t.id,
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "arguments": json.dumps(t.arguments),
                        },
                    }
                    for t in tool_calls
                ]
            self.history.append(assistant_message)

            for tool_call in regular_calls:
                args = {
                    "id": tool_call.id,
                    "tool_name": tool_call.name,
                    "args": tool_call.arguments,
                }

                # Every regular tool call asks for permission. The caller answers with
                # a list: [True] approves, anything else (including None) denies.
                permission_answers = yield PermissionRequest(**args)
                approved = bool(permission_answers) and all(
                    answer is True for answer in permission_answers
                )

                if approved:
                    # The caller runs the tool and answers with [result].
                    tool_answers = yield PreToolUse(**args)
                    result: str = tool_answers[0]
                else:
                    result = "Tool call denied by user"

                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(result),
                    }
                )

                yield PostToolUse(id=tool_call.id, tool_name=tool_call.name, result=result)  # type: ignore

            if spawn_calls:
                spawn_results: dict[str, str] = {}
                async for event in self._run_subagents(spawn_calls):  # type: ignore
                    if isinstance(event, SubagentStop):
                        spawn_results[event.id] = event.result
                    yield event

                for tool_call in spawn_calls:
                    self.history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": spawn_results.get(
                                tool_call.id, "Error: sub-agent returned no result."
                            ),
                        }
                    )

            if not tool_calls:
                yield Stop(text=full_content)
                break

            if turn >= self.max_turns:
                yield Stop(text=MAX_TURNS_MESSAGE.format(max_turns=self.max_turns))
                break

    async def _run_subagents(
        self,
        spawn_calls: list[ToolCall],
    ) -> AsyncGenerator[Event, str]:  # type: ignore
        """Run the ``spawn_agent`` calls and collect one tool result per call.

        Args:
            spawn_calls (list[ToolCall]): The ``spawn_agent`` calls emitted by
                the model.
            results (dict[str, str]): Filled in place with
                ``tool_call.id -> result text``. ``run()`` uses it to append the
                matching ``role="tool"`` messages to the history.

        Yields:
            SubagentStart before a sub-agent starts and SubagentStop when it
            finishes.
        """
        # TODO(spawn-agent): build the child Agent with
        # get_subagent_tools(self.tools), run it on `task`, and store its
        # final Stop text in results[tool_call.id]. Run several calls
        # concurrently with asyncio.gather
