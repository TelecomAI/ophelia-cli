import asyncio
import contextlib
import ctypes
import ntpath
import os
import shutil
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_IS_WINDOWS = sys.platform == "win32"

_CREATE_SUSPENDED = 0x00000004
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_THREAD_SUSPEND_RESUME = 0x0002
_TH32CS_SNAPPROCESS = 0x00000002
_TH32CS_SNAPTHREAD = 0x00000004
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_STILL_ACTIVE = 259
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_PIPE_DRAIN_TIMEOUT = 2.0
_FALLBACK_DRAIN_TIMEOUT = 0.2


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

    # Last resort: the WSL launcher is a real bash. USES_WSL reports it, and
    # shell_path() translates Windows paths for it.
    return shutil.which("bash")


BASH_PATH = _find_bash()
USES_WSL = BASH_PATH is not None and _is_wsl_launcher(BASH_PATH)
"""True when ``BASH_PATH`` is the Windows launcher for a Linux bash in WSL."""


def _is_absolute_drive_path(drive: str, rest: str) -> bool:
    """True for ``C:\\work`` and ``C:/work``, False for ``C:work`` and shares."""
    return len(drive) == 2 and drive[1] == ":" and rest.startswith(("\\", "/"))


def shell_path(path: str) -> str:
    """Return ``path`` the way the shell that ``run_bash`` starts sees it.

    A bash from WSL is a Linux shell, and Linux sees the ``C:`` drive as
    ``/mnt/c``, so ``C:\\work`` is ``/mnt/c/work``. Git Bash on Windows is a
    Windows program whose shell would eat the backslashes, so it gets
    ``C:/work`` instead. Other shells see the path unchanged.
    """
    drive, rest = ntpath.splitdrive(path)
    if not _is_absolute_drive_path(drive, rest):
        # Relative paths, drive-relative paths, and network shares are left alone.
        return path

    if USES_WSL:
        return f"/mnt/{drive[0].lower()}{rest.replace('\\', '/')}"
    if _IS_WINDOWS and BASH_PATH:
        return (drive + rest).replace("\\", "/")
    return path


@dataclass(frozen=True)
class _Win32Api:
    kernel32: Any
    DWORD: Any
    FILETIME: Any
    THREADENTRY32: Any
    PROCESSENTRY32W: Any
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION: Any


_WIN32_API: _Win32Api | None = None


def _get_win32() -> _Win32Api | None:
    """Return cached kernel32 bindings and Win32 struct classes on Windows, or None elsewhere."""
    global _WIN32_API
    if not _IS_WINDOWS:
        return None
    if _WIN32_API is not None:
        return _WIN32_API

    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None

    from ctypes import wintypes

    class _FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    class _THREADENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = windll.kernel32
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE

    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE

    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL

    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL

    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL

    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL

    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL

    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE

    kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
    kernel32.Thread32First.restype = wintypes.BOOL

    kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
    kernel32.Thread32Next.restype = wintypes.BOOL

    kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenThread.restype = wintypes.HANDLE

    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.ResumeThread.restype = wintypes.DWORD

    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL

    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    _WIN32_API = _Win32Api(
        kernel32=kernel32,
        DWORD=wintypes.DWORD,
        FILETIME=_FILETIME,
        THREADENTRY32=_THREADENTRY32,
        PROCESSENTRY32W=_PROCESSENTRY32W,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION=_JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    )
    return _WIN32_API


def _get_handle_creation_time(win32: _Win32Api, handle: int) -> int | None:
    creation = win32.FILETIME()
    exit_time = win32.FILETIME()
    kernel_time = win32.FILETIME()
    user_time = win32.FILETIME()
    if not win32.kernel32.GetProcessTimes(
        handle,
        ctypes.byref(creation),
        ctypes.byref(exit_time),
        ctypes.byref(kernel_time),
        ctypes.byref(user_time),
    ):
        return None
    return (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)


def _get_windows_process_creation_time(pid: int) -> int | None:
    """Return the 64-bit FILETIME creation timestamp for `pid` on Windows."""
    win32 = _get_win32()
    if win32 is None:
        return None

    handle = win32.kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        return _get_handle_creation_time(win32, int(handle))
    finally:
        win32.kernel32.CloseHandle(handle)


