"""Command line and output parser for cuda_memtest.

One process runs per GPU (``--device N``) so that errors are attributed
without untangling interleaved output. ``--stress`` selects Test10 and
``--exit_on_error``; the process is started with a pass count far above
what fits into the VRAM phase and is stopped at the phase deadline.
A pattern error is reported as ``ERROR: (<test>) <n> errors found in
block <b>`` (tests.cpp), which is the VRAM rule of DevSpec 4.4.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

binary_name = "cuda_memtest"
# Upper bound on passes; the orchestrator stops the tool at the phase
# deadline long before this is reached.
unbounded_passes = 1_000_000

finished_pattern = re.compile(r"Test(\d+) finished in ([\d.]+) seconds")
block_error_pattern = re.compile(
    r"ERROR: \((?P<test>[^)]*)\) (?P<count>\d+) errors found in block"
)
allocated_pattern = re.compile(r"Allocated (\d+) MB")
error_marker = "ERROR:"


def build_command(
    device: int, stress: bool = True, binary: str = binary_name
) -> list[str]:
    """Return the cuda_memtest argument vector for one GPU."""
    argv = [binary, "--device", str(device)]
    if stress:
        argv.append("--stress")
    else:
        argv.append("--exit_on_error")
    argv += ["--num_passes", str(unbounded_passes)]
    return argv


@dataclass
class CudaMemtestResult:
    """Parsed outcome of one cuda_memtest process."""

    device: int
    tests_finished: int = 0
    pattern_errors: int = 0
    allocated_mib: int | None = None
    error_lines: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        """Return whether the tool reported any error."""
        return bool(self.pattern_errors or self.error_lines)

    def as_dict(self) -> dict:
        """Return a JSON-ready summary."""
        return {
            "index": self.device,
            "tests_finished": self.tests_finished,
            "pattern_errors": self.pattern_errors,
            "allocated_mib": self.allocated_mib,
            "error_lines": self.error_lines,
        }


def parse(text: str, device: int) -> CudaMemtestResult:
    """Parse the log of one cuda_memtest process."""
    result = CudaMemtestResult(device)
    for line in text.splitlines():
        if finished_pattern.search(line):
            result.tests_finished += 1
        allocated = allocated_pattern.search(line)
        if allocated and result.allocated_mib is None:
            result.allocated_mib = int(allocated[1])
        block = block_error_pattern.search(line)
        if block:
            result.pattern_errors += int(block["count"])
        if error_marker in line:
            result.error_lines.append(line.strip())
    return result
