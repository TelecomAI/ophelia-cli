import asyncio
from pathlib import Path

SCHEMA = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": (
            "Write content to a file, overwriting it if it exists. "
            "Missing parent directories are created automatically."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to write.",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file.",
                },
            },
            "required": ["file_path", "content"],
        },
    },
}


def _write_file(file_path: str, content: str) -> str:
    """Write content to file, creating parent dirs if needed.

    Args:
        file_path (str): path to the file
        content (str): content to write

    Returns:
        str: success message
    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fd:
        fd.write(content)

    return "Successfully written content to file"


async def write_file(file_path: str, content: str) -> str:
    """Write content to file asynchronously, creating parent directories if needed.

    Args:
        file_path (str): path to the file
        content (str): content to write

    Returns:
        str: success message
    """
    return await asyncio.to_thread(_write_file, file_path, content)
