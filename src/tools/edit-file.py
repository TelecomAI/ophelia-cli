"""
Edit file command
"""

SCHEMA = {
    "name": "edit_file",
    "description": "Edit a file like following: Replace old_string with new_string in the file. old_string must be unique.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "the file path of the file to edit.",
            },
            "old_string": {
                "type": "string",
                "description": "old string to find and replace by the new one.",
            },
            "new_string": {
                "type": "string",
                "description": "new string to put in place of the old one.",
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    },
}


def edit_file_sync(file_path: str, old_string: str, new_string: str):
    try:
        with open(file_path, "r+", encoding="utf-8") as f:
            if not old_string:
                return "Error: The old string can't be empty."
            s = f.read()
            c = s.count(old_string)
            if c == 0:
                return "Error: The old string isn't in the file."
            if c > 1:
                return "Error: The old string was found more than one time."
            s = s.replace(old_string, new_string)
            f.seek(0)
            f.write(s)
            f.truncate()
            f.close()
    except (FileNotFoundError, PermissionError, IsADirectoryError) as e:
        return f"Error: {e}."
    return "The old string was succesfully replaced by the new one in the file."


async def edit_file(file_path: str, old_string: str, new_string: str):
    import asyncio

    return await asyncio.to_thread(edit_file_sync, file_path, old_string, new_string)
