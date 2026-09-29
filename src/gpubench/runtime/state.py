"""Progress of the current run in ``<results-root>/.state.json``.

``gpubench status``, ``attach``, and ``stop`` run in other ``docker
exec`` processes; this file tells them which process and result folder
belong to the run and how far it got. It is replaced atomically, so a
reader never sees half a file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from gpubench.collectors import telemetry
from gpubench.console.mode import Tick

state_file = ".state.json"
status_running = "running"
status_finished = "finished"
status_interrupted = "interrupted"


def write_state(root: Path, state: dict[str, Any]) -> None:
    """Replace the state file of ``root`` with ``state``."""
    path = root / state_file
    temporary = path.with_name(f"{state_file}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_state(root: Path) -> dict[str, Any] | None:
    """Return the state of ``root``, or None when there is none."""
    path = root / state_file
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


class StateConsole:
    """Console member that mirrors the run's progress into the file."""

    def __init__(self, root: Path, pid: int | None = None) -> None:
        """Write the state of results folder ``root``."""
        self.root = root
        self.state: dict[str, Any] = {
            "pid": os.getpid() if pid is None else pid,
            "status": status_running,
            "started": telemetry.utc_timestamp(),
            "result_dir": None,
            "phase": "preflight",
            "number": 0,
            "total": 0,
            "last_event": "",
            "gpus": [],
        }
        self.flush()

    def flush(self) -> None:
        """Write the current state, stamped with the time."""
        self.state["updated"] = telemetry.utc_timestamp()
        write_state(self.root, self.state)

    def set_result_dir(self, result_dir: Path) -> None:
        """Record the result folder once preflight created it."""
        self.state["result_dir"] = str(result_dir)
        self.flush()

    def event(self, message: str) -> None:
        """Remember the latest event."""
        self.state["last_event"] = message
        self.flush()

    def tick(self, tick: Tick) -> None:
        """Record the phase, its progress, and the latest readings."""
        keys = ("temp_gpu", "power_draw", "clk_sm", "util_gpu")
        self.state.update(
            phase=tick.phase,
            number=tick.number,
            total=tick.total,
            gpus=[
                {"index": r["gpu_index"], **{k: r.get(k) for k in keys}}
                for r in tick.records
            ],
        )
        self.flush()

    def verdict(self, verdict: dict[str, Any]) -> None:
        """Record the verdict and exit code."""
        self.state["verdict"] = verdict.get("verdict")
        self.state["exit_code"] = verdict.get("exit_code")
        self.flush()

    def finish(self, status: str, exit_code: int) -> None:
        """Mark the run as ended with ``status`` and ``exit_code``."""
        self.state["status"] = status
        self.state["exit_code"] = exit_code
        self.flush()

    def close(self) -> None:
        """Nothing to finish; ``finish`` records the end."""
