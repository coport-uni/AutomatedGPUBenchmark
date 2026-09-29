"""Line-oriented consoles: plain text and JSON Lines.

Plain mode prints one line per event and per sampling tick, so it reads
well in a log file or a CI job. The same lines go to ``console.log`` in
the result folder, which ``gpubench attach`` follows. JSON mode prints
one object per line for scripts (DevSpec 4.8).
"""

from __future__ import annotations

import json
from typing import Any, TextIO

from gpubench.collectors import telemetry
from gpubench.console.mode import Tick


def format_tick(tick: Tick) -> str:
    """Return the plain line of one sampling tick."""
    parts = [
        f"gpu{r['gpu_index']} {r['temp_gpu']} C {r['power_draw']} W "
        f"{r['clk_sm']} MHz"
        for r in tick.records
    ]
    return f"[{tick.phase} {tick.number}/{tick.total}] " + " | ".join(parts)


def verdict_lines(verdict: dict[str, Any]) -> list[str]:
    """Return one line per rule and per incomplete reason."""
    lines = []
    for rule in verdict.get("rules", []):
        grades = ", ".join(
            f"gpu{g['index']} {g['grade']} ({g['measured']})"
            for g in rule["gpus"]
        )
        lines.append(f"verdict: {rule['title']}: {grades}")
    for reason in verdict.get("incomplete_reasons", []):
        lines.append(f"verdict: incomplete: {reason}")
    return lines


class PlainConsole:
    """Write plain lines to a text stream, flushing each one."""

    def __init__(self, stream: TextIO) -> None:
        """Write to ``stream``."""
        self.stream = stream

    def write(self, line: str) -> None:
        """Write one line and flush it."""
        self.stream.write(line + "\n")
        self.stream.flush()

    def event(self, message: str) -> None:
        """Write the message as it is."""
        self.write(message)

    def tick(self, tick: Tick) -> None:
        """Write the tick line."""
        self.write(format_tick(tick))

    def verdict(self, verdict: dict[str, Any]) -> None:
        """Write one line per rule."""
        for line in verdict_lines(verdict):
            self.write(line)

    def close(self) -> None:
        """Nothing to finish; the stream belongs to the caller."""


class BufferedLog(PlainConsole):
    """Plain lines kept in memory until the log file exists.

    Preflight reports before the result folder exists; those lines are
    written to ``console.log`` as soon as ``open`` is called.
    """

    def __init__(self) -> None:
        """Start without a file."""
        self.pending: list[str] = []
        self.stream = None  # type: ignore[assignment]

    def open(self, path) -> None:
        """Start writing to ``path``, beginning with the buffered lines."""
        self.stream = path.open("a", encoding="utf-8", newline="\n")
        for line in self.pending:
            self.stream.write(line + "\n")
        self.pending.clear()
        self.stream.flush()

    def write(self, line: str) -> None:
        """Write to the file, or buffer until it is open."""
        if self.stream is None:
            self.pending.append(line)
        else:
            super().write(line)

    def close(self) -> None:
        """Close the file."""
        if self.stream is not None and not self.stream.closed:
            self.stream.close()


def tick_record(tick: Tick) -> dict[str, Any]:
    """Return the JSON object of one tick."""
    keys = ("temp_gpu", "power_draw", "clk_sm", "util_gpu", "mem_used")
    return {
        "type": "tick",
        "ts": telemetry.utc_timestamp(),
        "phase": tick.phase,
        "number": tick.number,
        "total": tick.total,
        "gpus": [
            {"index": r["gpu_index"], **{k: r.get(k) for k in keys}}
            for r in tick.records
        ],
    }


class JsonConsole:
    """Write one JSON object per line (JSON Lines)."""

    def __init__(self, stream: TextIO) -> None:
        """Write to ``stream``."""
        self.stream = stream

    def write(self, record: dict[str, Any]) -> None:
        """Write one object and flush it."""
        self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.stream.flush()

    def event(self, message: str) -> None:
        """Write an event object."""
        self.write(
            {
                "type": "event",
                "ts": telemetry.utc_timestamp(),
                "message": message,
            }
        )

    def tick(self, tick: Tick) -> None:
        """Write a tick object."""
        self.write(tick_record(tick))

    def verdict(self, verdict: dict[str, Any]) -> None:
        """Write the verdict with its rules, without per-GPU metrics."""
        self.write(
            {
                "type": "verdict",
                "ts": telemetry.utc_timestamp(),
                "verdict": verdict.get("verdict"),
                "exit_code": verdict.get("exit_code"),
                "incomplete_reasons": verdict.get("incomplete_reasons", []),
                "rules": verdict.get("rules", []),
            }
        )

    def close(self) -> None:
        """Nothing to finish."""
