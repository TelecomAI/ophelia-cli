import asyncio
import contextlib
import ctypes
import os
import shlex
import signal
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools import ToolRegistry
from src.tools import run_bash as run_bash_module
from src.tools.run_bash import run_bash


def expected_report(cmd: str, exit_code: int, stdout: str, stderr: str) -> str:
    return f"Command: {cmd!r}\nExit code: {exit_code}\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}\n"


def test_schema_registers_with_the_tool_registry() -> None:
    # The registry only accepts the OpenAI schema format that every other tool uses.
    registry = ToolRegistry()

    registry.register(run_bash_module.SCHEMA, run_bash)

    assert registry.get_schemas() == [run_bash_module.SCHEMA]
    assert run_bash_module.SCHEMA["function"]["name"] == "run_bash"


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


@pytest.mark.skipif(run_bash_module.BASH_PATH is None, reason="bash is not installed")
@pytest.mark.asyncio
async def test_run_bash_returns_stdout_and_stderr() -> None:
    cmd = "printf 'standard output'; printf 'standard error' >&2"
    result = await run_bash(cmd)

    assert result == expected_report(cmd, 0, "standard output", "standard error")


@pytest.mark.skipif(run_bash_module.BASH_PATH is None, reason="bash is not installed")
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


@pytest.mark.skipif(run_bash_module.BASH_PATH is None, reason="bash is not installed")
@pytest.mark.asyncio
async def test_run_bash_reports_timeout() -> None:
    with pytest.raises(TimeoutError, match="timed out after 1 seconds"):
        await run_bash("sleep 2", timeout=1)


@pytest.mark.skipif(run_bash_module.BASH_PATH is None, reason="bash is not installed")
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


@pytest.mark.skipif(
    sys.platform != "win32" or run_bash_module.BASH_PATH is None,
    reason="requires Windows and bash",
)
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


@pytest.mark.skipif(
    sys.platform != "win32" or run_bash_module.BASH_PATH is None,
    reason="requires Windows and bash",
)
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only snapshot/fallback cleanup tests")
@pytest.mark.asyncio
async def test_kill_windows_descendants_snapshot_kills_orphan_after_parent_exits_windows(
    tmp_path: Path,
) -> None:
    python_exe = getattr(sys, "_base_executable", sys.executable) or sys.executable
    pid_file = tmp_path / "orphan_pids.txt"
    child_code = "import time; time.sleep(30)"
    launcher_code = (
        "import pathlib, subprocess, sys; "
        f"p = subprocess.Popen([{python_exe!r}, '-c', {child_code!r}]); "
        f"pathlib.Path({pid_file.as_posix()!r}).write_text(f'{{p.pid}}\\n')"
    )
    launcher = await asyncio.create_subprocess_exec(
        python_exe,
        "-c",
        launcher_code,
        creationflags=run_bash_module._CREATE_SUSPENDED,
    )
    launcher_start = run_bash_module._get_windows_process_creation_time(launcher.pid)
    assert launcher_start is not None
    assert run_bash_module._resume_windows_process(launcher.pid)
    await asyncio.wait_for(launcher.wait(), timeout=5)

    orphan_pid = int(pid_file.read_text().strip())
    try:
        assert _is_windows_process_alive(orphan_pid)
        assert run_bash_module._kill_windows_descendants_snapshot(launcher.pid, launcher_start)
        await assert_windows_process_terminated(orphan_pid)
    finally:
        if _is_windows_process_alive(orphan_pid):
            win32 = run_bash_module._get_win32()
            if win32 is not None:
                handle = win32.kernel32.OpenProcess(0x0001, False, orphan_pid)
                if handle:
                    win32.kernel32.TerminateProcess(handle, 1)
                    win32.kernel32.CloseHandle(handle)


