"""Rich renderables for the Ophelia home screen."""

from rich import box
from rich.console import Group
from rich.layout import Layout
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

LOGO_COLOR = "#98BBEA"
BACKGROUND_COLOR = "#373C66"
BORDER_COLOR = "#3181DD"
GRAY_TEXT_COLOR = "#7B7878"
TEXT_COLOR = "white"
PROMPT_BACKGROUND_COLOR = "#21243E"

FOOTER_TEXT = "Ophelia is an open source CLI developed by Télécom IA"
PROMPT_PLACEHOLDER = "Ask Ophelia..."

LOGO_WIDTH = 21
LOGO_LINES = tuple(
    line.ljust(LOGO_WIDTH)
    for line in (
        " ▒" + "█" * 17 + "▒ ",
        "",
        "    ▒" + "█" * 11 + "▒",
        "",
        "▒" + "█" * 19 + "▒",
        " ▒█▒" + " " * 13 + "▒█▒ ",
        "    ▒█▒ ▒██▒ ▒█▒",
        "    ▒█▒ ▒██▒ ▒█▒",
        "    ▒█▒ ▒██▒ ▒█▒",
        "    ▒█▒ ▒██▒ ▒█▒",
        "    ▒█▒ ▒██▒",
        "    ▒█▒",
        "    ▒█▒",
    )
)

LOGO_HEIGHT = len(LOGO_LINES)

HEADER_HEIGHT = LOGO_HEIGHT + 1
PROMPT_HEIGHT = 3


def logo_component() -> Text:
    """Return the Ophelia pillar logo."""
    return Text("\n".join(LOGO_LINES), style=LOGO_COLOR, no_wrap=True)


def info_component(model_name: str, context_size: str, quote: str) -> Panel:
    """Return the bordered info box with model, context size and quote."""
    body = Group(
        Text("Ophelia", style=f"bold {TEXT_COLOR}"),
        Text(""),
        Text(model_name, style=GRAY_TEXT_COLOR),
        Text(f"{context_size} Context", style=GRAY_TEXT_COLOR),
        Text(""),
        Text(""),
        Text(quote, style=TEXT_COLOR),
        Text(""),
        Text(""),
        Text(FOOTER_TEXT, style=GRAY_TEXT_COLOR),
    )
    return Panel(
        body,
        box=box.SQUARE,
        border_style=BORDER_COLOR,
        style=f"on {BACKGROUND_COLOR}",
        expand=True,
    )


def header_component(model_name: str, context_size: str, quote: str) -> Padding:
    """Return the logo and info box side by side."""
    grid = Table.grid(expand=True, padding=(0, 2))
    grid.add_column(width=LOGO_WIDTH)
    grid.add_column(ratio=1)
    grid.add_row(logo_component(), info_component(model_name, context_size, quote))
    return Padding(grid, (1, 2, 0, 2))


def prompt_component(placeholder: str = PROMPT_PLACEHOLDER) -> Padding:
    """Return the input prompt bar."""
    row = Table.grid(expand=True, padding=(0, 1))
    row.add_column(width=1)
    row.add_column(ratio=1)
    row.add_row(Text(">", style=TEXT_COLOR), Text(placeholder, style=GRAY_TEXT_COLOR))
    return Padding(row, (1, 2), style=f"on {PROMPT_BACKGROUND_COLOR}")


def home_layout(model_name: str, context_size: str, quote: str) -> Layout:
    """Return the full-screen home layout: header, empty body, prompt."""
    layout = Layout()
    layout.split_column(
        Layout(
            header_component(model_name, context_size, quote),
            name="header",
            size=HEADER_HEIGHT,
        ),
        Layout(prompt_component(), name="prompt", size=PROMPT_HEIGHT),
    )
    return layout
