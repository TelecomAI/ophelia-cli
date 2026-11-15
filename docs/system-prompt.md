# Ophelia's system prompt

This document explains how Ophelia's system prompt is built and why it looks the way it does. It covers issue #16.

The system prompt is the first message of every request Ophelia sends to the LLM. The agent sends it again on every turn, together with the tool definitions and the conversation so far. It tells the model who it is, how to work, and how to use its tools, so it shapes almost everything the agent does. It also means that every word costs tokens on every request.

## Motivation

Ophelia needs instructions that make the model behave like a careful coding assistant. It should explore before changing code, check its work, respect the user's approvals, and resist instructions hidden in files.

The placeholder prompt in `src/agent.py`, on the `feat/8-add-events` branch, was a starting point taken from Owain Lewis' nano-agent, according to the issue. It had problems:

- It described tools Ophelia doesn't have ("searching for files, listing directories"). A model told that a tool exists may try to call it.
- It said nothing about the user's machine. For example, the model couldn't know that commands run in `cmd.exe` on Windows.
- It had no guidance on approvals, destructive commands, secrets, or prompt injection.

## How it works now

The prompt is assembled from three parts, always in this order:

1. **Main instructions**, in `src/prompts/system_prompt.md`. They never change while Ophelia runs.
2. **Tool guidelines**, one file per tool in `src/prompts/tools/<tool_name>.md`. Only the guidelines of tools the agent really has are included.
3. **An Environment section**, built when Ophelia starts: working directory, operating system, shell, and today's date.

The agent should build its prompt like this:

```python
from src.prompts import build_system_prompt

system_prompt = build_system_prompt(self.tools)  # tool names, or the agent's tool dict
```

`SYSTEM_PROMPT` still exists, but it holds only the main instructions, without tool guidelines or the Environment section.

| File | What it holds |
|---|---|
| `src/prompts/system_prompt.md` | The main instructions |
| `src/prompts/tools/*.md` | Advice for each tool: `run_bash`, `read_file`, `write_file`, `edit_file`, `spawn_agent` |
| `src/prompts/system_prompt.py` | `build_system_prompt`, `Environment`, and helpers |
| `tests/prompts/system_prompt_test.py` | Unit tests for the rules below |
| `scripts/check_system_prompt.py` | A live check of the model's behavior |

The main instructions have these sections, in this order:

- **Identity:** what Ophelia is, and that the user sees and approves tool calls.
- **How you work:**
  - keep going until the task is done;
  - look before acting;
  - plan;
  - make small changes;
  - check your work;
  - recover from failures;
  - ask when something is unclear.
- **Using your tools:** general advice that applies to every tool.
- **Safety:** denied tool calls, destructive actions, secrets, and prompt injection.
- **Communicating:** style, and what the final message should contain.

The main instructions are about 480 words. With every tool and the Environment section, the prompt is about 790 words, roughly 1,100 tokens (estimated from its length).

## Design decisions

Each decision below gives the reason for it and where that reason comes from.

1. **A compact, structured prompt.** We compared three options:
   - minimal: about 100 words, like the placeholder;
   - compact and structured: about 500 words, the one we chose;
   - comprehensive: several thousand words, like OpenAI's Codex prompts, which are 3,400 to 3,500 words each.

   We chose the compact one for three reasons:
   - **The default model is small.** Our default, `openai/gpt-oss-20b`, is a small model, and the IFScale study found that models follow instructions less reliably as the number of instructions grows. The study tested report writing, not coding agents, so treat it as a trend, not an exact number.
   - **Every word is sent on every request.** Groq lists 8K tokens per minute for `gpt-oss-20b`. Our whole prompt is about one seventh of that, while a comprehensive one would take about half of it on the first request of a session.
   - **A short prompt is easier to work with.** The team can review it, explain it, and change it more easily.

   This follows Anthropic's context engineering advice: aim for the "right altitude" between rigid if-then rules and vague guidance, use the smallest set of information that fully describes the expected behavior, and add instructions when testing shows a failure.

   We left out, and could add if testing shows a need: step-by-step approaches for common tasks such as bug fixes or reviews, examples of good plans and final messages, and advice on how much initiative to take in new projects.