@pytest.mark.skipif(
    sys.platform != "win32" or run_bash_module.BASH_PATH is None,
    reason="requires Windows and bash",
)
@pytest.mark.asyncio
async def test_run_bash_delivers_timeout_when_job_unavailable_and_pipes_held_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(run_bash_module, "_attach_windows_job", lambda _pid: None)

    pid_file = tmp_path / "fallback_pids.txt"
    child_code = "import time; time.sleep(30)"
    launcher_code = (
        "import os, pathlib, subprocess, sys; "
        f"p = subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        f"pathlib.Path({pid_file.as_posix()!r}).write_text(f'{{os.getpid()}} {{p.pid}}\\n')"
    )
    cmd = f"{shlex.quote(Path(sys.executable).as_posix())} -c {shlex.quote(launcher_code)}"

    start = asyncio.get_running_loop().time()
    try:
        with pytest.raises(TimeoutError):
            await run_bash(cmd, timeout=1)
        elapsed = asyncio.get_running_loop().time() - start
        assert elapsed < 5, f"run_bash hung on descendant pipes for {elapsed:.2f}s"
    finally:
        if pid_file.exists():
            parts = pid_file.read_text().strip().split()
            if len(parts) == 2 and _is_windows_process_alive(int(parts[1])):
                win32 = run_bash_module._get_win32()
                if win32 is not None:
                    handle = win32.kernel32.OpenProcess(0x0001, False, int(parts[1]))
                    if handle:
                        win32.kernel32.TerminateProcess(handle, 1)
                        win32.kernel32.CloseHandle(handle)


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

    monkeypatch.setattr(run_bash_module, "_IS_WINDOWS", False)
    monkeypatch.setattr(run_bash_module, "BASH_PATH", "/custom/bin/bash")

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

    monkeypatch.setattr(run_bash_module, "_IS_WINDOWS", False)
    monkeypatch.setattr(run_bash_module, "BASH_PATH", None)

    with patch(
        "src.tools.run_bash.asyncio.create_subprocess_shell",
        new=AsyncMock(return_value=fake_proc),
    ) as mock_shell:
        result = await run_bash("echo ok")

    mock_shell.assert_awaited_once()
    assert mock_shell.call_args.kwargs["cmd"] == "echo ok"
    assert "STDOUT:\nok" in result


@pytest.mark.asyncio
async def test_run_bash_attaches_windows_job_before_resuming_suspended_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    fake_proc = MagicMock()
    fake_proc.pid = 4242
    fake_proc.returncode = 0

    async def fake_communicate() -> tuple[bytes, bytes]:
        events.append("communicate")
        return (b"hello", b"")

    fake_proc.communicate = fake_communicate

    async def fake_exec(*_args: object, **kwargs: object) -> MagicMock:
        assert kwargs.get("creationflags") == run_bash_module._CREATE_SUSPENDED
        assert kwargs.get("start_new_session") is False
        events.append("spawn_suspended")
        return fake_proc

    def fake_creation_time(pid: int) -> int:
        assert pid == 4242
        events.append("get_creation_time")
        return 1000

    def fake_attach(pid: int) -> int:
        assert pid == 4242
        events.append("attach_job")
        return 999

    def fake_resume(pid: int) -> bool:
        assert pid == 4242
        events.append("resume_process")
        return True

    fake_win32 = MagicMock()
    monkeypatch.setattr(run_bash_module, "_IS_WINDOWS", True)
    monkeypatch.setattr(run_bash_module, "BASH_PATH", r"C:\Program Files\Git\bin\bash.exe")
    monkeypatch.setattr(run_bash_module, "_get_windows_process_creation_time", fake_creation_time)
    monkeypatch.setattr(run_bash_module, "_attach_windows_job", fake_attach)
    monkeypatch.setattr(run_bash_module, "_resume_windows_process", fake_resume)
    monkeypatch.setattr(run_bash_module, "_get_win32", lambda: fake_win32)

    with patch("src.tools.run_bash.asyncio.create_subprocess_exec", side_effect=fake_exec):
        result = await run_bash("echo hello")

    assert events == [
        "spawn_suspended",
        "get_creation_time",
        "attach_job",
        "resume_process",
        "communicate",
    ]
    fake_win32.kernel32.CloseHandle.assert_called_once_with(999)
    assert "STDOUT:\nhello" in result


@pytest.mark.asyncio
async def test_run_bash_cleans_up_if_windows_resume_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_proc = MagicMock()
    fake_proc.pid = 4242
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))
    fake_win32 = MagicMock()
    kill_mock = AsyncMock(return_value=True)

    monkeypatch.setattr(run_bash_module, "_IS_WINDOWS", True)
    monkeypatch.setattr(run_bash_module, "BASH_PATH", r"C:\Program Files\Git\bin\bash.exe")
    monkeypatch.setattr(run_bash_module, "_get_windows_process_creation_time", lambda _pid: 1000)
    monkeypatch.setattr(run_bash_module, "_attach_windows_job", lambda _pid: 777)
    monkeypatch.setattr(run_bash_module, "_resume_windows_process", lambda _pid: False)
    monkeypatch.setattr(run_bash_module, "_kill_process_tree", kill_mock)
    monkeypatch.setattr(run_bash_module, "_get_win32", lambda: fake_win32)

    with (
        patch(
            "src.tools.run_bash.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fake_proc),
        ),
        pytest.raises(OSError, match="Failed to resume suspended Windows process"),
    ):
        await run_bash("echo hello")

    kill_mock.assert_awaited_once_with(4242, 777, 1000)
    fake_win32.kernel32.CloseHandle.assert_called_once_with(777)


