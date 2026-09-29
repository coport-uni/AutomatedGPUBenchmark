"""Choose the console mode and fan events out to several consoles.

``docker exec -it`` gives the run a TTY, so ``auto`` selects the live
display; ``docker exec`` without ``-t`` and ``docker exec -d`` do not,
so ``auto`` falls back to plain lines (DevSpec 4.8).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, TextIO

output_modes = ("auto", "live", "plain", "json")
dumb_terminal = "dumb"


@dataclass(frozen=True)
class Tick:
    """One sampling tick: the phase, its progress, and the readings."""

    phase: str
    number: int
    total: int
    records: Sequence[dict[str, Any]] = field(default_factory=tuple)


class Console(Protocol):
    """Receiver of everything a run reports while it runs."""

    def event(self, message: str) -> None:
        """Report one line of progress, such as a phase start."""

    def tick(self, tick: Tick) -> None:
        """Report one sampling tick."""

    def verdict(self, verdict: dict[str, Any]) -> None:
        """Report the evaluation of the run."""

    def close(self) -> None:
        """Finish the output, for example by leaving the live block."""


def is_tty(stream: TextIO) -> bool:
    """Return whether ``stream`` is an interactive terminal."""
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


def resolve(requested: str, stream: TextIO, env: dict | None = None) -> str:
    """Return the concrete mode for ``requested``.

    ``auto`` becomes ``live`` on a TTY whose ``TERM`` is not ``dumb``,
    and ``plain`` everywhere else.

    Raises:
        ValueError: If ``requested`` is not a known mode.
    """
    if requested not in output_modes:
        raise ValueError(f"unknown output mode {requested!r}")
    if requested != "auto":
        return requested
    environment = os.environ if env is None else env
    if is_tty(stream) and environment.get("TERM") != dumb_terminal:
        return "live"
    return "plain"


class ConsoleGroup:
    """Forward every call to each member console in order."""

    def __init__(self, members: Sequence[Console] = ()) -> None:
        """Start with ``members``; more can be added later."""
        self.members: list[Console] = list(members)

    def add(self, member: Console) -> None:
        """Add ``member`` for all following calls."""
        self.members.append(member)

    def event(self, message: str) -> None:
        """Forward an event."""
        for member in self.members:
            member.event(message)

    def tick(self, tick: Tick) -> None:
        """Forward a tick."""
        for member in self.members:
            member.tick(tick)

    def verdict(self, verdict: dict[str, Any]) -> None:
        """Forward the verdict."""
        for member in self.members:
            member.verdict(verdict)

    def close(self) -> None:
        """Close every member."""
        for member in self.members:
            member.close()


def create(mode: str, stream: TextIO) -> Console:
    """Return the console for a resolved ``mode`` writing to ``stream``."""
    from gpubench.console import live, plain

    if mode == "live":
        return live.LiveConsole(stream)
    if mode == "json":
        return plain.JsonConsole(stream)
    return plain.PlainConsole(stream)
