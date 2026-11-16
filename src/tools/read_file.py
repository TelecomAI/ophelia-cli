import asyncio
from pathlib import Path

SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": (
            "Read and return the text content of a file. "
            "Optionally specify line_start and line_end (1-indexed, inclusive) to read a specific range."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to read.",
                },
                "line_start": {
                    "type": "integer",
                    "description": "First line to read (1-indexed, inclusive).",
                },
                "line_end": {
                    "type": "integer",
                    "description": "Last line to read (1-indexed, inclusive).",
                },
            },
            "required": ["file_path"],
        },
    },
}


def _read_file_sync(
    file_path: str,
    line_start: int | None = None,
    line_end: int | None = None,
) -> str:
    """Read content from a file synchronously, with optional 1-indexed line slicing."""
    path = Path(file_path)

    if not path.exists():
        return f"Error: File '{file_path}' does not exist."
    if not path.is_file():
        return f"Error: '{file_path}' is a directory, not a file."

    if line_start is not None and line_start < 1:
        return "Error: line_start must be greater than or equal to 1."
    if line_start is not None and line_end is not None and line_end < line_start:
        return "Error: line_end must be greater than or equal to line_start."

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Error: '{file_path}' is a binary file or not valid UTF-8."
    except PermissionError:
        return f"Error: Permission denied when reading '{file_path}'."
    except OSError as exc:
        return f"Error reading '{file_path}': {exc}"

    if line_start is None and line_end is None:
        return content

    lines = content.splitlines(keepends=True)
    start_idx = (line_start - 1) if line_start is not None else 0
    end_idx = line_end if line_end is not None else len(lines)
    return "".join(lines[start_idx:end_idx])


async def read_file(
    file_path: str,
    line_start: int | None = None,
    line_end: int | None = None,
) -> str:
    """Read content from a file asynchronously."""
    return await asyncio.to_thread(_read_file_sync, file_path, line_start, line_end)
