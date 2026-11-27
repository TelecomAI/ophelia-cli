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
    SubagentStart,
    SubagentStop,
    ThinkingDisplay,
)
from src.prompts import Environment, build_system_prompt
from src.provider import Provider, ToolCall
from src.tools.spawn_agent import VALID_EFFORTS

MAX_TURNS_MESSAGE = "Maximum agent turns reached ({max_turns})."


class Agent:
    def __init__(
        self,
        provider: Provider,
        tools: list[dict] | None = None,
        max_turns: int = 20,
    ) -> None:
        """Initialize the agent.

        Args:
            provider (Provider): The provider to use. The system prompt is built
                from the tool schemas and the detected environment.
            tools (list[dict], optional): Tool schemas sent to the provider.
            max_turns (int, optional): Max number of turns. Defaults to 20.
        """

        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")

        self.provider = provider
        self.tools = tools or []

        self.system_prompt = build_system_prompt(
            tool_names=[
                tool_name
                for tool in self.tools
                if (tool_name := tool["function"]["name"]) is not None
            ],
            environment=Environment.detect(),
        )
        self.max_turns = max_turns
        self.output_schema: type[BaseModel] | dict[str, Any] | None = None
        self.history: list[dict] = [
            {"role": "system", "content": self.system_prompt}
        ]  # TODO: possibly forgets first message after a long session

    async def run(
        self,
        user_input: str,
        effort: str | None = None,
        stream: bool = True,
    ) -> AsyncGenerator[Event, Any]:
        """
        Run one invocation of the agent.

        Args:
            user_input (str): The user message to send to the model.
            effort (str, optional): Reasoning effort for this run only.
            stream (bool, optional): Whether to stream the model response chunk by
                chunk. When False, one non-streaming provider call is made per turn
                and the whole message is emitted as a single MessageDisplay event.
                Defaults to True.
        """

        if effort is None or effort not in VALID_EFFORTS:
            raise ValueError(f"effort must be one of {VALID_EFFORTS}")

        self.history.append({"role": "user", "content": user_input})

        turn: int = 0
        while True:
            turn += 1
            full_content: str = ""
            tool_calls: list[ToolCall] = []
            if stream:
                async for chunk in self.provider.stream(
                    messages=self.history,
                    tools=self.tools,
                    output_schema=self.output_schema,
                    reasoning_effort=effort,
                ):
                    full_content += chunk.content

                    if chunk.reasoning:
                        yield ThinkingDisplay(text=chunk.reasoning)

                    if chunk.content:
                        yield MessageDisplay(text=chunk.content)

                    tool_calls.extend(chunk.tool_calls)
            else:
                response = await self.provider.complete(
                    messages=self.history,
                    tools=self.tools,
                    output_schema=self.output_schema,
                    reasoning_effort=effort,
                )
                full_content = response.content
                tool_calls = list(response.tool_calls)

                if full_content:
                    yield MessageDisplay(text=full_content)
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

            for tool_call in tool_calls:
                tool_args = {
                    "id": tool_call.id,
                    "tool_name": tool_call.name,
                    "args": tool_call.arguments,
                }

                # Every regular tool call asks for permission. The caller answers with
                # a list: [True] approves, anything else (including None) denies.
                permission_answers = yield PermissionRequest(**tool_args)
                approved = bool(permission_answers) and all(
                    answer is True for answer in permission_answers
                )

                if approved:
                    # The caller runs the tool and answers with [result].
                    if tool_call.name == "spawn_agent":
                        pre_event = SubagentStart(id=tool_call.id, **tool_args["args"])
                    else:
                        pre_event = PreToolUse(**tool_args)
                    tool_answers = yield pre_event

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

                if tool_call.name == "spawn_agent" and approved:
                    post_event = SubagentStop(
                        id=tool_call.id, task=tool_args["args"]["task"], result=result
                    )
                else:
                    post_event = PostToolUse(
                        id=tool_call.id, tool_name=tool_call.name, result=result
                    )

                yield post_event

            if not tool_calls:
                yield Stop(text=full_content)
                break

            if turn >= self.max_turns:
                yield Stop(text=MAX_TURNS_MESSAGE.format(max_turns=self.max_turns))
                break