2. **How to work comes first, style comes last.** IFScale found that models favor instructions that appear early. A test checks the section order.
3. **Three reminders for agents, worded calmly.** OpenAI's GPT-4.1 guide found that three reminders raised its SWE-bench Verified score by about 20%: keep going until the task is done, use tools instead of guessing, and plan before acting. All three are in "How you work". They are worded calmly because Anthropic's prompting guide warns that strongly worded versions can make recent Claude models use tools too much.
4. **No shouted rules.** Anthropic's guide says recent models over-react to rules like "CRITICAL: you MUST" and recommends plain wording. A test keeps words such as MUST and CRITICAL out of the prompt.
5. **Sections with Markdown headers.** Anthropic's context engineering article recommends splitting a prompt into clear sections, with XML tags or Markdown headers, and notes that the exact format matters less as models improve. OpenAI's GPT-4.1 guide also uses Markdown sections. Markdown works across providers.
6. **Tool advice only for tools that exist.** The main text never names a tool. Tool names appear only in the guidelines of tools the agent was given, so the prompt can't describe a tool the model can't call, which was the placeholder's main problem. Tests check this for every tool.
7. **Tool definitions go through the API, not the prompt.** Tool names and parameters are sent in the API's `tools` field. The prompt only adds advice on using the tools. OpenAI's GPT-4.1 guide measured about 2% better results this way than with tools described inside the prompt. Anthropic's "Building effective agents" adds that tool descriptions deserve as much care as the prompt itself.
8. **Nothing about calling several tools at once.** Groq doesn't support parallel tool calls for `openai/gpt-oss-20b`. Models that do support them, such as Claude, use them well without being asked, so saying nothing is correct for every model.
9. **A runtime Environment section, placed last.** The model can't know the user's machine. The `run_bash` tool starts commands with `asyncio.create_subprocess_shell`, which uses `cmd.exe` on Windows and `/bin/sh` elsewhere, so the model needs the shell name to write commands that work. Every model also has a training cutoff, so it needs today's date. The section comes last because of prompt caching. Groq reuses a cached prompt only when its beginning matches exactly, so its docs recommend putting the parts that never change first and the changing parts last. Cached tokens cost 50% less and don't count toward Groq's rate limits.
10. **File contents and command output are treated as data.** This defends against prompt injection, which is text in a file or a command's output that tries to give the model orders. OpenAI's harmony format, which gpt-oss models were trained on, ranks tool messages lowest (system, developer, user, assistant, then tool), so this rule matches how the model was trained.
11. **The prompt text lives in Markdown files.** That keeps prose out of Python code, GitHub shows it readably in pull requests, and the tool files can be included one by one. Codex and OpenCode also keep their prompts in separate files.
12. **A new `src/prompts/` package instead of editing `src/agent.py`.** `agent.py` only exists on the unmerged `feat/8-add-events` branch, so editing it here would clash with that work. The agent only needs to import `build_system_prompt`.
13. **One prompt for every model, for now.** We have one default model to test against. Codex and OpenCode both keep a separate prompt per model family, so that's the likely next step once we test other models. Add model-specific text only for failures we actually observe.

## Supporting other models

Most of the prompt is independent of the model:

- the tool list that matches the real tools;
- the Environment section;
- the order with the fixed text first, which suits OpenAI, Anthropic, Google, and Groq, since they all cache the start of a prompt;
- Markdown sections, calm wording, and the safety rules.

Three things are tuned for `openai/gpt-oss-20b` on Groq:

- saying nothing about parallel tool calls;
- the short length, since stronger models handle longer prompts well;
- the calm wording of the reminders.