def _attach_windows_job(pid: int) -> int | None:
    """Attach `pid` to a new Windows Job Object so its entire process tree can be killed."""
    win32 = _get_win32()
    if win32 is None:
        return None

    job = win32.kernel32.CreateJobObjectW(None, None)
    if not job:
        return None

    limit_info = win32.JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limit_info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32.kernel32.SetInformationJobObject(
        job,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
        ctypes.byref(limit_info),
        ctypes.sizeof(limit_info),
    )

    proc_handle = win32.kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
    if not proc_handle:
        win32.kernel32.CloseHandle(job)
        return None

    try:
        if not win32.kernel32.AssignProcessToJobObject(job, proc_handle):
            win32.kernel32.CloseHandle(job)
            return None
    finally:
        win32.kernel32.CloseHandle(proc_handle)

    return int(job)


def _resume_windows_process(pid: int) -> bool:
    """Resume all suspended threads belonging to `pid`."""
    win32 = _get_win32()
    if win32 is None:
        return False

    snap = win32.kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if not snap or snap == _INVALID_HANDLE_VALUE:
        return False

    resumed = False
    try:
        entry = win32.THREADENTRY32()
        entry.dwSize = ctypes.sizeof(entry)
        has_entry = bool(win32.kernel32.Thread32First(snap, ctypes.byref(entry)))
        while has_entry:
            if int(entry.th32OwnerProcessID) == pid:
                thread_handle = win32.kernel32.OpenThread(
                    _THREAD_SUSPEND_RESUME, False, entry.th32ThreadID
                )
                if thread_handle:
                    try:
                        res = win32.kernel32.ResumeThread(thread_handle)
                        if int(res) != 0xFFFFFFFF:
                            resumed = True
                    finally:
                        win32.kernel32.CloseHandle(thread_handle)
            has_entry = bool(win32.kernel32.Thread32Next(snap, ctypes.byref(entry)))
    finally:
        win32.kernel32.CloseHandle(snap)

    return resumed


