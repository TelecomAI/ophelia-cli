"""Rich renderables for the Ophelia terminal UI."""

from __future__ import annotations

from typing import ClassVar

from pygments.style import Style as PygmentsStyle
from pygments.token import (
    Comment,
    Keyword,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
)
from pygments.token import (
    Text as TokenText,
)
from rich import box
from rich.console import ConsoleRenderable, Group
from rich.layout import Layout
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.spinner import Spinner
from rich.style import Style
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

LOGO_COLOR = "#98BBEA"
BACKGROUND_COLOR = "#121029"
BORDER_COLOR = "#3181DD"
ACCENT_COLOR = "#3181DD"
GRAY_TEXT_COLOR = "#7B7878"
TEXT_COLOR = "#FFFFFF"
PROMPT_BACKGROUND_COLOR = "#21233E"
CODE_BACKGROUND_COLOR = "#21233E"
STRING_COLOR = "#38E13B"

BG_STYLE = Style(bgcolor=BACKGROUND_COLOR)
PROMPT_BG_STYLE = Style(bgcolor=PROMPT_BACKGROUND_COLOR)

FOOTER_TEXT = "Ophelia is an open source CLI developed by Télécom IA"
PROMPT_PLACEHOLDER = "Ask Ophelia..."

HORIZONTAL_MARGIN = 2

LOGO_WIDTH = 22
LOGO_LINES = tuple(
    line.ljust(LOGO_WIDTH)
    for line in (
        " ░▒" + "█" * 16 + "▒░ ",
        "",
        "    ░▒" + "█" * 10 + "▒░",
        "",
        "░" + "█" * 20 + "░",
        "░██░" + " " * 14 + "░██░",
        "     ▒██ ░██░ ██▒",
        "     ▒██ ░██░ ██▒",
        "     ▒██ ░██░ ██▒",
        "     ▒██ ░██░ ██▒",
        "     ▒██ ░██░",
        "     ▒██",
        "     ▒██",
    )
)

LOGO_HEIGHT = len(LOGO_LINES)

HEADER_HEIGHT = LOGO_HEIGHT + 2
PROMPT_HEIGHT = 1


class OpheliaSyntaxStyle(PygmentsStyle):
    """Pygments theme matching the Ophelia code block palette."""

    background_color = CODE_BACKGROUND_COLOR
    default_style = TEXT_COLOR
    styles: ClassVar[dict[object, str]] = {
        TokenText: TEXT_COLOR,
        Keyword: ACCENT_COLOR,
        Keyword.Namespace: ACCENT_COLOR,
        Operator.Word: ACCENT_COLOR,
        Name: TEXT_COLOR,
        Operator: TEXT_COLOR,
        Punctuation: TEXT_COLOR,
        Number: TEXT_COLOR,
        String: STRING_COLOR,
        Comment: GRAY_TEXT_COLOR,
    }


class _OpheliaSyntax(Syntax):
    """Syntax helper using the Ophelia Pygments theme on #21233E."""


def logo_component() -> Text:
    """Return the Ophelia pillar logo."""
    return Text(
        "\n".join(LOGO_LINES),
        style=f"{LOGO_COLOR} on {BACKGROUND_COLOR}",
        no_wrap=True,
    )


def info_component(model_name: str, context_size: str, quote: str) -> Panel:
    """Return the bordered info box with model, context size and quote."""
    body = Group(
        Text("Ophelia", style=f"bold {TEXT_COLOR} on {BACKGROUND_COLOR}"),
        Text("", style=BG_STYLE),
        Text(model_name, style=f"{GRAY_TEXT_COLOR} on {BACKGROUND_COLOR}"),
        Text(f"{context_size} Context", style=f"{GRAY_TEXT_COLOR} on {BACKGROUND_COLOR}"),
        Text("", style=BG_STYLE),
        Text("", style=BG_STYLE),
        Text(quote, style=f"{TEXT_COLOR} on {BACKGROUND_COLOR}"),
        Text("", style=BG_STYLE),
        Text("", style=BG_STYLE),
        Text(FOOTER_TEXT, style=f"{GRAY_TEXT_COLOR} on {BACKGROUND_COLOR}"),
    )
    return Panel(
        body,
        box=box.SQUARE,
        border_style=f"{BORDER_COLOR} on {BACKGROUND_COLOR}",
        style=BG_STYLE,
        padding=(0, 1),
        expand=True,
    )