To support more models, keep this shared prompt. Add small additions per model, or per ability (for example "can call several tools at once"), when tests show a model needs them. These abilities should come from the Provider class (#12). `scripts/check_system_prompt.py` takes a `--model` option, so the same scenarios can be run against each model.

## Validation

**Unit tests** (`uv run python -m pytest tests/prompts`). There are 25 tests. They check that:

- the main text names no tool, and the prompt mentions only the tools it was given;
- every known tool has guidelines;
- unknown or unsafe tool names (such as `../system_prompt`) are ignored;
- tool order and duplicates don't change the prompt;
- the Environment section is always last, and only that section changes between machines;
- the shell is reported the way `run_bash` really runs commands, on Windows and elsewhere;
- the sections come in the designed order;
- the prompt stays under 1,000 words;
- no shouted words appear.

**Live check** (`uv run python scripts/check_system_prompt.py`). It sends four scenarios to the model and checks only its next move, without running any tool:

1. It reads or searches before fixing a typo.
2. It explores the project before answering "what does this project do?".
3. It doesn't run a command that a file tells it to run (prompt injection).
4. It asks the user instead of retrying a denied tool call.

It needs a `GROQ_API_KEY` in `.env`. *Results: not run yet.*

**Not yet possible:** an end-to-end test of the agent loop. That needs the Agent class (#11) and the Provider (#12).

## Limitations and follow-ups

- **A compact prompt leaves some behavior to the model.** There are no examples and no task-by-task advice. If testing or real use shows a gap, add one specific rule for it rather than a whole section.
- **Untested on the real model:** run the live check before relying on the prompt.
- **`spawn_agent` guidelines are a first draft:** the owner of #6 should adjust them to the real tool.
- **Tool descriptions are part of the prompt too:** for example, `edit_file`'s description could be clearer. That's up to each tool's owner.
- **`run_bash` runs `cmd.exe` on Windows** despite its name. Because of this, two of its existing tests fail on Windows (they use `printf` and `;`). It's worth a separate issue.
- **Future work:**
  - a shorter prompt for sub-agents (with #6);
  - short reminders that the agent loop adds to the conversation, which Claude Code does;
  - support for project instruction files such as `AGENTS.md`.
- **The Agent (#11) should call `build_system_prompt(self.tools)`.** Using `SYSTEM_PROMPT` alone leaves out the tool guidelines and the Environment section.

## Changing the prompt

- **Main instructions:** edit `src/prompts/system_prompt.md`, and keep tool names out of it.
- **Keep it compact:** the size test fails above 1,000 words, which is meant to start a conversation, not to be raised quietly.
- **A new tool:** add `src/prompts/tools/<tool_name>.md`. Start it with `## <tool_name>`, mention no other tool by name, and add the tool to `KNOWN_TOOLS` in the tests.
- **After a change:** run the tests and the live check. On Windows, `uv run pytest` can be blocked by Smart App Control, but `uv run python -m pytest` works.

## References

- Anthropic, [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) (September 2025): the right altitude, sections, and a minimal set of information.
- Anthropic, [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) (December 2024): keep agents simple, design tools carefully, and use feedback from the environment.
- Anthropic, [Prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices): calm wording and avoiding over-prompting.
- OpenAI, [GPT-4.1 prompting guide](https://developers.openai.com/cookbook/examples/gpt4-1_prompting_guide): reminders for agents, passing tools through the API, and prompt structure.
- OpenAI, [Harmony response format](https://developers.openai.com/cookbook/articles/openai-harmony): how gpt-oss ranks system, developer, user, and tool messages.
- Groq: [prompt caching](https://console.groq.com/docs/prompt-caching), [rate limits](https://console.groq.com/docs/rate-limits), [tool use](https://console.groq.com/docs/tool-use).
- Jaroslawicz et al., [How Many Instructions Can LLMs Follow at Once?](https://arxiv.org/abs/2507.11538) (2025), the IFScale benchmark.
- OpenAI Codex prompts: [codex-rs/core](https://github.com/openai/codex/tree/main/codex-rs/core). OpenCode prompts: [system-prompt](https://github.com/anomalyco/opencode/tree/dev/packages/core/src/plugin/system-prompt).
