import pytest

from src.tools import PermissionPolicy, ToolRegistry


def _schema(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "parameters": {}}}


async def _echo(text: str) -> str:
    return text


async def _boom() -> str:
    raise RuntimeError("kaboom")


class TestPermissionPolicy:
    def test_listed_tool_requires_permission(self):
        policy = PermissionPolicy(["run_bash"])

        assert policy.require_permission("run_bash") is True

    def test_unlisted_tool_does_not_require_permission(self):
        policy = PermissionPolicy(["run_bash"])

        assert policy.require_permission("read_file") is False

    def test_default_policy_requires_no_permission(self):
        assert PermissionPolicy().require_permission("run_bash") is False


class TestToolRegistry:
    def test_get_schemas_returns_registered_schemas(self):
        registry = ToolRegistry()
        registry.register(_schema("echo"), _echo)

        assert registry.get_schemas() == [_schema("echo")]

    def test_get_schemas_is_empty_by_default(self):
        assert ToolRegistry().get_schemas() == []

    def test_register_rejects_schema_without_name(self):
        with pytest.raises(ValueError, match="function.name"):
            ToolRegistry().register({"function": {}}, _echo)

    def test_register_rejects_duplicate_name(self):
        registry = ToolRegistry()
        registry.register(_schema("echo"), _echo)

        with pytest.raises(ValueError, match="already registered"):
            registry.register(_schema("echo"), _echo)

    def test_requires_permission_delegates_to_policy(self):
        registry = ToolRegistry(PermissionPolicy(["run_bash"]))

        assert registry.requires_permission("run_bash") is True
        assert registry.requires_permission("read_file") is False

    async def test_execute_runs_tool_with_args(self):
        registry = ToolRegistry()
        registry.register(_schema("echo"), _echo)

        result = await registry.execute("echo", {"text": "hello"})

        assert result == "hello"

    async def test_execute_returns_error_for_unknown_tool(self):
        result = await ToolRegistry().execute("missing", {})

        assert result == "Error: unknown tool 'missing'"

    async def test_execute_returns_error_string_when_tool_raises(self):
        registry = ToolRegistry()
        registry.register(_schema("boom"), _boom)

        result = await registry.execute("boom", {})

        assert result == "Error executing tool 'boom': RuntimeError: kaboom"

    async def test_execute_returns_error_string_for_bad_args(self):
        registry = ToolRegistry()
        registry.register(_schema("echo"), _echo)

        result = await registry.execute("echo", {"wrong": "x"})

        assert result.startswith("Error executing tool 'echo': TypeError")
