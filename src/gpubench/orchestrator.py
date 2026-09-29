"""Drive one test run through its phases (DevSpec 4.1).

Preflight and idle sample telemetry only. Burn runs gpu_burn once for
warm-up plus steady, and the telemetry is labelled by elapsed time so
the tool is never restarted between the two. Cooldown samples only.
VRAM runs one cuda_memtest per GPU until the phase time is spent.
After the last phase the result folder is evaluated and the run exits
with the verdict (DevSpec 4.8).
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
from gpubench.runners import base, cuda_memtest, gpu_burn
from gpubench.runtime.exit_codes import ExitCode

leftover_process_names = ("gpu_burn", "cuda_memtest")
result_dir_time_format = "%Y%m%d-%H%M%S"
summary_file = "summary.json"
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


def format_tick(phase: str, number: int, total: int, records: list) -> str:
    """Return one plain console line summarising a sampling tick."""
    parts = [
        f"gpu{r['gpu_index']} {r['temp_gpu']} C {r['power_draw']} W "
        f"{r['clk_sm']} MHz"
        for r in records
    ]
    return f"[{phase} {number + 1}/{total}] " + " | ".join(parts)


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
        out: TextIO,
        log_dir: Path,
        launch: Launcher,
    ) -> None:
        """Keep the handles the phases need."""
        self.nvml = nvml
        self.gpus = gpus
        self.writer = writer
        self.interval_s = interval_s
        self.out = out
        self.log_dir = log_dir
        self.launch = launch
        self.active: list[base.ToolProcess] = []
        self.results: dict[str, Any] = {}

    def say(self, message: str) -> None:
        """Print one console line."""
        print(message, file=self.out)

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
            line = format_tick(phase, number - first, per_phase[phase], records)
            self.say(line)

        return telemetry.run_sampler(tick, total_s, self.interval_s)

    def sample_phase(self, phase: str, duration_s: float) -> int:
        """Sample every GPU once per interval for ``duration_s``."""
        return self.sample_schedule([(phase, duration_s)])

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
        # for -stts after the sampling window; allow for all of it.
        grace_s = profile["stop_grace_s"] + settings["sigterm_timeout_s"]
        status = self.finish_tool(process, grace_s)
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


def report_verdict(state: Run, verdict: dict[str, Any]) -> None:
    """Print one console line per rule and the incomplete reasons."""
    for rule in verdict["rules"]:
        grades = ", ".join(
            f"gpu{g['index']} {g['grade']} ({g['measured']})"
            for g in rule["gpus"]
        )
        state.say(f"verdict: {rule['title']}: {grades}")
    for reason in verdict["incomplete_reasons"]:
        state.say(f"verdict: incomplete: {reason}")


def write_reports(state: Run, result_dir: Path) -> bool:
    """Render charts and reports; return False when that failed.

    A report that violates the OOXML schema fails the run (DevSpec
    4.6.1, step 3) even though the verdict is already in summary.json.
    """
    # Imported here so the GPU path does not load matplotlib, Plotly,
    # and python-docx before the tests have finished.
    from gpubench.report import render

    state.say("report: rendering charts and reports")
    try:
        files = render.render(result_dir)
    except (render.ReportError, OSError) as exc:
        state.say(f"report: failed: {exc}")
        return False
    for note in files.notes:
        state.say(f"report: {note}")
    if files.rules_filtered:
        state.say("report: rule table reduced to WARN and FAIL to fit A4")
    state.say(f"report: {files.pdf or files.docx}")
    return True


def write_summary(path: Path, status: str, reason: str, results: dict) -> None:
    """Write ``summary.json`` with the runner results gathered so far."""
    document = {"status": status, "reason": reason, "runners": results}
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def run(
    options: RunOptions,
    nvml: Any = pynvml,
    out: TextIO = sys.stdout,
    proc_root: Path = Path("/proc"),
    host_root: Path = Path("/"),
    launch: Launcher = launch_tool,
) -> ExitCode:
    """Execute every implemented phase and write the result folder.

    Returns:
        ``ExitCode.ERROR`` when preflight or the report fails, otherwise
        the exit code of the verdict.
    """
    leftovers = find_leftover_processes(proc_root)
    if leftovers:
        for pid, name in leftovers:
            print(f"preflight: {name} still running as pid {pid}", file=out)
        print("preflight: stop those processes and retry", file=out)
        return ExitCode.ERROR

    nvml.nvmlInit()
    writer = None
    state = None
    result_dir = None
    try:
        count = nvml.nvmlDeviceGetCount()
        if count == 0:
            print("preflight: no NVIDIA GPU visible", file=out)
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
            print(f"preflight: {exc}", file=out)
            return ExitCode.ERROR
        profile_name = options.profile
        if profile_name == "auto":
            profile_name = gpu_class
        try:
            profile = config.load_profile(profile_name)
        except FileNotFoundError as exc:
            print(f"preflight: {exc}", file=out)
            return ExitCode.ERROR

        now = dt.datetime.now(dt.UTC)
        hostname = socket.gethostname()
        result_dir = make_result_dir(options.results_root, hostname, now)
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
        print(
            f"preflight: {count} GPU(s), class {gpu_class}, "
            f"profile {profile_name}, results {result_dir}",
            file=out,
        )
        for d in descriptions:
            missing = ", ".join(d["unsupported_fields"]) or "none"
            print(
                f"preflight: gpu{d['index']} {d['name']} "
                f"({d['brand']}), unsupported: {missing}",
                file=out,
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
            out,
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
        report_verdict(state, verdict)
        if not write_reports(state, result_dir):
            return ExitCode.ERROR
        state.say(
            f"run: finished in {elapsed_s:.0f} s; verdict {verdict['verdict']}"
        )
        return ExitCode(verdict["exit_code"])
    except KeyboardInterrupt:
        if state is not None:
            state.stop_all()
        if result_dir is not None:
            write_summary(
                result_dir / summary_file,
                "INCOMPLETE",
                "interrupted",
                state.results if state is not None else {},
            )
        print("run: interrupted; result is INCOMPLETE", file=out)
        return ExitCode.INCOMPLETE
    finally:
        if state is not None:
            state.stop_all()
        if writer is not None:
            writer.close()
        nvml.nvmlShutdown()
