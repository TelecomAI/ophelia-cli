import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
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
from src.tools.spawn_agent import VALID_EFFORTS, get_subagent_tools, validate_spawn_agent_args

MAX_TURNS_MESSAGE = "Maximum agent turns reached ({max_turns})."

# Answer for sub-agent tool calls when the Agent has no tool executor.
SUBAGENT_TOOL_ERROR = "Error: sub-agents cannot execute tools yet."

# Runs one tool call: ``executor(tool_name, args)`` returns the result text.
ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[str]]


async def _run_tool(
    tool_executor: ToolExecutor | None,
    tool_name: str,
    args: dict[str, Any],
) -> str:
    """Run one tool call through the executor and return its result text.

    Errors raised by the executor propagate: ``_run_subagents`` reports them as a
    failed sub-agent instead of handing a silent failure to the model.
    """
    if tool_executor is None:
        return SUBAGENT_TOOL_ERROR
    return await tool_executor(tool_name, args)


def _tool_schema_name(schema: dict[str, Any]) -> str | None:
    """Return a tool schema's name in either OpenAI or ``input_schema`` format."""
    function = schema.get("function")
    if isinstance(function, dict):
        name = function.get("name")
        return name if isinstance(name, str) else None

    name = schema.get("name")
    return name if isinstance(name, str) else None


class Agent:
    def __init__(
        self,
        provider: Provider,
        tools: list[dict] | None = None,  # TODO: Check the compatibiliy between calls
        max_turns: int = 20,
        *,
        effort: str = "medium",
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        """Initialize the agent.

        Args:
            provider (Provider): The provider to use. The system prompt is built
                from the tool schemas and the detected environment.
            tools (list[dict], optional): Tool schemas sent to the provider.
            max_turns (int, optional): Max number of turns. Defaults to 20.
            effort (str, optional): Reasoning effort used by default on every run
                ('low', 'medium', or 'high'). Defaults to "medium".
            tool_executor (ToolExecutor, optional): Callable executed as
                ``tool_executor(tool_name, args)`` that returns a tool's result
                text. Used to run sub-agent tool calls. When None, sub-agent tool
                calls are answered with ``SUBAGENT_TOOL_ERROR``. Defaults to None.
        """

        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        if effort not in VALID_EFFORTS:
            raise ValueError(f"effort must be one of {VALID_EFFORTS}")

        self.provider = provider
        self.tools = tools or []

        # NOTE: Make sure that tools have the intended structure
        self.system_prompt = build_system_prompt(
            tool_names=[
                name for tool in self.tools if (name := _tool_schema_name(tool)) is not None
            ],
            environment=Environment.detect(),
        )
        self.max_turns = max_turns
        self.effort = effort
        self.tool_executor = tool_executor
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
        Run one turn of the agent.

        Args:
            user_input (str): The user message to send to the model.
            effort (str, optional): Reasoning effort for this run only. If None,
                the agent's own effort is used.
            stream (bool, optional): Whether to stream the model response chunk by
                chunk. When False, one non-streaming provider call is made per turn
                and the whole message is emitted as a single MessageDisplay event.
                Defaults to True.
        """

        if effort is not None and effort not in VALID_EFFORTS:
            raise ValueError(f"effort must be one of {VALID_EFFORTS}")

        run_effort = self.effort if effort is None else effort

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
                    reasoning_effort=run_effort,
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
                    reasoning_effort=run_effort,
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
                async for event in self._run_subagents(spawn_calls):
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
    ) -> AsyncGenerator[Event, Any]:
        """Run the ``spawn_agent`` calls concurrently and stream their events."""

        if not spawn_calls:
            return
        named_schemas = {
            name: schema for schema in self.tools if (name := _tool_schema_name(schema)) is not None
        }
        subagent_tools = list(get_subagent_tools(named_schemas).values())
        queue: asyncio.Queue[Event] = asyncio.Queue()

        async def run_one(tool_call: ToolCall) -> None:
            task = tool_call.arguments.get("task")
            task = task if isinstance(task, str) else ""

            try:
                task, effort = validate_spawn_agent_args(**tool_call.arguments)
            except (TypeError, ValueError) as exc:
                await queue.put(SubagentStop(id=tool_call.id, task=task, result=f"Error: {exc}"))
                return

            await queue.put(SubagentStart(id=tool_call.id, task=task, effort=effort))

            subagent = Agent(
                provider=self.provider,
                tools=subagent_tools,
                max_turns=self.max_turns,
                tool_executor=self.tool_executor,
            )
            try:
                result = await self._drive_subagent(subagent, task, effort, self.tool_executor)
            except Exception as exc:  # noqa: BLE001
                result = f"Error: sub-agent failed: {exc}"

            await queue.put(SubagentStop(id=tool_call.id, task=task, result=result))

        run_all = asyncio.gather(*(run_one(tool_call) for tool_call in spawn_calls))
        try:
            remaining = len(spawn_calls)
            while remaining:
                event = await queue.get()
                if isinstance(event, SubagentStop):
                    remaining -= 1
                yield event
        finally:
            await run_all

    @staticmethod
    async def _drive_subagent(
        subagent: Agent,
        task: str,
        effort: str,
        tool_executor: ToolExecutor | None = None,
    ) -> str:
        """Run a sub-agent to completion and return the text of its Stop event."""

        runner = subagent.run(task, effort=effort, stream=False)
        answer: Any = None
        try:
            while True:
                try:
                    event = await runner.asend(answer)
                except StopAsyncIteration:
                    return ""
                answer = None

                if isinstance(event, PermissionRequest):
                    answer = [True]
                elif isinstance(event, PreToolUse):
                    answer = [await _run_tool(tool_executor, event.tool_name, event.args)]
                elif isinstance(event, Stop):
                    return event.text
        finally:
            await runner.aclose()
