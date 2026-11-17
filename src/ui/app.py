"""Interactive terminal UI controller for Ophelia."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.layout.containers import VSplit, Window
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.layout import Layout as PTLayout
from prompt_toolkit.layout.processors import AfterInput, ConditionalProcessor
from prompt_toolkit.output.color_depth import ColorDepth
from prompt_toolkit.styles import Style as PTStyle
from rich.console import Console, ConsoleRenderable, Group
from rich.live import Live

from src.ui.components import (
    BACKGROUND_COLOR,
    GRAY_TEXT_COLOR,
    HORIZONTAL_MARGIN,
    PROMPT_BACKGROUND_COLOR,
    PROMPT_PLACEHOLDER,
    TEXT_COLOR,
    assistant_response_component,
    blank_line,
    done_component,
    header_component,
    status_component,
    status_spinner,
    step_component,
    user_prompt_component,
)

DEFAULT_MODEL_NAME = "Claude Fable 5.1"
DEFAULT_CONTEXT_SIZE = "1M"
DEFAULT_QUOTE = "Fix the bug, you must.\nBlame the compiler, you shall not."

PREVIEW_PROMPT = (
    "Write a simple Python code that opens a CSV file and loads the data into a variable df."
)
PREVIEW_STEPS = (
    "I will verify the .csv file structure.",
    "I will create a Python script to load the data.",
)
PREVIEW_RESPONSE = (
    "Here is the standard Python code using the pandas library to read a CSV file:\n\n"
    "```python\n"
    "import pandas as pd\n\n"
    "# Load the CSV file into a DataFrame\n"
    "df = pd.read_csv('your_file.csv')\n"
    "```"
)


@dataclass
class TurnResult:
    """Data rendered for a completed assistant turn."""

    steps: list[str] = field(default_factory=list)
    elapsed: str = "0.0s"
    tokens: str = "0"
    tools_used: int = 0
    response: str = ""
    status_text: str = "Cooking ..."


def _bg_escape(hex_color: str) -> str:
    value = hex_color.lstrip("#")
    r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return f"\x1b[48;2;{r};{g};{b}m"


def _enter_alt_screen() -> None:
    """Switch to the alternate screen buffer so shell prompt / sticky scroll are hidden."""
    sys.stdout.write("\x1b[?1049h")
    sys.stdout.flush()


def _paint_terminal_canvas() -> None:
    """Clear the viewport and paint the entire canvas with #121029."""
    sys.stdout.write(f"\x1b]11;{BACKGROUND_COLOR}\x07{_bg_escape(BACKGROUND_COLOR)}\x1b[2J\x1b[H")
    sys.stdout.flush()


def _restore_terminal_canvas() -> None:
    """Reset terminal attributes, OSC 11 background, and exit alternate screen."""
    sys.stdout.write("\x1b]111\x07\x1b[0m\x1b[?1049l")
    sys.stdout.flush()


def _prompt_line_prefix(line_number: int, wrap_count: int) -> FormattedText:
    prefix = "> " if (line_number == 0 and wrap_count == 0) else "  "
    return FormattedText([(f"fg:{TEXT_COLOR} bg:{PROMPT_BACKGROUND_COLOR}", prefix)])


class _ResizeAwareApplication(Application[str | None]):
    """prompt_toolkit Application that re-renders scrollback content on terminal resize."""

    def __init__(
        self,
        *args: object,
        on_resize_redraw: Callable[[], None] | None = None,
        **kwargs: object,
    ) -> None:
        self._on_resize_redraw = on_resize_redraw
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    def _on_resize(self) -> None:
        self.renderer.erase(leave_alternate_screen=False)
        if self._on_resize_redraw is not None:
            self._on_resize_redraw()
        self._request_absolute_cursor_position()
        self._redraw()


