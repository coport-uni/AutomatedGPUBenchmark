"""Drive one test run through its phases (DevSpec 4.1).

M2 covers preflight and idle. The burn, cooldown, and VRAM phases are
added by the runners in M3; until then ``run`` ends after idle with
``ExitCode.INCOMPLETE`` so no caller can mistake it for a verdict.
"""

from __future__ import annotations

import datetime as dt
import json
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import pynvml

from gpubench import config, detect
from gpubench.analysis.loader import sysinfo_file, telemetry_file
from gpubench.collectors import sysinfo, telemetry
from gpubench.runtime.exit_codes import ExitCode

leftover_process_names = ("gpu_burn", "cuda_memtest")
result_dir_time_format = "%Y%m%d-%H%M%S"


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
    base = f"{hostname}_{now.strftime(result_dir_time_format)}"
    candidate = root / base
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = root / f"{base}-{suffix}"
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


class Run:
    """State shared by the phases of one run."""

    def __init__(
        self,
        nvml: Any,
        gpus: list[telemetry.GpuHandle],
        writer: telemetry.TelemetryWriter,
        interval_s: float,
        out: TextIO,
    ) -> None:
        """Keep the handles the phases need."""
        self.nvml = nvml
        self.gpus = gpus
        self.writer = writer
        self.interval_s = interval_s
        self.out = out

    def sample_all(self, phase: str) -> list[dict[str, Any]]:
        """Sample every GPU once and append the records to the file."""
        ts = telemetry.utc_timestamp()
        records = [telemetry.sample(self.nvml, g, phase, ts) for g in self.gpus]
        self.writer.write(records)
        return records

    def sample_phase(self, phase: str, duration_s: float) -> int:
        """Sample every GPU once per interval for ``duration_s``."""
        total = int(duration_s // self.interval_s)

        def tick(number: int) -> None:
            records = self.sample_all(phase)
            print(format_tick(phase, number, total, records), file=self.out)

        return telemetry.run_sampler(tick, duration_s, self.interval_s)


def run(
    options: RunOptions,
    nvml: Any = pynvml,
    out: TextIO = sys.stdout,
    proc_root: Path = Path("/proc"),
    host_root: Path = Path("/"),
) -> ExitCode:
    """Execute preflight and idle and write the result folder.

    Returns:
        ``ExitCode.ERROR`` when preflight fails, otherwise
        ``ExitCode.INCOMPLETE`` because the later phases are not
        implemented yet.
    """
    leftovers = find_leftover_processes(proc_root)
    if leftovers:
        for pid, name in leftovers:
            print(f"preflight: {name} still running as pid {pid}", file=out)
        print("preflight: stop those processes and retry", file=out)
        return ExitCode.ERROR

    nvml.nvmlInit()
    writer = None
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
        info["run"] = {"profile": profile_name, "gpu_class": gpu_class}
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
        state = Run(nvml, gpus, writer, profile["sampling_interval_s"], out)
        state.sample_all("preflight")
        state.sample_phase("idle", profile["phases"]["idle_s"])
        print(
            "run: burn, cooldown, and VRAM phases are not implemented "
            "yet (M3); result is INCOMPLETE",
            file=out,
        )
        return ExitCode.INCOMPLETE
    except KeyboardInterrupt:
        print("run: interrupted; result is INCOMPLETE", file=out)
        return ExitCode.INCOMPLETE
    finally:
        if writer is not None:
            writer.close()
        nvml.nvmlShutdown()
