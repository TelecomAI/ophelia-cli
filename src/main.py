"""Command-line entry point for Ophelia."""

from rich.console import Console

from src.ui.components import BACKGROUND_COLOR, home_layout

MODEL_NAME = "Claude Fable 5.1"
CONTEXT_SIZE = "1M"
QUOTE = "Fix the bug, you must.\nBlame the compiler, you shall not."


def main() -> None:
    """Start the Ophelia CLI in the alternate screen."""
    console = Console()
    with console.screen(hide_cursor=True) as screen:
        screen.update(home_layout(MODEL_NAME, CONTEXT_SIZE, QUOTE))
        input()
