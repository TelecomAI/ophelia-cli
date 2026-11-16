import asyncio
import contextlib
import ctypes
import os
import shutil
import signal
import sys
from pathlib import Path
from typing import Any

_IS_WINDOWS = sys.platform == "win32"


def _is_wsl_launcher(path: str) -> bool:
    normalized = os.path.normcase(os.path.abspath(path))
    return normalized.endswith(
        (
            os.path.normcase(os.path.join("WindowsApps", "bash.exe")),
            os.path.normcase(os.path.join("System32", "bash.exe")),
        )
    )


def _find_bash() -> str | None:
    """Locate a bash executable, preferring Git Bash over the WSL launcher on Windows."""
    if not _IS_WINDOWS:
        return shutil.which("bash")

    candidates: list[Path] = []
    git_path = shutil.which("git")
    if git_path:
        git_root = Path(git_path).resolve().parent.parent
        candidates.extend([git_root / "bin" / "bash.exe", git_root / "usr" / "bin" / "bash.exe"])

    for env_var, subpaths in (
        ("ProgramFiles", (("Git", "bin", "bash.exe"), ("Git", "usr", "bin", "bash.exe"))),
        ("ProgramFiles(x86)", (("Git", "bin", "bash.exe"), ("Git", "usr", "bin", "bash.exe"))),
        (
            "LocalAppData",
            (
                ("Programs", "Git", "bin", "bash.exe"),
                ("Programs", "Git", "usr", "bin", "bash.exe"),
            ),
        ),
    ):
        base = os.environ.get(env_var)
        if base:
            for parts in subpaths:
                candidates.append(Path(base, *parts))

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    which_bash = shutil.which("bash")
    if which_bash and not _is_wsl_launcher(which_bash):
        return which_bash
    return which_bash


BASH_PATH = _find_bash()


def _get_kernel32() -> Any:
    """Return a configured kernel32 handle on Windows, or None elsewhere."""
    if not _IS_WINDOWS:
        return None

    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None

    from ctypes import wintypes

    kernel32 = windll.kernel32
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE

    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL

    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _attach_windows_job(pid: int) -> int | None:
    """Attach `pid` to a new Windows Job Object so its entire process tree can be killed."""
    kernel32 = _get_kernel32()
    if kernel32 is None:
        return None

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None

    process_set_quota = 0x0100
    process_terminate = 0x0001
    proc_handle = kernel32.OpenProcess(process_set_quota | process_terminate, False, pid)
    if not proc_handle:
        kernel32.CloseHandle(job)
        return None

    try:
        if not kernel32.AssignProcessToJobObject(job, proc_handle):
            kernel32.CloseHandle(job)
            return None
    finally:
        kernel32.CloseHandle(proc_handle)

    return int(job)


async def _kill_process_tree(pid: int, job_handle: int | None) -> None:
    """Terminate `pid` and all of its descendants across POSIX and Windows."""
    if _IS_WINDOWS:
        kernel32 = _get_kernel32()
        if job_handle is not None and kernel32 is not None:
            kernel32.TerminateJobObject(job_handle, 1)
            return

        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/T",
            "/F",
            "/PID",
            str(pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await killer.wait()
        return

    with contextlib.suppress(ProcessLookupError):
        # start_new_session=True sets PGID to proc.pid; os.getpgid() can fail once reaped
        os.killpg(pid, signal.SIGKILL)


"""
Run bash commands
"""

SCHEMA = {
    "name": "run_bash",
    "description": "Run a bash command and return the output.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds. Defaults to 30.",
                "default": 30,
            },
            "max_output": {
                "type": "integer",
                "description": "Max output length in characters, defaults to 2000.",
                "default": 2000,
            },
        },
        "required": ["command"],
    },
}


async def run_bash(command: str, timeout: int = 30, max_output: int = 2000) -> str:
    """Run a bash command with a timeout and return combined stdout/stderr of max_output length."""

    if not isinstance(timeout, int) or timeout <= 0:
        raise ValueError("The timeout parameter of run_bash tool must be a positive integer")
    if not isinstance(max_output, int) or max_output <= 0:
        raise ValueError("The max_output parameter of run_bash tool must be a positive integer")

    if not command or not command.strip():
        return "No command is given"

    if BASH_PATH:
        proc = await asyncio.create_subprocess_exec(
            BASH_PATH,
            "-c",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=not _IS_WINDOWS,
        )
    else:
        proc = await asyncio.create_subprocess_shell(
            cmd=command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=not _IS_WINDOWS,
        )

    job_handle = _attach_windows_job(proc.pid)
    completed = False
    try:
        # this can throw a TimeoutError
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        completed = True

    except TimeoutError as exc:
        # we re-throw the error, cause the error catching logic must be handled elsewhere
        raise TimeoutError(f"Command {command!r} timed out after {timeout} seconds") from exc
    finally:
        try:
            if not completed:
                await _kill_process_tree(proc.pid, job_handle)
                await proc.communicate()
        finally:
            if job_handle is not None and _IS_WINDOWS:
                kernel32 = _get_kernel32()
                if kernel32 is not None:
                    kernel32.CloseHandle(job_handle)

    result = (
        f"Command: {command!r}\n"
        f"Exit code: {proc.returncode}\n\n"
        "STDOUT:\n"
        f"{stdout.decode('utf-8', errors='replace')}\n\n"
        "STDERR:\n"
        f"{stderr.decode('utf-8', errors='replace')}\n"
    )

    if len(result) > max_output:
        return result[:max_output] + "\n [TRUNCATED]"
    return result


if __name__ == "__main__":
    print(asyncio.run(run_bash(command="ls")))
