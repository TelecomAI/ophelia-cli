"""Command-line entry point for Ophelia."""

from rich.console import Console

console = Console()


def main() -> None:
    """Start the Ophelia CLI."""
    console.print("[bold cyan]Ophelia CLI[/bold cyan]")
    console.print("Your AI coding assistant is ready to be built.")
