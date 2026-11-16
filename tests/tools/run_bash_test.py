import asyncio
import contextlib
import ctypes
import os
import shlex
import shutil
import signal
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools import run_bash as run_bash_module
from src.tools.run_bash import run_bash


def expected_report(cmd: str, exit_code: int, stdout: str, stderr: str) -> str:
    return f"Command: {cmd!r}\nExit code: {exit_code}\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}\n"


async def assert_process_terminated(pid: int) -> None:
    deadline = asyncio.get_running_loop().time() + 1
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        if Path("/proc").is_dir():
            try:
                stat = Path(f"/proc/{pid}/stat").read_text()
            except FileNotFoundError, ProcessLookupError:
                return
            # The command name in parentheses may itself contain spaces or parentheses.
            if stat.rsplit(")", 1)[1].split()[0] == "Z":
                return
        assert asyncio.get_running_loop().time() < deadline, f"Process {pid} did not terminate"
        await asyncio.sleep(0.02)


def _is_windows_process_alive(pid: int) -> bool:
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return False
    from ctypes import wintypes

    kernel32 = windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    process_query_limited_information = 0x1000
    still_active = 259
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


async def assert_windows_process_terminated(pid: int) -> None:
    deadline = asyncio.get_running_loop().time() + 2
    while _is_windows_process_alive(pid):
        assert asyncio.get_running_loop().time() < deadline, f"Process {pid} did not terminate"
        await asyncio.sleep(0.02)


@pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="requires Linux procfs")
@pytest.mark.asyncio
async def test_termination_check_accepts_unreaped_zombie() -> None:
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    try:
        await assert_process_terminated(pid)
        os.kill(pid, 0)
        assert Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "Z"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        await asyncio.to_thread(os.waitpid, pid, 0)


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