def _kill_windows_descendants_snapshot(pid: int, root_start_time: int | None) -> bool:
    """Walk the Windows process snapshot to terminate `pid` and surviving descendants."""
    win32 = _get_win32()
    if win32 is None:
        return False

    snap = win32.kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snap or snap == _INVALID_HANDLE_VALUE:
        return False

    children_by_parent: dict[int, list[int]] = {}
    try:
        entry = win32.PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        has_entry = bool(win32.kernel32.Process32FirstW(snap, ctypes.byref(entry)))
        while has_entry:
            proc_id = int(entry.th32ProcessID)
            parent_id = int(entry.th32ParentProcessID)
            if proc_id != 0 and proc_id != parent_id:
                children_by_parent.setdefault(parent_id, []).append(proc_id)
            has_entry = bool(win32.kernel32.Process32NextW(snap, ctypes.byref(entry)))
    finally:
        win32.kernel32.CloseHandle(snap)

    handles_to_kill: list[int] = []
    max_root_child_start: int | None = None

    root_handle = win32.kernel32.OpenProcess(
        _PROCESS_TERMINATE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if root_handle:
        actual_root_start = _get_handle_creation_time(win32, int(root_handle))
        exit_code = win32.DWORD()
        root_alive = (
            win32.kernel32.GetExitCodeProcess(root_handle, ctypes.byref(exit_code))
            and exit_code.value == _STILL_ACTIVE
        )
        if (
            root_start_time is not None
            and actual_root_start is not None
            and actual_root_start != root_start_time
        ):
            # `pid` exited and was recycled by an unrelated newer process.
            max_root_child_start = actual_root_start
            win32.kernel32.CloseHandle(root_handle)
        elif not root_alive:
            win32.kernel32.CloseHandle(root_handle)
        else:
            handles_to_kill.append(int(root_handle))

    queue: list[tuple[int, int | None, int | None]] = [(pid, root_start_time, max_root_child_start)]
    visited = {pid}

    while queue:
        curr_pid, min_start, max_start = queue.pop(0)
        for child_pid in children_by_parent.get(curr_pid, ()):
            if child_pid in visited:
                continue
            visited.add(child_pid)

            child_handle = win32.kernel32.OpenProcess(
                _PROCESS_TERMINATE | _PROCESS_QUERY_LIMITED_INFORMATION, False, child_pid
            )
            if not child_handle:
                continue

            child_start = _get_handle_creation_time(win32, int(child_handle))
            if min_start is not None and child_start is not None and child_start < min_start:
                win32.kernel32.CloseHandle(child_handle)
                continue
            if max_start is not None and child_start is not None and child_start >= max_start:
                win32.kernel32.CloseHandle(child_handle)
                continue

            handles_to_kill.append(int(child_handle))
            queue.append((child_pid, child_start if child_start is not None else min_start, None))

    killed_any = False
    try:
        for handle in handles_to_kill:
            if win32.kernel32.TerminateProcess(handle, 1):
                killed_any = True
            else:
                exit_code = win32.DWORD()
                if (
                    win32.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                    and exit_code.value != _STILL_ACTIVE
                ):
                    killed_any = True
    finally:
        for handle in handles_to_kill:
            win32.kernel32.CloseHandle(handle)

    return killed_any


async def _kill_process_tree(
    pid: int,
    job_handle: int | None,
    proc_start_time: int | None = None,
) -> bool:
    """Terminate `pid` and all of its descendants across POSIX and Windows.

    Returns True when full process-tree containment/termination succeeded, or False
    when fallback cleanup could not confirm all descendants were terminated.
    """
    if _IS_WINDOWS:
        win32 = _get_win32()
        if (
            job_handle is not None
            and win32 is not None
            and win32.kernel32.TerminateJobObject(job_handle, 1)
        ):
            return True

        snapshot_killed = _kill_windows_descendants_snapshot(pid, proc_start_time)

        taskkill_ok = False
        with contextlib.suppress(FileNotFoundError, OSError):
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/T",
                "/F",
                "/PID",
                str(pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(killer.wait(), timeout=_PIPE_DRAIN_TIMEOUT)
                taskkill_ok = killer.returncode == 0
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    killer.kill()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(killer.wait(), timeout=_FALLBACK_DRAIN_TIMEOUT)

        if not taskkill_ok:
            snapshot_killed = (
                _kill_windows_descendants_snapshot(pid, proc_start_time) or snapshot_killed
            )

        return taskkill_ok or snapshot_killed

    with contextlib.suppress(ProcessLookupError):
        # start_new_session=True sets PGID to proc.pid; os.getpgid() can fail once reaped
        os.killpg(pid, signal.SIGKILL)
    return True


async def _drain_process(
    communication: asyncio.Future[tuple[bytes, bytes]],
    proc: Any,
    *,
    tree_killed: bool,
) -> tuple[bytes, bytes]:
    """Wait for the pipe reader to finish after termination without hanging.

    The reader collects everything the process printed, including the output from
    before it was killed. Returns empty bytes when the pipes could not be drained
    in time, which happens when a leaked descendant keeps them open.
    """
    drain_timeout = _PIPE_DRAIN_TIMEOUT if tree_killed else _FALLBACK_DRAIN_TIMEOUT
    try:
        # Shielded so a slow drain leaves the reader alive until we cancel it below.
        return await asyncio.wait_for(asyncio.shield(communication), timeout=drain_timeout)
    except TimeoutError:
        communication.cancel()
        transport = getattr(proc, "_transport", None)
        if transport is not None:
            transport.close()
        with contextlib.suppress(TimeoutError, ProcessLookupError):
            await asyncio.wait_for(proc.wait(), timeout=_FALLBACK_DRAIN_TIMEOUT)
        return b"", b""


def _format_partial_output(stdout: bytes, stderr: bytes) -> str:
    """Format what a timed-out command managed to print before it was killed."""
    sections = []
    if stdout:
        sections.append("STDOUT:\n" + stdout.decode("utf-8", errors="replace"))
    if stderr:
        sections.append("STDERR:\n" + stderr.decode("utf-8", errors="replace"))
    return "\n\n".join(sections)


"""
Run shell commands
"""

DEFAULT_TIMEOUT = 30
DEFAULT_MAX_OUTPUT = 8000
# Long enough for a slow build, short enough that a mistake in the units can't
# keep a command running for hours.
MAX_TIMEOUT = 3600

SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_bash",
        "description": "Run a shell command and return the output.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        f"Timeout in seconds. Defaults to {DEFAULT_TIMEOUT}; at most {MAX_TIMEOUT}."
                    ),
                    "default": DEFAULT_TIMEOUT,
                },
                "max_output": {
                    "type": "integer",
                    "description": (
                        f"Max output length in characters. Defaults to {DEFAULT_MAX_OUTPUT}."
                    ),
                    "default": DEFAULT_MAX_OUTPUT,
                },
            },
            "required": ["command"],
        },
    },
}


