"""Live TTY console for ``docker exec -it`` (DevSpec 4.8).

Events scroll like plain lines. Below them a status block with the
phase, its progress, and one line per GPU is redrawn in place every
tick with ANSI escape codes, which every terminal ``docker exec -it``
attaches to understands. No curses or third-party library is needed.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TextIO

from gpubench.console.mode import Tick
from gpubench.console.plain import verdict_lines

bar_width = 24
bar_done = "#"
bar_todo = "-"
seconds_per_minute = 60
escape = "\x1b["
clear_to_end = f"{escape}J"
grade_styles = {
    "PASS": f"{escape}32m",
    "WARN": f"{escape}33m",
    "FAIL": f"{escape}31m",
}
reset_style = f"{escape}0m"


def cursor_up_lines(count: int) -> str:
    """Return the code that moves to the start of ``count`` lines up."""
    return f"{escape}{count}F"


def progress_bar(number: int, total: int) -> str:
    """Return ``[####----]`` for ``number`` of ``total``."""
    done = bar_width * number // total if total else bar_width
    return "[" + bar_done * done + bar_todo * (bar_width - done) + "]"


def format_elapsed(seconds: float) -> str:
    """Return ``MM:SS``."""
    whole = int(seconds)
    return f"{whole // seconds_per_minute:02d}:{whole % seconds_per_minute:02d}"


def format_gpu(record: dict[str, Any]) -> str:
    """Return the status line of one GPU."""

    def value(key: str, unit: str, width: int) -> str:
        reading = record.get(key)
        text = "n/a" if reading is None else f"{reading}"
        return f"{text:>{width}} {unit}"

    return (
        f"  gpu{record['gpu_index']}  "
        f"{value('temp_gpu', 'C', 3)}  "
        f"{value('power_draw', 'W', 7)}  "
        f"{value('clk_sm', 'MHz', 5)}  "
        f"util {value('util_gpu', '%', 3)}"
    )


class LiveConsole:
    """Scrolling events above a status block redrawn in place."""

    def __init__(
        self, stream: TextIO, clock: Callable[[], float] = time.monotonic
    ) -> None:
        """Write to ``stream``; ``clock`` measures the elapsed time."""
        self.stream = stream
        self.clock = clock
        self.started = clock()
        self.block: list[str] = []
        self.drawn = 0

    def erase_block(self) -> None:
        """Remove the status block drawn last."""
        if self.drawn:
            self.stream.write(cursor_up_lines(self.drawn) + clear_to_end)
            self.drawn = 0

    def draw_block(self) -> None:
        """Draw the current status block below the events."""
        for line in self.block:
            self.stream.write(line + "\n")
        self.drawn = len(self.block)
        self.stream.flush()

    def event(self, message: str) -> None:
        """Print ``message`` above the status block."""
        self.erase_block()
        self.stream.write(message + "\n")
        self.draw_block()

    def tick(self, tick: Tick) -> None:
        """Replace the status block with this tick's readings."""
        elapsed = format_elapsed(self.clock() - self.started)
        header = (
            f"{tick.phase:<12} {progress_bar(tick.number, tick.total)} "
            f"{tick.number}/{tick.total}  elapsed {elapsed}"
        )
        self.erase_block()
        self.block = [header, *(format_gpu(r) for r in tick.records)]
        self.draw_block()

    def verdict(self, verdict: dict[str, Any]) -> None:
        """Print the rule lines and the coloured run verdict."""
        self.erase_block()
        self.block = []
        for line in verdict_lines(verdict):
            self.stream.write(line + "\n")
        grade = str(verdict.get("verdict"))
        style = grade_styles.get(grade, "")
        closing = reset_style if style else ""
        self.stream.write(f"verdict: {style}{grade}{closing}\n")
        self.stream.flush()

    def close(self) -> None:
        """Leave the last status block on screen."""
        self.stream.flush()