@pytest.mark.skipif(sys.platform == "win32", reason="uses POSIX bash PIDs and os.kill(..., 0)")
@pytest.mark.asyncio
async def test_run_bash_kills_child_processes_on_timeout(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    cmd = f"(sleep 30 & echo $! > {pid_file}; wait)"

    with pytest.raises(TimeoutError):
        await run_bash(cmd, timeout=1)

    grandchild_pid = int(pid_file.read_text().strip())

    await assert_process_terminated(grandchild_pid)


@pytest.mark.skipif(sys.platform == "win32", reason="uses POSIX bash PIDs and os.kill(..., 0)")
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

    await assert_process_terminated(grandchild_pid)


@pytest.mark.skipif(sys.platform == "win32", reason="uses POSIX bash PIDs and os.kill(..., 0)")
@pytest.mark.asyncio
async def test_run_bash_kills_descendant_after_shell_exits_on_timeout(tmp_path: Path) -> None:
    pid_file = tmp_path / "pids.txt"
    cmd = f'sleep 30 & printf \'%s %s\\n\' "$$" "$!" > {pid_file}'

    with pytest.raises(TimeoutError):
        await run_bash(cmd, timeout=1)

    _, descendant_pid_str = pid_file.read_text().strip().split()
    descendant_pid = int(descendant_pid_str)

    try:
        await assert_process_terminated(descendant_pid)
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(descendant_pid, signal.SIGKILL)


@pytest.mark.skipif(sys.platform == "win32", reason="uses POSIX bash PIDs and os.kill(..., 0)")
@pytest.mark.asyncio
async def test_run_bash_kills_descendant_after_shell_exits_on_cancellation(tmp_path: Path) -> None:
    pid_file = tmp_path / "pids.txt"
    cmd = f'sleep 30 & printf \'%s %s\\n\' "$$" "$!" > {pid_file}'

    task = asyncio.create_task(run_bash(cmd, timeout=30))

    shell_pid: int | None = None
    descendant_pid: int | None = None
    for _ in range(50):
        if pid_file.exists():
            content = pid_file.read_text()
            if "\n" in content:
                shell_pid_str, descendant_pid_str = content.strip().split()
                shell_pid = int(shell_pid_str)
                descendant_pid = int(descendant_pid_str)
                try:
                    os.kill(shell_pid, 0)
                except ProcessLookupError:
                    break
        await asyncio.sleep(0.02)

    assert shell_pid is not None and descendant_pid is not None, (
        "Child process did not start in time"
    )
    with pytest.raises(ProcessLookupError):
        os.kill(shell_pid, 0)

    try:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        await assert_process_terminated(descendant_pid)
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(descendant_pid, signal.SIGKILL)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only Job Object cleanup tests")
@pytest.mark.asyncio
async def test_run_bash_kills_descendant_after_shell_exits_on_timeout_windows(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "win_pids.txt"
    child_code = "import time; time.sleep(30)"
    launcher_code = (
        "import os, pathlib, subprocess, sys; "
        f"p = subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        f"pathlib.Path({pid_file.as_posix()!r}).write_text(f'{{os.getpid()}} {{p.pid}}\\n')"
    )
    cmd = f"{shlex.quote(Path(sys.executable).as_posix())} -c {shlex.quote(launcher_code)}"

    with pytest.raises(TimeoutError):
        await run_bash(cmd, timeout=1)

    _, descendant_pid_str = pid_file.read_text().strip().split()
    await assert_windows_process_terminated(int(descendant_pid_str))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only Job Object cleanup tests")
@pytest.mark.asyncio
async def test_run_bash_kills_descendant_after_shell_exits_on_cancellation_windows(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "win_pids.txt"
    child_code = "import time; time.sleep(30)"
    launcher_code = (
        "import os, pathlib, subprocess, sys; "
        f"p = subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        f"pathlib.Path({pid_file.as_posix()!r}).write_text(f'{{os.getpid()}} {{p.pid}}\\n')"
    )
    cmd = f"{shlex.quote(Path(sys.executable).as_posix())} -c {shlex.quote(launcher_code)}"

    task = asyncio.create_task(run_bash(cmd, timeout=30))

    launcher_pid: int | None = None
    descendant_pid: int | None = None
    for _ in range(100):
        if pid_file.exists():
            content = pid_file.read_text()
            if "\n" in content:
                launcher_pid_str, descendant_pid_str = content.strip().split()
                launcher_pid = int(launcher_pid_str)
                descendant_pid = int(descendant_pid_str)
                if not _is_windows_process_alive(launcher_pid):
                    break
        await asyncio.sleep(0.02)

    assert launcher_pid is not None and descendant_pid is not None, (
        "Child process did not start in time"
    )
    assert not _is_windows_process_alive(launcher_pid)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await assert_windows_process_terminated(descendant_pid)


def test_find_bash_prefers_git_bash_over_wsl_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    git_dir = tmp_path / "Git"
    git_exe = git_dir / "cmd" / "git.exe"
    git_bash = git_dir / "bin" / "bash.exe"
    git_exe.parent.mkdir(parents=True)
    git_bash.parent.mkdir(parents=True)
    git_exe.write_text("")
    git_bash.write_text("")

    wsl_bash = r"C:\Users\dev\AppData\Local\Microsoft\WindowsApps\bash.exe"

    monkeypatch.setattr(run_bash_module, "_IS_WINDOWS", True)
    monkeypatch.setattr(
        run_bash_module.shutil,
        "which",
        lambda name: str(git_exe) if name == "git" else wsl_bash,
    )

    assert run_bash_module._find_bash() == str(git_bash)


@pytest.mark.asyncio
async def test_run_bash_uses_exec_with_dash_c_when_bash_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_proc = MagicMock()
    fake_proc.pid = 12345
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))

    monkeypatch.setattr(run_bash_module, "BASH_PATH", "/custom/bin/bash")
    monkeypatch.setattr(run_bash_module, "_attach_windows_job", lambda _pid: None)

    with patch(
        "src.tools.run_bash.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_proc),
    ) as mock_exec:
        result = await run_bash("echo ok")

    mock_exec.assert_awaited_once()
    assert mock_exec.call_args.args == ("/custom/bin/bash", "-c", "echo ok")
    assert "STDOUT:\nok" in result


@pytest.mark.asyncio
async def test_run_bash_falls_back_to_shell_when_bash_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_proc = MagicMock()
    fake_proc.pid = 12345
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))

    monkeypatch.setattr(run_bash_module, "BASH_PATH", None)
    monkeypatch.setattr(run_bash_module, "_attach_windows_job", lambda _pid: None)

    with patch(
        "src.tools.run_bash.asyncio.create_subprocess_shell",
        new=AsyncMock(return_value=fake_proc),
    ) as mock_shell:
        result = await run_bash("echo ok")

    mock_shell.assert_awaited_once()
    assert mock_shell.call_args.kwargs["cmd"] == "echo ok"
    assert "STDOUT:\nok" in result


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
