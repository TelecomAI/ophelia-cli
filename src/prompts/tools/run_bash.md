## run_bash

Runs one shell command and returns its exit code and output.

- Each call starts a new shell in the working directory, so `cd` and variables don't carry over. Chain steps that depend on each other in one command.
- Use the shell named in the Environment section: usually `cmd.exe` on Windows, and a POSIX `sh` elsewhere.
- Long output is cut off and ends with `[TRUNCATED]`. Narrow the command, or raise `max_output`.
- Commands stop after 30 seconds by default. Raise `timeout` for slow ones, such as test suites or installs.
- Commands can't read keyboard input, so avoid interactive programs and anything that keeps running.
