"""``gpubench status``, ``attach``, and ``stop`` (DevSpec 4.8, README 7).

A long run is started with ``docker exec -d``; these commands run in
further ``docker exec`` processes of the same container. They find the
run through ``<results-root>/.lock`` (held while it runs) and
``.state.json`` (its pid, result folder, and progress).
"""

from __future__ import annotations

import os
import signal
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from gpubench.runtime import lock
from gpubench.runtime import state as run_state
from gpubench.runtime.exit_codes import ExitCode

console_log_file = "console.log"
poll_interval_s = 0.5
# Waiting for preflight to create the result folder.
result_dir_timeout_s = 60.0
# gpu_burn may take its stop grace plus -stts to exit, and the
# INCOMPLETE report takes about ten seconds to render.
stop_timeout_s = 180.0


def say(out: TextIO, message: str) -> None:
    """Write one line and flush it."""
    out.write(message + "\n")
    out.flush()


def describe_gpu(gpu: dict[str, Any]) -> str:
    """Return the status line of one GPU reading."""
    return (
        f"gpu{gpu['index']} {gpu.get('temp_gpu')} C "
        f"{gpu.get('power_draw')} W {gpu.get('clk_sm')} MHz "
        f"util {gpu.get('util_gpu')} %"
    )


def describe_last(out: TextIO, state: dict[str, Any] | None, name: str) -> None:
    """Print the outcome of the last run, if any."""
    if not state or not state.get("result_dir"):
        return
    say(
        out,
        f"{name}: last run {state['result_dir']}: {state.get('status')}, "
        f"verdict {state.get('verdict', 'none')}, "
        f"exit {state.get('exit_code')}",
    )


def status(root: Path, out: TextIO) -> ExitCode:
    """Print the progress of the running test, or the last outcome."""
    state = run_state.read_state(root)
    if not lock.is_held(root):
        say(out, "status: no run in progress")
        describe_last(out, state, "status")
        return ExitCode.PASS
    if state is None:
        say(out, "status: a run holds the lock but has no state yet")
        return ExitCode.PASS
    say(
        out,
        f"status: running, pid {state['pid']}, started {state['started']}, "
        f"results {state.get('result_dir') or 'not created yet'}",
    )
    say(
        out,
        f"status: phase {state['phase']} {state['number']}/{state['total']}",
    )
    if state.get("last_event"):
        say(out, f"status: last event: {state['last_event']}")
    for gpu in state.get("gpus", []):
        say(out, f"status: {describe_gpu(gpu)}")
    return ExitCode.PASS


def wait_for_result_dir(
    root: Path, clock: Callable[[], float], sleep: Callable[[float], None]
) -> Path | None:
    """Wait until the running test has created its result folder."""
    deadline = clock() + result_dir_timeout_s
    while clock() < deadline:
        state = run_state.read_state(root) or {}
        if state.get("result_dir"):
            return Path(state["result_dir"])
        if not lock.is_held(root):
            return None
        sleep(poll_interval_s)
    return None


def attach(
    root: Path,
    out: TextIO,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> ExitCode:
    """Follow ``console.log`` of the running test until it ends.

    Ctrl+C detaches without stopping the run.

    Returns:
        The exit code of the run once it ended, ``ExitCode.PASS`` after
        a detach, or ``ExitCode.ERROR`` when no run is in progress.
    """
    if not lock.is_held(root):
        say(out, "attach: no run in progress")
        describe_last(out, run_state.read_state(root), "attach")
        return ExitCode.ERROR
    result_dir = wait_for_result_dir(root, clock, sleep)
    if result_dir is None:
        say(out, "attach: the run ended before it created a result folder")
        return ExitCode.ERROR
    path = result_dir / console_log_file
    say(out, f"attach: following {path}; Ctrl+C detaches")
    try:
        position = 0
        while True:
            running = lock.is_held(root)
            if path.is_file():
                with path.open(encoding="utf-8", errors="replace") as log:
                    log.seek(position)
                    text = log.read()
                    position = log.tell()
                if text:
                    out.write(text)
                    out.flush()
            if not running:
                break
            sleep(poll_interval_s)
    except KeyboardInterrupt:
        say(out, "attach: detached; the run continues")
        return ExitCode.PASS
    state = run_state.read_state(root) or {}
    code = state.get("exit_code", int(ExitCode.ERROR))
    say(out, f"attach: run ended with exit {code}")
    return ExitCode(code)


def stop(
    root: Path,
    out: TextIO,
    kill: Callable[[int, int], None] = os.kill,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> ExitCode:
    """Send SIGTERM to the running test and wait until it has ended.

    The run then stops its tools and writes an INCOMPLETE report.

    Returns:
        ``ExitCode.PASS`` when the run ended, ``ExitCode.ERROR`` when no
        run was in progress or it did not end within the timeout.
    """
    state = run_state.read_state(root)
    if not lock.is_held(root) or state is None:
        say(out, "stop: no run in progress")
        return ExitCode.ERROR
    pid = int(state["pid"])
    say(
        out,
        f"stop: sending SIGTERM to pid {pid} "
        f"(results {state.get('result_dir') or 'not created yet'})",
    )
    try:
        kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        say(out, f"stop: pid {pid} no longer exists")
        return ExitCode.ERROR
    deadline = clock() + stop_timeout_s
    while lock.is_held(root):
        if clock() > deadline:
            say(out, f"stop: the run did not end within {stop_timeout_s:.0f} s")
            return ExitCode.ERROR
        sleep(poll_interval_s)
    final = run_state.read_state(root) or {}
    say(
        out,
        f"stop: run ended: {final.get('status')}, "
        f"verdict {final.get('verdict', 'none')}, "
        f"exit {final.get('exit_code')}",
    )
    return ExitCode.PASS