_TRUNCATION_MARKER = "\n\n[... TRUNCATED ...]\n\n"


def _truncate(text: str, max_length: int) -> str:
    """Cut `text` to `max_length` characters, keeping its start and its end.

    Errors and test failures are usually in the last lines, so keeping only the
    start would hide the useful part of the output.
    """
    if len(text) <= max_length:
        return text
    if max_length <= len(_TRUNCATION_MARKER):
        return text[:max_length]

    budget = max_length - len(_TRUNCATION_MARKER)
    head = budget // 2
    tail = budget - head
    return text[:head] + _TRUNCATION_MARKER + text[-tail:]


def _positive_int(name: str, value: object) -> int:
    """Return `value` as a positive int, or raise ValueError naming `name`.

    ``bool`` is rejected explicitly because it is a subclass of ``int``, so
    ``timeout=True`` would otherwise pass as 1.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"The {name} parameter of run_bash tool must be a positive integer")
    return value


async def run_bash(
    command: str,
    timeout: int = DEFAULT_TIMEOUT,
    max_output: int = DEFAULT_MAX_OUTPUT,
) -> str:
    """Run a shell command with a timeout and return combined stdout/stderr of max_output length."""

    timeout = _positive_int("timeout", timeout)
    if timeout > MAX_TIMEOUT:
        raise ValueError(
            f"The timeout parameter of run_bash tool must be at most {MAX_TIMEOUT} seconds"
        )
    max_output = _positive_int("max_output", max_output)

    if not command or not command.strip():
        return "No command is given"

    spawn_kwargs: dict[str, Any] = {
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "start_new_session": not _IS_WINDOWS,
    }
    if _IS_WINDOWS:
        spawn_kwargs["creationflags"] = _CREATE_SUSPENDED

    if BASH_PATH:
        proc = await asyncio.create_subprocess_exec(
            BASH_PATH,
            "-c",
            command,
            **spawn_kwargs,
        )
    else:
        proc = await asyncio.create_subprocess_shell(
            cmd=command,
            **spawn_kwargs,
        )

    job_handle: int | None = None
    proc_start_time: int | None = None
    completed = False
    timed_out = False
    partial_stdout = b""
    partial_stderr = b""
    # Reading in a separate task keeps the output when the wait times out: cancelling
    # communicate() would close the pipes and lose what the process already printed.
    communication = asyncio.ensure_future(proc.communicate())
    try:
        if _IS_WINDOWS:
            proc_start_time = _get_windows_process_creation_time(proc.pid)
            job_handle = _attach_windows_job(proc.pid)
            if not _resume_windows_process(proc.pid):
                raise OSError(f"Failed to resume suspended Windows process {proc.pid}")

        done, _ = await asyncio.wait({communication}, timeout=timeout)
        if communication in done:
            stdout, stderr = communication.result()
            completed = True
        else:
            timed_out = True
    finally:
        try:
            if not completed:
                tree_killed = await _kill_process_tree(proc.pid, job_handle, proc_start_time)
                partial_stdout, partial_stderr = await _drain_process(
                    communication, proc, tree_killed=tree_killed
                )
        finally:
            if job_handle is not None and _IS_WINDOWS:
                win32 = _get_win32()
                if win32 is not None:
                    win32.kernel32.CloseHandle(job_handle)

    if timed_out:
        # The caller handles this error; the output printed before the kill is the
        # only clue about where the command hung, so it goes in the message.
        message = f"Command {command!r} timed out after {timeout} seconds"
        partial = _format_partial_output(partial_stdout, partial_stderr)
        if partial:
            message += f"\n\nOutput before the timeout:\n{_truncate(partial, max_output)}"
        raise TimeoutError(message)

    result = (
        f"Command: {command!r}\n"
        f"Exit code: {proc.returncode}\n\n"
        "STDOUT:\n"
        f"{stdout.decode('utf-8', errors='replace')}\n\n"
        "STDERR:\n"
        f"{stderr.decode('utf-8', errors='replace')}\n"
    )

    return _truncate(result, max_output)


if __name__ == "__main__":
    print(asyncio.run(run_bash(command="ls")))
