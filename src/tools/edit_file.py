import asyncio

"""
Edit file command
"""

SCHEMA = {
    "type": "function",
    "function": {
        "name": "edit_file",
        "description": "Edit a file like following: Replace old_string with new_string in the file. old_string must be unique.",
        "parameters": {
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
    },
}


def _edit_file(file_path: str, old_string: str, new_string: str):
    """Edit a file by replacing old_string with new_string. old_string must be unique.

    Args:
        file_path (str): path to the file
        old_string (str): string to replace
        new_string (str): replacement string

    Returns:
        str: success message
    """
    # check file path
    if not isinstance(file_path, str):
        raise TypeError("file_path must be a string")

    # check old string
    if not isinstance(old_string, str):
        raise TypeError("old_string must be a string")
    if not old_string:
        raise ValueError("old_string can't be empty")

    # check new string
    if not isinstance(new_string, str):
        raise TypeError("new_string must be a string")

    with open(file_path, "r+", encoding="utf-8", newline="") as f:
        s = f.read()
        first = s.find(old_string)
        if first == -1:
            raise ValueError(f"old_string not found in the file {file_path}")
        if s.find(old_string, first + 1) != -1:
            raise ValueError("old_string must be unique")
        s = s.replace(old_string, new_string)
        f.seek(0)
        f.write(s)
        f.truncate()
        f.close()

    return "The old string was succesfully replaced by the new one in the file."


async def edit_file(file_path: str, old_string: str, new_string: str):
    return await asyncio.to_thread(_edit_file, file_path, old_string, new_string)
