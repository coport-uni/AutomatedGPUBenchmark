"""Signal handling during a run (DevSpec 4.8).

SIGINT (Ctrl+C in ``docker exec -it``) and SIGTERM (``gpubench stop``,
``docker stop``) both raise ``Interrupted`` so the orchestrator can stop
the tools and still write an INCOMPLETE report. SIGHUP, sent when an
SSH session closes, is ignored so the run continues. While the report
is being written, further stop signals only print a notice.
"""

from __future__ import annotations

import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

stop_signals = (signal.SIGINT, signal.SIGTERM)
hangup_signal = getattr(signal, "SIGHUP", None)


class Interrupted(BaseException):
    """A stop signal arrived; ``name`` is its name, such as SIGINT.

    It derives from BaseException, like KeyboardInterrupt, so ordinary
    ``except Exception`` blocks in the phases do not swallow it.
    """

    def __init__(self, name: str) -> None:
        """Remember the signal name."""
        super().__init__(name)
        self.name = name


def signal_name(number: int) -> str:
    """Return ``SIGINT`` style names for signal ``number``."""
    try:
        return signal.Signals(number).name
    except ValueError:
        return f"signal {number}"


def raise_interrupted(number: int, frame: Any) -> None:
    """Signal handler that turns a stop signal into ``Interrupted``."""
    raise Interrupted(signal_name(number))


def install(handler: Callable[[int, Any], None]) -> dict[int, Any]:
    """Set ``handler`` for the stop signals and ignore SIGHUP.

    Returns:
        The previous handlers, for ``restore``.
    """
    previous = {}
    for number in stop_signals:
        previous[number] = signal.signal(number, handler)
    if hangup_signal is not None:
        previous[hangup_signal] = signal.signal(hangup_signal, signal.SIG_IGN)
    return previous


def restore(previous: dict[int, Any]) -> None:
    """Put back the handlers returned by ``install``."""
    for number, handler in previous.items():
        signal.signal(number, handler)


@contextmanager
def run_signals() -> Iterator[None]:
    """Raise ``Interrupted`` on SIGINT and SIGTERM; ignore SIGHUP."""
    previous = install(raise_interrupted)
    try:
        yield
    finally:
        restore(previous)


@contextmanager
def shielded(notify: Callable[[str], None]) -> Iterator[None]:
    """Keep stop signals from interrupting cleanup; report them instead."""

    def note(number: int, frame: Any) -> None:
        name = signal_name(number)
        notify(f"run: {name} ignored while the report is written")

    previous = install(note)
    try:
        yield
    finally:
        restore(previous)
