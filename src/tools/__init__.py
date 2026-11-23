"""Tool registration, permission policy, and execution."""

from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

ToolFunc = Callable[..., Awaitable[Any]]


class PermissionPolicy:
    """Decides which tools need explicit user approval before they run."""

    def __init__(self, require_permission_for: Iterable[str] = ()) -> None:
        """Initialize the policy.

        Args:
            require_permission_for (Iterable[str], optional): Names of the tools
                that need user approval. Every other tool runs without asking.
        """
        self._restricted = frozenset(require_permission_for)

    def require_permission(self, tool_name: str) -> bool:
        """Return True if the tool needs user approval before it runs."""
        return tool_name in self._restricted


class ToolRegistry:
    """Stores tool schemas and callables, and executes tool calls by name."""

    def __init__(self, permission_policy: PermissionPolicy | None = None) -> None:
        """Initialize an empty registry.

        Args:
            permission_policy (PermissionPolicy, optional): Policy that decides
                which tools need approval. Defaults to requiring no approval.
        """
        self.permission_policy = permission_policy or PermissionPolicy()
        self._schemas: dict[str, dict[str, Any]] = {}
        self._functions: dict[str, ToolFunc] = {}

    def register(self, schema: dict[str, Any], func: ToolFunc) -> None:
        """Register a tool.

        Args:
            schema (dict[str, Any]): OpenAI-style tool schema. Its function name is the tool name.
            func (ToolFunc): Async callable that implements the tool.

        Raises:
            ValueError: If the schema has no function name or the name is already registered.
        """
        name = schema.get("function", {}).get("name")
        if not name:
            raise ValueError("tool schema must define function.name")
        if name in self._functions:
            raise ValueError(f"tool '{name}' is already registered")
        self._schemas[name] = schema
        self._functions[name] = func

    def get_schemas(self) -> list[dict[str, Any]]:
        """Return the schemas of all registered tools."""
        return list(self._schemas.values())

    def requires_permission(self, tool_name: str) -> bool:
        """Return True if the named tool needs user approval before it runs."""
        return self.permission_policy.require_permission(tool_name)

    async def execute(self, tool_name: str, args: Mapping[str, Any]) -> str:
        """Run a tool and return its output as a string.

        Errors never propagate: an unknown tool or a failing tool returns a
        formatted error string so the agent loop keeps running.

        Args:
            tool_name (str): Name of the tool to run.
            args (Mapping[str, Any]): Keyword arguments for the tool.

        Returns:
            str: The tool output, or an error message.
        """
        func = self._functions.get(tool_name)
        if func is None:
            return f"Error: unknown tool '{tool_name}'"
        try:
            result = await func(**args)
        except Exception as exc:  # noqa: BLE001 - tool errors must not crash the agent loop
            return f"Error executing tool '{tool_name}': {type(exc).__name__}: {exc}"
        return str(result)
