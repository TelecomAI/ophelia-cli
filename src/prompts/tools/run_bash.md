## run_bash

Runs one shell command and returns its exit code and output.

- Each call starts a new shell in the working directory, so `cd` and variables don't carry over. Chain steps that depend on each other in one command.
- Use the shell named in the Environment section, usually bash. If it is `cmd.exe`, use `dir`, `type`, and `findstr` rather than `ls`, `cat`, and `grep`.
- Read and change files with the file tools when you have them, rather than with commands such as `type` or `sed`.
- Long output is cut off and ends with `[TRUNCATED]`. Narrow the command, or raise `max_output`.
- Commands stop after 30 seconds by default. For slow ones, such as test suites or installs, raise `timeout`. It is in seconds, not milliseconds: 120 means two minutes.
- Commands can't read keyboard input, so avoid interactive programs and anything that keeps running.
