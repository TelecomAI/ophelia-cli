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
                "description": "Max output length.",
                "default": 2000,
            },
        },
        "required": ["command"],
    },
}


async def run_bash(command: str, timeout: int = 30, max_output: int = 2000) -> str:
    """Run a bash command with a timeout and return combined stdout/stderr"""

    if not isinstance(timeout, int) or timeout < 0:
        raise ValueError("The timeout parameter of run_bash tool must be a positif integer")

    if command:
        import asyncio

        proc = await asyncio.create_subprocess_shell(
            cmd=command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )

        try:
            # this can throw a TimeoutError
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        except TimeoutError:
            proc.kill()
            stdout, stderr = await proc.communicate()
            # we re-throw the error, cause the error catching logic must be handled elsewhere
            raise TimeoutError(f"Command {command!r} timed out after {timeout} seconds")

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

    return "No command is given"


if __name__ == "__main__":
    import asyncio

    print(asyncio.run(run_bash(command="ls")))