def header_component(model_name: str, context_size: str, quote: str) -> Padding:
    """Return the logo and info box side by side."""
    grid = Table.grid(expand=True, padding=(0, 2), pad_edge=False)
    grid.add_column(width=LOGO_WIDTH)
    grid.add_column(ratio=1)
    grid.add_row(logo_component(), info_component(model_name, context_size, quote))
    return Padding(grid, (1, HORIZONTAL_MARGIN, 1, HORIZONTAL_MARGIN), style=BG_STYLE)


def _prompt_bar(text: str, text_color: str) -> Padding:
    """Return a prompt bar aligned flush with the header margins."""
    row = Table.grid(expand=True, padding=(0, 1), pad_edge=False)
    row.add_column(width=1)
    row.add_column(ratio=1)
    row.add_row(
        Text(">", style=f"{TEXT_COLOR} on {PROMPT_BACKGROUND_COLOR}"),
        Text(text, style=f"{text_color} on {PROMPT_BACKGROUND_COLOR}"),
    )
    inner = Padding(row, (0, 1, 0, 0), style=PROMPT_BG_STYLE)
    return Padding(inner, (0, HORIZONTAL_MARGIN), style=BG_STYLE)


def prompt_component(placeholder: str = PROMPT_PLACEHOLDER) -> Padding:
    """Return the idle input prompt bar with placeholder text."""
    return _prompt_bar(placeholder, GRAY_TEXT_COLOR)


def user_prompt_component(text: str) -> Padding:
    """Return a submitted user prompt bar."""
    return _prompt_bar(text, TEXT_COLOR)


def status_spinner(text: str = "Cooking ...") -> Padding:
    """Return an animated braille spinner line for live status updates."""
    spinner = Spinner(
        "dots",
        text=Text(text, style=f"{ACCENT_COLOR} on {BACKGROUND_COLOR}"),
        style=f"{ACCENT_COLOR} on {BACKGROUND_COLOR}",
    )
    return Padding(spinner, (0, HORIZONTAL_MARGIN), style=BG_STYLE)


def status_component(text: str = "Cooking ...", frame_char: str = "⠋") -> Padding:
    """Return a static braille status line (for non-live rendering or snapshots)."""
    line = Text.assemble(
        (f"{frame_char} ", f"{ACCENT_COLOR} on {BACKGROUND_COLOR}"),
        (text, f"{ACCENT_COLOR} on {BACKGROUND_COLOR}"),
    )
    return Padding(line, (0, HORIZONTAL_MARGIN), style=BG_STYLE)


def step_component(text: str) -> Padding:
    """Return a dim bulleted step/thought line."""
    row = Table.grid(expand=True, padding=(0, 1), pad_edge=False)
    row.add_column(width=1)
    row.add_column(ratio=1)
    row.add_row(
        Text("*", style=f"{GRAY_TEXT_COLOR} on {BACKGROUND_COLOR}"),
        Text(text, style=f"{GRAY_TEXT_COLOR} on {BACKGROUND_COLOR}"),
    )
    return Padding(row, (0, HORIZONTAL_MARGIN), style=BG_STYLE)


def done_component(
    elapsed: str,
    tokens: str,
    tools_used: int,
) -> Padding:
    """Return the completion summary line directly beneath the final step."""
    tool_label = "tool" if tools_used == 1 else "tools"
    summary = f"Done ({elapsed} • {tokens} Tokens • {tools_used} {tool_label} used)"
    row = Table.grid(expand=True, padding=(0, 1), pad_edge=False)
    row.add_column(width=1)
    row.add_column(ratio=1)
    row.add_row(
        Text("⎿", style=f"{TEXT_COLOR} on {BACKGROUND_COLOR}"),
        Text(summary, style=f"{TEXT_COLOR} on {BACKGROUND_COLOR}"),
    )
    return Padding(row, (0, HORIZONTAL_MARGIN), style=BG_STYLE)


