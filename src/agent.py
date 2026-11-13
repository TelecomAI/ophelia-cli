from events import Event
from typing import AsyncGenerator

# TODO: issue #16 Define the system prompt
SYSTEM_PROMPT: str = """You are a coding assistant that helps developers with software engineering tasks.

You have access to tools for reading files, writing files, searching for files, listing directories, and running bash commands. Use these tools to explore the codebase, understand the code, and make changes as requested.

When given a task:
1. Understand what is being asked
2. Explore the relevant code using your tools
3. Make the necessary changes
4. Verify your work

Be concise and direct in your responses."""


class Agent:

    def __init__(
        self,
        provider: Provider,  # TODO: issue #12 Implement the Provider class which standardize llm calls and responses
        tools: dict | None = None,
        system_prompt: str = SYSTEM_PROMPT,
        max_turns: int = 20,
    ) -> None:
        """Initialize the agent.

        Args:
            provider (Provider): The provider to use.
            system_prompt (str, optional): The system prompt. Defaults to SYSTEM_PROMPT.
            max_turns (int, optional): Max number of turns. Defaults to 20.
        """

        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")

        self.provider = provider
        self.tools = tools or {}
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.history: list[dict] = []

    async def run(self, user_input: str) -> AsyncGenerator[Event]:
        """
        Run one turn of the agent.
        """
        pass