def read_styled_prompt(
    placeholder: str = PROMPT_PLACEHOLDER,
    *,
    on_resize_redraw: Callable[[], None] | None = None,
) -> str | None:
    """Read interactive input inside the #21233E bar with #121029 margins."""
    buffer = Buffer(multiline=True)
    is_empty = Condition(lambda: buffer.text == "")

    kb = KeyBindings()

    @kb.add("enter")
    def _submit(event: KeyPressEvent) -> None:
        text = event.app.current_buffer.text.strip()
        if text:
            event.app.exit(result=text)

    @kb.add("escape", "enter")
    def _newline(event: KeyPressEvent) -> None:
        event.app.current_buffer.insert_text("\n")

    @kb.add("c-c")
    @kb.add("c-d")
    def _abort(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    pt_style = PTStyle.from_dict(
        {
            "canvas": f"bg:{BACKGROUND_COLOR}",
            "prompt-bg": f"bg:{PROMPT_BACKGROUND_COLOR} fg:{TEXT_COLOR}",
            "placeholder": f"bg:{PROMPT_BACKGROUND_COLOR} fg:{GRAY_TEXT_COLOR}",
        }
    )

    placeholder_processor = ConditionalProcessor(
        AfterInput(FormattedText([("class:placeholder", placeholder)])),
        filter=is_empty,
    )

    input_window = Window(
        content=BufferControl(
            buffer=buffer,
            input_processors=[placeholder_processor],
            key_bindings=kb,
        ),
        wrap_lines=True,
        dont_extend_height=True,
        style="class:prompt-bg",
        get_line_prefix=_prompt_line_prefix,
    )

    layout = PTLayout(
        VSplit(
            [
                Window(
                    width=HORIZONTAL_MARGIN,
                    dont_extend_height=True,
                    style="class:canvas",
                    char=" ",
                ),
                input_window,
                Window(width=1, dont_extend_height=True, style="class:prompt-bg", char=" "),
                Window(
                    width=HORIZONTAL_MARGIN,
                    dont_extend_height=True,
                    style="class:canvas",
                    char=" ",
                ),
            ]
        )
    )

    app = _ResizeAwareApplication(
        layout=layout,
        style=pt_style,
        color_depth=ColorDepth.DEPTH_24_BIT,
        full_screen=False,
        erase_when_done=True,
        on_resize_redraw=on_resize_redraw,
    )
    return app.run()


class OpheliaUI:
    """Controller for rendering the Ophelia terminal interface."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        context_size: str = DEFAULT_CONTEXT_SIZE,
        quote: str = DEFAULT_QUOTE,
        console: Console | None = None,
    ) -> None:
        self.model_name = model_name
        self.context_size = context_size
        self.quote = quote
        self.console = console or Console(color_system="truecolor")
        self._history: list[tuple[str, TurnResult, str]] = []

    def start(self) -> None:
        """Enter alternate screen, enforce #121029 canvas, and print the home header."""
        _enter_alt_screen()
        _paint_terminal_canvas()
        self.console.print(header_component(self.model_name, self.context_size, self.quote))

    def redraw(self) -> None:
        """Re-render the full canvas, header, and conversation history at the current width."""
        _paint_terminal_canvas()
        self.console.print(header_component(self.model_name, self.context_size, self.quote))
        for prompt_text, result, status_frame in self._history:
            self._print_turn(prompt_text, result, status_frame=status_frame)
            self.console.print(blank_line())

    def _print_turn(
        self,
        prompt_text: str,
        result: TurnResult,
        *,
        status_frame: str = "⠋",
    ) -> None:
        """Print a completed turn without mutating history."""
        self.console.print(user_prompt_component(prompt_text))
        self.console.print(blank_line())
        self.console.print(status_component(result.status_text, frame_char=status_frame))
        if result.steps:
            self.console.print(blank_line())
            for idx, step in enumerate(result.steps):
                if idx > 0:
                    self.console.print(blank_line())
                self.console.print(step_component(step))
        self.console.print(done_component(result.elapsed, result.tokens, result.tools_used))
        if result.response:
            self.console.print(blank_line())
            self.console.print(assistant_response_component(result.response))

    def render_turn(
        self,
        prompt_text: str,
        result: TurnResult,
        *,
        status_frame: str = "⠋",
    ) -> None:
        """Render a completed prompt + thinking status + steps + response turn."""
        self._history.append((prompt_text, result, status_frame))
        self._print_turn(prompt_text, result, status_frame=status_frame)

    def run_live_turn(
        self,
        prompt_text: str,
        handler: Callable[[Callable[[str], None]], TurnResult],
    ) -> None:
        """Print the prompt bar, animate the live spinner/steps, then render the response."""
        self.console.print(user_prompt_component(prompt_text))
        self.console.print(blank_line())

        steps: list[str] = []

        def build_live_view() -> Group:
            items: list[ConsoleRenderable] = [status_spinner("Cooking ...")]
            for step in steps:
                items.append(blank_line())
                items.append(step_component(step))
            return Group(*items)

        with Live(
            build_live_view(),
            console=self.console,
            refresh_per_second=12,
            transient=True,
        ) as live:

            def emit_step(step_text: str) -> None:
                steps.append(step_text)
                live.update(build_live_view(), refresh=True)

            result = handler(emit_step)

        final_steps = result.steps or steps
        stored_result = (
            result
            if result.steps
            else TurnResult(
                steps=list(final_steps),
                elapsed=result.elapsed,
                tokens=result.tokens,
                tools_used=result.tools_used,
                response=result.response,
                status_text=result.status_text,
            )
        )
        self._history.append((prompt_text, stored_result, "⠒"))
        self.console.print(status_component(result.status_text, frame_char="⠒"))
        if final_steps:
            self.console.print(blank_line())
            for idx, step in enumerate(final_steps):
                if idx > 0:
                    self.console.print(blank_line())
                self.console.print(step_component(step))
        self.console.print(done_component(result.elapsed, result.tokens, result.tools_used))
        if result.response:
            self.console.print(blank_line())
            self.console.print(assistant_response_component(result.response))
        self.console.print(blank_line())

    def render_preview(self) -> None:
        """Render the exact reference conversation shown in app-preview.png."""
        self._history.clear()
        self.start()
        self.render_turn(
            PREVIEW_PROMPT,
            TurnResult(
                steps=list(PREVIEW_STEPS),
                elapsed="12.5s",
                tokens="1k",
                tools_used=3,
                response=PREVIEW_RESPONSE,
            ),
            status_frame="⠒",
        )
        self.console.print(blank_line())

    def run_interactive(
        self,
        handler: Callable[[str, Callable[[str], None]], TurnResult] | None = None,
        *,
        show_preview: bool = False,
    ) -> None:
        """Run the interactive prompt loop in the styled terminal UI."""
        turn_handler = handler or _demo_turn_handler
        if show_preview:
            self.render_preview()
        else:
            self._history.clear()
            self.start()

        try:
            while True:
                user_input = read_styled_prompt(on_resize_redraw=self.redraw)
                if user_input is None or user_input in {"/exit", "/quit"}:
                    break
                self.run_live_turn(
                    user_input,
                    lambda emit, prompt=user_input: turn_handler(prompt, emit),
                )
        finally:
            _restore_terminal_canvas()


def _demo_turn_handler(prompt_text: str, emit_step: Callable[[str], None]) -> TurnResult:
    """Fallback simulated turn handler for UI testing before backend integration."""
    if "csv" in prompt_text.lower():
        time.sleep(0.35)
        emit_step(PREVIEW_STEPS[0])
        time.sleep(0.35)
        emit_step(PREVIEW_STEPS[1])
        time.sleep(0.25)
        return TurnResult(
            steps=list(PREVIEW_STEPS),
            elapsed="12.5s",
            tokens="1k",
            tools_used=3,
            response=PREVIEW_RESPONSE,
        )

    time.sleep(0.3)
    step = "Analyzing your request."
    emit_step(step)
    time.sleep(0.25)
    return TurnResult(
        steps=[step],
        elapsed="0.6s",
        tokens="128",
        tools_used=0,
        response=f"Received prompt: {prompt_text}",
    )


def main() -> None:
    """Entry point for running the standalone Ophelia UI preview or interactive shell."""
    parser = argparse.ArgumentParser(description="Run the Ophelia terminal UI.")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Render the reference app-preview conversation before the prompt bar.",
    )
    args = parser.parse_args()
    OpheliaUI().run_interactive(show_preview=args.preview)


if __name__ == "__main__":
    main()
