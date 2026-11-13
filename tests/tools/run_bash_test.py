import asyncio
import os
import shutil
from pathlib import Path

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


@pytest.mark.asyncio
async def test_run_bash_kills_child_processes_on_timeout(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    cmd = f"(sleep 30 & echo $! > {pid_file}; wait)"

    with pytest.raises(TimeoutError):
        await run_bash(cmd, timeout=1)

    await asyncio.sleep(0.05)  # Allow PID 1 a moment to reap the orphaned grandchild
    grandchild_pid = int(pid_file.read_text().strip())

    with pytest.raises(ProcessLookupError):
        os.kill(grandchild_pid, 0)


@pytest.mark.asyncio
async def test_run_bash_kills_child_processes_on_cancellation(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    cmd = f"(sleep 30 & echo $! > {pid_file}; wait)"

    task = asyncio.create_task(run_bash(cmd, timeout=30))

    # Wait until the grandchild has spawned and written its PID
    for _ in range(50):
        if pid_file.exists() and pid_file.read_text().strip():
            break
        await asyncio.sleep(0.02)

    assert pid_file.exists(), "Child process did not start in time"
    grandchild_pid = int(pid_file.read_text().strip())

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0.05)
    with pytest.raises(ProcessLookupError):
        os.kill(grandchild_pid, 0)


@pytest.mark.parametrize("max_output", [0, -1, 1.5, "1"])
@pytest.mark.asyncio
async def test_run_bash_rejects_invalid_max_output(max_output: object) -> None:
    with pytest.raises(ValueError, match="max_output parameter"):
        await run_bash("printf 'should not run'", max_output=max_output)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_run_bash_returns_no_command_message_for_whitespace_command() -> None:
    assert await run_bash("   \n\t  ") == "No command is given"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
@pytest.mark.asyncio
async def test_run_bash_supports_bash_syntax() -> None:
    cmd = "[[ 'hello' == h* ]] && printf 'bash works'"
    result = await run_bash(cmd)

    assert result == expected_report(cmd, 0, "bash works", "")
