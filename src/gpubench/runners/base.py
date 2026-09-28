"""Launch a test tool as its own process group with output in ``logs/``.

The raw tool output never reaches the terminal (DevSpec 4.8); it goes
to one log file per process so a failure can be analysed afterwards.
Each tool runs in a new session, so stopping it signals the whole
group, including the per-GPU children that gpu_burn forks.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

# gpu_burn waits this long after SIGTERM before it escalates to SIGKILL
# for its own children (its -stts default), so the group gets the same.
default_stop_grace_s = 30.0
poll_interval_s = 0.2


class ToolProcess:
    """One running tool, its log file, and how it ended."""

    def __init__(
        self,
        argv: Sequence[str],
        log_path: Path,
        env: dict[str, str] | None = None,
    ) -> None:
        """Start ``argv`` with stdout and stderr written to ``log_path``."""
        self.argv = list(argv)
        self.log_path = log_path
        self.stopped = False
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = log_path.open("wb")
        self._process = subprocess.Popen(
            self.argv,
            stdin=subprocess.DEVNULL,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )

    @property
    def pid(self) -> int:
        """Return the process id, which is also the process group id."""
        return self._process.pid

    def poll(self) -> int | None:
        """Return the exit status, or ``None`` while still running."""
        return self._process.poll()

    def wait(self, timeout_s: float | None = None) -> int | None:
        """Wait for exit; return the status or ``None`` on timeout."""
        try:
            return self._process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return None

    def _signal_group(self, number: int) -> None:
        if hasattr(os, "killpg"):
            try:
                os.killpg(self._process.pid, number)
            except ProcessLookupError:
                pass
        elif number == signal.SIGTERM:
            self._process.terminate()
        else:
            self._process.kill()

    def stop(self, grace_s: float = default_stop_grace_s) -> int:
        """Terminate the process group, escalating to SIGKILL.

        Returns:
            The exit status of the group leader.
        """
        if self.poll() is None:
            self.stopped = True
            self._signal_group(signal.SIGTERM)
            if self.wait(grace_s) is None:
                self._signal_group(getattr(signal, "SIGKILL", signal.SIGTERM))
                self.wait()
        return self.finish()

    def finish(self) -> int:
        """Wait for exit, close the log, and return the exit status."""
        status = self._process.wait()
        if not self._log.closed:
            self._log.close()
        return status

    def read_log(self) -> str:
        """Return the log contents decoded leniently."""
        return self.log_path.read_text(encoding="utf-8", errors="replace")


def wait_until(
    deadline: float, processes: Sequence[ToolProcess], clock=time.monotonic
) -> None:
    """Block until ``deadline`` or until every process has exited."""
    while clock() < deadline:
        if all(p.poll() is not None for p in processes):
            return
        time.sleep(min(poll_interval_s, max(0.0, deadline - clock())))
