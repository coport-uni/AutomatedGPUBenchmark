"""Drive one test run through its phases (DevSpec 4.1).

Preflight and idle sample telemetry only. Burn runs gpu_burn once for
warm-up plus steady, and the telemetry is labelled by elapsed time so
the tool is never restarted between the two. While gpu_burn finishes
after its window, samples are labelled ``burn_finish``. Cooldown
samples only. VRAM runs one cuda_memtest per GPU until the phase time
is spent. After the last phase the result folder is evaluated, the
reports are written, and the run exits with the verdict (DevSpec 4.8).

Only one run holds ``<results-root>/.lock`` at a time. SIGINT and
SIGTERM stop the tools and still produce an INCOMPLETE report; SIGHUP
is ignored.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import socket
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import pynvml

from gpubench import config, detect, evaluate
from gpubench.analysis.loader import sysinfo_file, telemetry_file
from gpubench.collectors import sysinfo, telemetry
from gpubench.console import mode as console_mode
from gpubench.console import plain
from gpubench.console.mode import Console, ConsoleGroup, Tick
from gpubench.runners import base, cuda_memtest, gpu_burn
from gpubench.runtime import signals
from gpubench.runtime import state as run_state
from gpubench.runtime.exit_codes import ExitCode
from gpubench.runtime.lock import RunLock

leftover_process_names = ("gpu_burn", "cuda_memtest")
result_dir_time_format = "%Y%m%d-%H%M%S"
summary_file = "summary.json"
console_log_file = "console.log"
logs_dir = "logs"
# CUDA enumerates the fastest GPU first by default; PCI order makes
# the tool's GPU numbers match the NVML indices in telemetry.jsonl.
tool_environment = {"CUDA_DEVICE_ORDER": "PCI_BUS_ID"}

Launcher = Callable[[Sequence[str], Path], base.ToolProcess]


def launch_tool(argv: Sequence[str], log_path: Path) -> base.ToolProcess:
    """Start a tool with the environment every runner needs."""
    return base.ToolProcess(argv, log_path, {**os.environ, **tool_environment})


@dataclass(frozen=True)
class RunOptions:
    """Choices made on the command line for one run."""

    profile: str
    gpu_class: str | None
    results_root: Path
    output: str = "auto"


def find_leftover_processes(
    proc_root: Path = Path("/proc"),
    names: tuple[str, ...] = leftover_process_names,
) -> list[tuple[int, str]]:
    """Return ``(pid, name)`` of test tools still running.

    A ``gpu_burn`` left behind by an interrupted run would load the GPU
    during idle and skew every result (DevSpec 4.8).
    """
    found = []
    for comm in proc_root.glob("[0-9]*/comm"):
        try:
            name = comm.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if name in names:
            found.append((int(comm.parent.name), name))
    return sorted(found)


def make_result_dir(root: Path, hostname: str, now: dt.datetime) -> Path:
    """Create ``<root>/<hostname>_<YYYYMMDD-HHMMSS>`` and return it.

    A numeric suffix keeps two runs started in the same second apart.
    """
    base_name = f"{hostname}_{now.strftime(result_dir_time_format)}"
    candidate = root / base_name
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = root / f"{base_name}-{suffix}"
    candidate.mkdir(parents=True)
    return candidate


def phase_at(schedule: Sequence[tuple[str, float]], elapsed_s: float) -> str:
    """Return the phase of ``schedule`` that contains ``elapsed_s``."""
    end = 0.0
    for name, duration_s in schedule:
        end += duration_s
        if elapsed_s < end:
            return name
    return schedule[-1][0]


class Run:
    """State shared by the phases of one run."""

    def __init__(
        self,
        nvml: Any,
        gpus: list[telemetry.GpuHandle],
        writer: telemetry.TelemetryWriter,
        interval_s: float,
        console: Console,
        log_dir: Path,
        launch: Launcher,
    ) -> None:
        """Keep the handles the phases need."""
        self.nvml = nvml
        self.gpus = gpus
        self.writer = writer
        self.interval_s = interval_s
        self.console = console
        self.log_dir = log_dir
        self.launch = launch
        self.active: list[base.ToolProcess] = []
        self.results: dict[str, Any] = {}

    def say(self, message: str) -> None:
        """Report one console event."""
        self.console.event(message)

    def sample_all(self, phase: str) -> list[dict[str, Any]]:
        """Sample every GPU once and append the records to the file."""
        ts = telemetry.utc_timestamp()
        records = [telemetry.sample(self.nvml, g, phase, ts) for g in self.gpus]
        self.writer.write(records)
        return records

    def sample_schedule(self, schedule: Sequence[tuple[str, float]]) -> int:
        """Sample continuously across consecutive phases."""
        total_s = sum(duration for _, duration in schedule)
        per_phase = {name: int(d // self.interval_s) for name, d in schedule}
        starts: dict[str, int] = {}

        def tick(number: int) -> None:
            phase = phase_at(schedule, number * self.interval_s)
            first = starts.setdefault(phase, number)
            records = self.sample_all(phase)
            self.console.tick(
                Tick(phase, number - first + 1, per_phase[phase], records)
            )

        return telemetry.run_sampler(tick, total_s, self.interval_s)

    def sample_phase(self, phase: str, duration_s: float) -> int:
        """Sample every GPU once per interval for ``duration_s``."""
        return self.sample_schedule([(phase, duration_s)])

    def sample_while_running(
        self, phase: str, process: base.ToolProcess, limit_s: float
    ) -> int:
        """Sample as ``phase`` until ``process`` exits or ``limit_s``.

        Without this the telemetry paused while gpu_burn finished after
        its window, about 8 s with ``-stts 5`` (ToDo section 5).
        """
        total = int(limit_s // self.interval_s)

        def tick(number: int) -> None:
            records = self.sample_all(phase)
            self.console.tick(Tick(phase, number + 1, total, records))

        return telemetry.run_sampler(
            tick,
            limit_s,
            self.interval_s,
            until=lambda: process.poll() is not None,
        )

    def finish_tool(self, process: base.ToolProcess, grace_s: float) -> int:
        """Let a tool end by itself within ``grace_s``, then stop it."""
        if process.wait(grace_s) is None:
            status = process.stop()
        else:
            status = process.finish()
        self.active.remove(process)
        return status

    def burn(self, profile: dict[str, Any]) -> None:
        """Run gpu_burn through warm-up and steady."""
        phases = profile["phases"]
        settings = profile["gpu_burn"]
        schedule = [
            ("burn_warmup", phases["burn_warmup_s"]),
            ("burn_steady", phases["burn_steady_s"]),
        ]
        duration_s = int(sum(d for _, d in schedule))
        argv = gpu_burn.build_command(
            duration_s,
            settings["memory_percent"],
            settings["use_doubles"],
            settings["use_tensor_cores"],
            settings["sigterm_timeout_s"],
        )
        process = self.launch(argv, self.log_dir / "gpu_burn.log")
        self.active.append(process)
        self.say(f"burn: gpu_burn for {duration_s} s, log {process.log_path}")
        self.sample_schedule(schedule)
        # The tool still initialises, runs its full time, and sleeps
        # for -stts after the sampling window; allow for all of it and
        # keep sampling meanwhile.
        grace_s = profile["stop_grace_s"] + settings["sigterm_timeout_s"]
        self.sample_while_running("burn_finish", process, grace_s)
        status = self.finish_tool(process, 0.0)
        parsed = gpu_burn.parse(process.read_log())
        self.results["gpu_burn"] = {
            "exit_status": status,
            "stopped": process.stopped,
            "complete": parsed.complete,
            "gpus": [g.as_dict() for g in parsed.gpus],
        }
        for g in parsed.gpus:
            self.say(
                f"burn: gpu{g.index} {g.gflops_max} Gflop/s max, "
                f"{g.errors} errors, verdict {g.verdict}"
            )
        if not parsed.complete:
            self.say("burn: gpu_burn did not report a verdict for every GPU")

    def vram(self, profile: dict[str, Any]) -> None:
        """Run one cuda_memtest per GPU until the VRAM phase ends."""
        stress = profile["cuda_memtest"]["stress"]
        processes = []
        for gpu in self.gpus:
            argv = cuda_memtest.build_command(gpu.index, stress)
            log = self.log_dir / f"cuda_memtest_gpu{gpu.index}.log"
            processes.append(self.launch(argv, log))
        self.active.extend(processes)
        self.say(f"vram: cuda_memtest on {len(processes)} GPU(s)")
        self.sample_phase("vram", profile["phases"]["vram_s"])
        summaries = []
        for gpu, process in zip(self.gpus, processes, strict=True):
            status = self.finish_tool(process, 0.0)
            parsed = cuda_memtest.parse(process.read_log(), gpu.index)
            summary = parsed.as_dict()
            summary["exit_status"] = status
            summary["stopped_at_deadline"] = process.stopped
            summaries.append(summary)
            self.say(
                f"vram: gpu{gpu.index} {parsed.tests_finished} tests, "
                f"{parsed.pattern_errors} pattern errors"
            )
        self.results["cuda_memtest"] = summaries

    def stop_all(self) -> None:
        """Stop every tool that is still running."""
        for process in list(self.active):
            process.stop()
            self.active.remove(process)


def write_reports(console: Console, result_dir: Path) -> bool:
    """Render charts and reports; return False when that failed.

    A report that violates the OOXML schema fails the run (DevSpec
    4.6.1, step 3) even though the verdict is already in summary.json.
    """
    # Imported here so the GPU path does not load matplotlib, Plotly,
    # and python-docx before the tests have finished.
    from gpubench.report import render

    console.event("report: rendering charts and reports")
    try:
        files = render.render(result_dir)
    except (render.ReportError, OSError) as exc:
        console.event(f"report: failed: {exc}")
        return False
    for note in files.notes:
        console.event(f"report: {note}")
    if files.rules_filtered:
        console.event("report: rule table reduced to WARN and FAIL to fit A4")
    console.event(f"report: {files.pdf or files.docx}")
    return True


def write_summary(path: Path, status: str, reason: str, results: dict) -> None:
    """Write ``summary.json`` with the runner results gathered so far."""
    document = {"status": status, "reason": reason, "runners": results}
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def finish_interrupted(
    console: Console,
    state: Run | None,
    result_dir: Path | None,
    name: str,
) -> ExitCode:
    """Stop the tools and write an INCOMPLETE summary and report."""
    console.event(f"run: {name} received; stopping the test tools")
    if state is not None:
        state.stop_all()
    if result_dir is None:
        console.event("run: stopped before the result folder existed")
        return ExitCode.INCOMPLETE
    reason = f"interrupted by {name}"
    write_summary(
        result_dir / summary_file,
        "INCOMPLETE",
        reason,
        state.results if state is not None else {},
    )
    try:
        verdict = evaluate.write_evaluation(
            result_dir, summary_file, interrupted=reason
        )
    except (KeyError, ValueError, OSError) as exc:
        console.event(f"run: the partial run could not be evaluated: {exc}")
        return ExitCode.INCOMPLETE
    console.verdict(verdict)
    try:
        write_reports(console, result_dir)
    except Exception as exc:
        # The data of a stopped run can be too thin for a chart; the
        # verdict and summary are already written.
        console.event(f"report: failed on the partial run: {exc!r}")
    console.event("run: stopped; verdict INCOMPLETE")
    return ExitCode.INCOMPLETE


def execute(
    options: RunOptions,
    nvml: Any,
    console: ConsoleGroup,
    log: plain.BufferedLog,
    tracker: run_state.StateConsole,
    proc_root: Path,
    host_root: Path,
    launch: Launcher,
) -> ExitCode:
    """Run preflight, every phase, the evaluation, and the reports."""
    leftovers = find_leftover_processes(proc_root)
    if leftovers:
        for pid, name in leftovers:
            console.event(f"preflight: {name} still running as pid {pid}")
        console.event("preflight: stop those processes and retry")
        return ExitCode.ERROR

    nvml.nvmlInit()
    writer = None
    state = None
    result_dir = None
    try:
        count = nvml.nvmlDeviceGetCount()
        if count == 0:
            console.event("preflight: no NVIDIA GPU visible")
            return ExitCode.ERROR
        handles = [nvml.nvmlDeviceGetHandleByIndex(i) for i in range(count)]
        unsupported = [detect.probe_unsupported(nvml, h) for h in handles]
        descriptions = [
            sysinfo.describe_gpu(nvml, h, i, unsupported[i])
            for i, h in enumerate(handles)
        ]
        try:
            gpu_class = detect.resolve_class(
                (d["gpu_class"] for d in descriptions), options.gpu_class
            )
        except ValueError as exc:
            console.event(f"preflight: {exc}")
            return ExitCode.ERROR
        profile_name = options.profile
        if profile_name == "auto":
            profile_name = gpu_class
        try:
            profile = config.load_profile(profile_name)
        except FileNotFoundError as exc:
            console.event(f"preflight: {exc}")
            return ExitCode.ERROR

        now = dt.datetime.now(dt.UTC)
        hostname = socket.gethostname()
        result_dir = make_result_dir(options.results_root, hostname, now)
        log.open(result_dir / console_log_file)
        tracker.set_result_dir(result_dir)
        info = sysinfo.build_sysinfo(
            nvml,
            descriptions,
            hostname,
            telemetry.utc_timestamp(now),
            sysinfo.collect_host(host_root),
        )
        info["run"] = {
            "profile": profile_name,
            "gpu_class": gpu_class,
            "sampling_interval_s": profile["sampling_interval_s"],
            "gpu_ratio_min": profile["evaluation"]["gpu_ratio_min"],
            "phases": dict(profile["phases"]),
            "gpu_burn_memory_percent": profile["gpu_burn"]["memory_percent"],
        }
        (result_dir / sysinfo_file).write_text(
            json.dumps(info, indent=2) + "\n", encoding="utf-8"
        )
        console.event(
            f"preflight: {count} GPU(s), class {gpu_class}, "
            f"profile {profile_name}, results {result_dir}"
        )
        for d in descriptions:
            missing = ", ".join(d["unsupported_fields"]) or "none"
            console.event(
                f"preflight: gpu{d['index']} {d['name']} "
                f"({d['brand']}), unsupported: {missing}"
            )

        writer = telemetry.TelemetryWriter(result_dir / telemetry_file)
        gpus = [
            telemetry.GpuHandle(
                i, d["uuid"], handles[i], frozenset(d["unsupported_fields"])
            )
            for i, d in enumerate(descriptions)
        ]
        state = Run(
            nvml,
            gpus,
            writer,
            profile["sampling_interval_s"],
            console,
            result_dir / logs_dir,
            launch,
        )
        phases = profile["phases"]
        started = time.monotonic()
        state.sample_all("preflight")
        state.sample_phase("idle", phases["idle_s"])
        state.burn(profile)
        state.sample_phase("cooldown", phases["cooldown_s"])
        state.vram(profile)
        if profile["optional_runner"] != "none":
            state.say(
                f"optional: {profile['optional_runner']} arrives in M7; skipped"
            )
        elapsed_s = time.monotonic() - started
        write_summary(
            result_dir / summary_file, "EVALUATING", "", state.results
        )
        verdict = evaluate.write_evaluation(result_dir, summary_file)
        console.verdict(verdict)
        if not write_reports(console, result_dir):
            return ExitCode.ERROR
        state.say(
            f"run: finished in {elapsed_s:.0f} s; verdict {verdict['verdict']}"
        )
        return ExitCode(verdict["exit_code"])
    except signals.Interrupted as exc:
        with signals.shielded(console.event):
            tracker.state["interrupted_by"] = exc.name
            return finish_interrupted(console, state, result_dir, exc.name)
    finally:
        if state is not None:
            state.stop_all()
        if writer is not None:
            writer.close()
        nvml.nvmlShutdown()


def refuse_second_run(console: Console, root: Path) -> ExitCode:
    """Report the run that holds the lock and return ERROR."""
    holder = run_state.read_state(root) or {}
    console.event(
        f"preflight: another run holds {root / '.lock'} "
        f"(pid {holder.get('pid', '?')}, "
        f"results {holder.get('result_dir') or '?'}); "
        "see gpubench status"
    )
    return ExitCode.ERROR


def run(
    options: RunOptions,
    nvml: Any = pynvml,
    out: TextIO = sys.stdout,
    proc_root: Path = Path("/proc"),
    host_root: Path = Path("/"),
    launch: Launcher = launch_tool,
) -> ExitCode:
    """Execute a whole run under the results lock.

    Returns:
        ``ExitCode.ERROR`` when another run holds the lock, preflight
        fails, or the report fails; ``ExitCode.INCOMPLETE`` after
        SIGINT or SIGTERM; otherwise the exit code of the verdict.
    """
    mode = console_mode.resolve(options.output, out)
    console = ConsoleGroup([console_mode.create(mode, out)])
    root = options.results_root
    lock = RunLock(root)
    try:
        if not lock.acquire():
            return refuse_second_run(console, root)
        log = plain.BufferedLog()
        tracker = run_state.StateConsole(root)
        console.add(log)
        console.add(tracker)
        code = ExitCode.ERROR
        try:
            with signals.run_signals():
                code = execute(
                    options,
                    nvml,
                    console,
                    log,
                    tracker,
                    proc_root,
                    host_root,
                    launch,
                )
        except signals.Interrupted as exc:
            # A signal between the phases and the handler's own cleanup,
            # for example while NVML shuts down; nothing is left to stop.
            tracker.state["interrupted_by"] = exc.name
            code = ExitCode.INCOMPLETE
        finally:
            ended = (
                run_state.status_interrupted
                if tracker.state.get("interrupted_by")
                else run_state.status_finished
            )
            tracker.finish(ended, int(code))
            lock.release()
        return code
    finally:
        console.close()