def prose_component(text: str, *, markdown: bool = False) -> Padding:
    """Return assistant response prose on the #121029 canvas."""
    renderable: ConsoleRenderable = (
        Markdown(text, style=f"{TEXT_COLOR} on {BACKGROUND_COLOR}")
        if markdown
        else Text(text, style=f"{TEXT_COLOR} on {BACKGROUND_COLOR}")
    )
    return Padding(renderable, (0, HORIZONTAL_MARGIN), style=BG_STYLE)


def code_block_component(code: str, language: str = "python", start_line: int = 1) -> Padding:
    """Return a #21233E syntax-highlighted code block with line numbers."""
    clean_code = code.rstrip("\n")
    syntax = _OpheliaSyntax(
        clean_code,
        language,
        theme=OpheliaSyntaxStyle,
        background_color=CODE_BACKGROUND_COLOR,
        word_wrap=True,
    )
    highlighted = syntax.highlight(clean_code)
    lines = highlighted.split("\n")
    # Remove trailing empty split artifact only if split added an extra empty line
    if len(lines) > clean_code.count("\n") + 1:
        lines.pop()

    last_line_no = start_line + len(lines) - 1
    num_width = len(str(last_line_no))
    gutter_width = num_width + 2  # " {num} "

    grid = Table.grid(expand=True, padding=(0, 0), pad_edge=False)
    grid.add_column(width=gutter_width, no_wrap=True)
    grid.add_column(ratio=1)

    gutter_style = f"{GRAY_TEXT_COLOR} on {CODE_BACKGROUND_COLOR}"
    for offset, line_text in enumerate(lines):
        line_no = start_line + offset
        line_text.stylize(PROMPT_BG_STYLE)
        gutter = Text(f" {line_no:>{num_width}} ", style=gutter_style)
        grid.add_row(gutter, line_text)

    inner = Padding(grid, (0, 1, 0, 0), style=PROMPT_BG_STYLE)
    return Padding(inner, (0, HORIZONTAL_MARGIN), style=BG_STYLE)


def assistant_response_component(content: str) -> Group:
    """Render assistant prose and fenced code blocks with Ophelia styling."""
    parts: list[ConsoleRenderable] = []
    lines = content.splitlines()
    prose_buf: list[str] = []
    code_buf: list[str] = []
    in_code = False
    code_lang = "text"

    def flush_prose() -> None:
        text = "\n".join(prose_buf).strip("\n")
        prose_buf.clear()
        if text:
            if parts:
                parts.append(blank_line())
            parts.append(prose_component(text))

    for line in lines:
        stripped = line.strip()
        if not in_code and stripped.startswith("```"):
            flush_prose()
            in_code = True
            code_lang = stripped[3:].strip() or "text"
            code_buf.clear()
        elif in_code and stripped == "```":
            if parts:
                parts.append(blank_line())
            parts.append(code_block_component("\n".join(code_buf), language=code_lang))
            in_code = False
            code_buf.clear()
        elif in_code:
            code_buf.append(line)
        else:
            prose_buf.append(line)

    if in_code and code_buf:
        if parts:
            parts.append(blank_line())
        parts.append(code_block_component("\n".join(code_buf), language=code_lang))
    else:
        flush_prose()

    return Group(*parts)


def blank_line() -> Padding:
    """Return a full-width blank line painted with #121029."""
    return Padding(Text("", style=BG_STYLE), 0, style=BG_STYLE)


def home_layout(model_name: str, context_size: str, quote: str) -> Layout:
    """Return the full-screen home layout: header, prompt, and #121029 canvas."""
    layout = Layout()
    layout.split_column(
        Layout(
            header_component(model_name, context_size, quote),
            name="header",
            size=HEADER_HEIGHT,
        ),
        Layout(prompt_component(), name="prompt", size=PROMPT_HEIGHT),
        Layout(blank_line(), name="body"),
    )
    return layout
