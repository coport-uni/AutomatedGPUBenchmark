"""Command line and output parser for wilicc/gpu-burn.

gpu_burn prints a progress record roughly every second, separated by
carriage returns, and a ``Summary at:`` line every 10 % of the run.
The per-GPU error counters restart from zero after each summary, so
the total error count is the sum of each window's last value.
The final ``GPU N: OK|FAULTY`` lines are the tool's own verdict
(DevSpec 4.4, compute error rule).
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

binary_name = "gpu_burn"
compare_kernel_name = "compare.fatbin"
verdict_ok = "OK"
verdict_faulty = "FAULTY"

progress_pattern = re.compile(
    r"^(?P<percent>\d+(?:\.\d+)?)%\s+proc'd:\s*(?P<procd>.*?)\s+"
    r"errors:\s*(?P<errors>.*?)\s+temps:\s*(?P<temps>.*?)\s*$"
)
procd_pattern = re.compile(r"(-?\d+) \((\d+(?:\.\d+)?) Gflop/s\)")
error_pattern = re.compile(r"(\d+)\s*(?:\((DIED!|WARNING!)\))?")
temp_pattern = re.compile(r"(\d+) C|--")
summary_marker = "Summary at:"
# Records are separated by carriage returns; a record start is also a
# boundary so a log whose carriage returns were lost still parses.
record_separator = re.compile(r"[\r\n]+|(?=\b\d+(?:\.\d+)?%\s+proc'd:)")
verdict_pattern = re.compile(r"^\s*GPU (\d+): (OK|FAULTY)\s*$")
tested_pattern = re.compile(r"^Tested (\d+) GPUs:")


def build_command(
    duration_s: int,
    memory_percent: int,
    use_doubles: bool = False,
    use_tensor_cores: bool = False,
    sigterm_timeout_s: int | None = None,
    binary: str | None = None,
) -> list[str]:
    """Return the gpu_burn argument vector.

    The compare kernel is passed by absolute path so the tool can run
    from any working directory. ``sigterm_timeout_s`` maps to
    ``-stts``, the time the tool sleeps after stopping its workers.
    """
    path = binary or shutil.which(binary_name) or binary_name
    kernel = Path(path).resolve().parent / compare_kernel_name
    argv = [path, "-m", f"{memory_percent}%", "-c", str(kernel)]
    if sigterm_timeout_s is not None:
        argv += ["-stts", str(sigterm_timeout_s)]
    if use_doubles:
        argv.append("-d")
    if use_tensor_cores:
        argv.append("-tc")
    argv.append(str(duration_s))
    return argv


@dataclass
class GpuBurnGpu:
    """Parsed outcome for one GPU."""

    index: int
    gflops_samples: list[float] = field(default_factory=list)
    errors: int = 0
    died: bool = False
    verdict: str | None = None

    @property
    def gflops_max(self) -> float | None:
        """Return the highest reported throughput."""
        return max(self.gflops_samples, default=None)

    @property
    def gflops_last(self) -> float | None:
        """Return the throughput of the last progress record."""
        return self.gflops_samples[-1] if self.gflops_samples else None

    def as_dict(self) -> dict:
        """Return a JSON-ready summary."""
        return {
            "index": self.index,
            "gflops_max": self.gflops_max,
            "gflops_last": self.gflops_last,
            "errors": self.errors,
            "died": self.died,
            "verdict": self.verdict,
        }


@dataclass
class GpuBurnResult:
    """Everything the parser extracted from one gpu_burn log."""

    gpus: list[GpuBurnGpu]
    records: int
    tested: int | None

    @property
    def complete(self) -> bool:
        """Return whether the tool printed a verdict for every GPU."""
        return self.tested is not None and all(
            g.verdict is not None for g in self.gpus
        )

    @property
    def faulty(self) -> bool:
        """Return whether any GPU failed by the tool's own criteria."""
        return any(
            g.verdict == verdict_faulty or g.errors or g.died for g in self.gpus
        )


def split_fields(text: str) -> list[str]:
    """Split a ``a - b - c`` list printed by gpu_burn."""
    return [part.strip() for part in text.split(" - ")]


def parse(text: str) -> GpuBurnResult:
    """Parse a complete or truncated gpu_burn log."""
    gpus: dict[int, GpuBurnGpu] = {}
    window_errors: dict[int, int] = {}
    records = 0
    tested = None

    def gpu(index: int) -> GpuBurnGpu:
        return gpus.setdefault(index, GpuBurnGpu(index))

    def close_window() -> None:
        for index, count in window_errors.items():
            gpu(index).errors += count
        window_errors.clear()

    for fragment in record_separator.split(text):
        line = fragment.strip()
        if not line:
            continue
        match = progress_pattern.match(line)
        if match:
            records += 1
            procd = procd_pattern.findall(match["procd"])
            for index, (calcs, gflops) in enumerate(procd):
                if int(calcs) > 0:
                    gpu(index).gflops_samples.append(float(gflops))
                if int(calcs) < 0:
                    gpu(index).died = True
            for index, item in enumerate(split_fields(match["errors"])):
                counted = error_pattern.fullmatch(item)
                if counted:
                    window_errors[index] = int(counted[1])
                    if counted[2] == "DIED!":
                        gpu(index).died = True
            continue
        if line.startswith(summary_marker):
            close_window()
            continue
        verdict = verdict_pattern.match(fragment)
        if verdict:
            gpu(int(verdict[1])).verdict = verdict[2]
            continue
        header = tested_pattern.match(line)
        if header:
            tested = int(header[1])
    close_window()
    return GpuBurnResult(
        gpus=[gpus[i] for i in sorted(gpus)], records=records, tested=tested
    )