@pytest.mark.parametrize(("returncode", "expected"), [(0, True), (128, False)])
@pytest.mark.asyncio
async def test_kill_process_tree_windows_reports_taskkill_status(
    monkeypatch: pytest.MonkeyPatch, returncode: int, expected: bool
) -> None:
    fake_killer = MagicMock()
    fake_killer.returncode = returncode
    fake_killer.wait = AsyncMock(return_value=returncode)

    monkeypatch.setattr(run_bash_module, "_IS_WINDOWS", True)
    monkeypatch.setattr(run_bash_module, "_get_win32", lambda: None)
    monkeypatch.setattr(
        run_bash_module, "_kill_windows_descendants_snapshot", lambda _pid, _start: False
    )

    with patch(
        "src.tools.run_bash.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_killer),
    ):
        result = await run_bash_module._kill_process_tree(5555, None, 1000)

    assert result is expected


@pytest.mark.asyncio
async def test_run_bash_bounds_pipe_drain_when_descendant_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_transport = MagicMock()
    fake_proc = MagicMock()
    fake_proc.pid = 5000
    fake_proc._transport = fake_transport

    async def hung_communicate() -> tuple[bytes, bytes]:
        await asyncio.sleep(60)
        return (b"", b"")

    async def hung_wait() -> int:
        await asyncio.sleep(60)
        return 0

    fake_proc.communicate = hung_communicate
    fake_proc.wait = hung_wait

    monkeypatch.setattr(run_bash_module, "_IS_WINDOWS", False)
    monkeypatch.setattr(run_bash_module, "BASH_PATH", "/bin/bash")
    monkeypatch.setattr(run_bash_module, "_FALLBACK_DRAIN_TIMEOUT", 0.05)
    monkeypatch.setattr(run_bash_module, "_kill_process_tree", AsyncMock(return_value=False))

    start = asyncio.get_running_loop().time()
    with (
        patch(
            "src.tools.run_bash.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fake_proc),
        ),
        pytest.raises(TimeoutError, match="timed out after 1 seconds"),
    ):
        await run_bash("sleep 60 &", timeout=1)

    elapsed = asyncio.get_running_loop().time() - start
    assert elapsed < 2.0
    fake_transport.close.assert_called_once()


@pytest.mark.asyncio
async def test_run_bash_cancellation_bounds_pipe_drain_when_descendant_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_transport = MagicMock()
    fake_proc = MagicMock()
    fake_proc.pid = 5001
    fake_proc._transport = fake_transport
    started = asyncio.Event()

    async def hung_communicate() -> tuple[bytes, bytes]:
        started.set()
        await asyncio.sleep(60)
        return (b"", b"")

    async def hung_wait() -> int:
        await asyncio.sleep(60)
        return 0

    fake_proc.communicate = hung_communicate
    fake_proc.wait = hung_wait

    monkeypatch.setattr(run_bash_module, "_IS_WINDOWS", False)
    monkeypatch.setattr(run_bash_module, "BASH_PATH", "/bin/bash")
    monkeypatch.setattr(run_bash_module, "_FALLBACK_DRAIN_TIMEOUT", 0.05)
    monkeypatch.setattr(run_bash_module, "_kill_process_tree", AsyncMock(return_value=False))

    with patch(
        "src.tools.run_bash.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_proc),
    ):
        task = asyncio.create_task(run_bash("sleep 60 &", timeout=30))
        await started.wait()

        start = asyncio.get_running_loop().time()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    elapsed = asyncio.get_running_loop().time() - start
    assert elapsed < 1.0
    fake_transport.close.assert_called_once()


@pytest.mark.parametrize("max_output", [0, -1, 1.5, "1"])
@pytest.mark.asyncio
async def test_run_bash_rejects_invalid_max_output(max_output: object) -> None:
    with pytest.raises(ValueError, match="max_output parameter"):
        await run_bash("printf 'should not run'", max_output=max_output)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_run_bash_returns_no_command_message_for_whitespace_command() -> None:
    assert await run_bash("   \n\t  ") == "No command is given"


@pytest.mark.skipif(run_bash_module.BASH_PATH is None, reason="bash is not installed")
@pytest.mark.asyncio
async def test_run_bash_supports_bash_syntax() -> None:
    cmd = "[[ 'hello' == h* ]] && printf 'bash works'"
    result = await run_bash(cmd)

    assert result == expected_report(cmd, 0, "bash works", "")
