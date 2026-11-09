import asyncio
from pathlib import Path


def _write_file_sync(file_path: str, content: str) -> str:
    try:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fd:
            fd.write(content)
        return "Successfully written to file"

    except OSError as e:
        return f"Problem writing file: {e}"
    

async def write_file(file_path: str, content: str) -> str:
    """Write content to file, creating parent directories if needed."""
    return await asyncio.to_thread(_write_file_sync, file_path, content)
