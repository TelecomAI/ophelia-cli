import pytest

from src.tools.run_bash import run_bash


def expected_report(cmd: str, exit_code: int, stdout: str, stderr: str) -> str:
    return f"Command: {cmd!r}\nExit code: {exit_code}\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}\n"


@pytest.mark.asyncio
async def test_run_bash_returns_stdout_and_stderr() -> None:
    cmd = "printf 'standard output'; printf 'standard error' >&2"
    result = await run_bash(cmd)

    assert result == expected_report(cmd, 0, "standard output", "standard error")


@pytest.mark.asyncio
async def test_run_bash_returns_output_when_command_fails() -> None:
    cmd = "printf 'command failed' >&2; exit 1"
    result = await run_bash(cmd)

    assert result == expected_report(cmd, 1, "", "command failed")


@pytest.mark.asyncio
async def test_run_bash_returns_no_command_message_for_empty_command() -> None:
    assert await run_bash("") == "No command is given"


@pytest.mark.parametrize("timeout", [-1, 1.5, "1"])
@pytest.mark.asyncio
async def test_run_bash_rejects_invalid_timeout(timeout: object) -> None:
    with pytest.raises(ValueError, match="timeout parameter"):
        await run_bash("printf 'should not run'", timeout=timeout)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_run_bash_reports_timeout() -> None:
    with pytest.raises(TimeoutError, match="timed out after 1 seconds"):
        await run_bash("sleep 2", timeout=1)


@pytest.mark.asyncio
async def test_run_bash_truncates_long_report() -> None:
    cmd = "printf 'abcdefghij'"
    max_output = 40
    result = await run_bash(cmd, max_output=max_output)
    full_report = expected_report(cmd, 0, "abcdefghij", "")

    assert result == full_report[:max_output] + "\n [TRUNCATED]"
