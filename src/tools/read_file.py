import asyncio

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
                    "minimum": 1,
                    "description": "First line to read (1-indexed, inclusive).",
                },
                "line_end": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Last line to read (1-indexed, inclusive).",
                },
            },
            "required": ["file_path"],
        },
    },
}


def _read_file(
    file_path: str,
    line_start: int | None = None,
    line_end: int | None = None,
) -> str:
    """Read a UTF-8 file, optionally selecting a 1-indexed inclusive line range."""
    if not isinstance(file_path, str):
        raise TypeError("file_path must be a string")

    bounds = (("line_start", line_start), ("line_end", line_end))
    for name, value in bounds:
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            raise TypeError(f"{name} must be an integer")
    for name, value in bounds:
        if value is not None and value < 1:
            raise ValueError(f"{name} must be greater than or equal to 1")
    if line_start is not None and line_end is not None and line_end < line_start:
        raise ValueError("line_end must be greater than or equal to line_start")

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

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
    """Read a UTF-8 file asynchronously, raising errors for invalid input or read failures."""
    return await asyncio.to_thread(_read_file, file_path, line_start, line_end)
