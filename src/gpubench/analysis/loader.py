"""Read a result directory back into memory.

``telemetry.jsonl`` holds one JSON object per GPU per second and
``sysinfo.json`` describes the host (DevSpec section 4.3). The loader
is the single entry point for ``plot``, ``compare``, and the fixture
tests, so the field set is validated once here rather than in every
consumer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

telemetry_file = "telemetry.jsonl"
sysinfo_file = "sysinfo.json"

# One record per GPU per second. Fields a GPU does not support hold
# ``null`` rather than being omitted (LearnedPatterns E3).
telemetry_fields = (
    "ts",
    "phase",
    "gpu_index",
    "gpu_uuid",
    "temp_gpu",
    "temp_mem",
    "power_draw",
    "power_limit",
    "clk_sm",
    "clk_mem",
    "util_gpu",
    "mem_used",
    "fan_speed",
    "pstate",
    "clk_event_reasons",
    "ecc_corr",
    "ecc_uncorr",
    "remap_corr",
    "remap_uncorr",
    "remap_pending",
    "remap_failure",
    "pcie_gen",
    "pcie_width",
)

# ``synthetic`` is mandatory so that a fixture made from generated data
# can never be mistaken for a measurement (DevSpec section 4.6).
sysinfo_fields = (
    "hostname",
    "captured_at",
    "synthetic",
    "gpus",
    "driver_version",
    "cuda_version",
    "cpu",
    "memory",
    "os",
)


@dataclass(frozen=True)
class RunData:
    """Contents of one result directory that analysis needs."""

    sysinfo: dict[str, Any]
    samples: list[dict[str, Any]]

    @property
    def gpu_indices(self) -> list[int]:
        """Return the GPU indices present in the telemetry, sorted."""
        return sorted({sample["gpu_index"] for sample in self.samples})

    @property
    def phases(self) -> list[str]:
        """Return the phase names in order of first appearance."""
        seen: dict[str, None] = {}
        for sample in self.samples:
            seen.setdefault(sample["phase"], None)
        return list(seen)


def load_telemetry(path: Path) -> list[dict[str, Any]]:
    """Parse a telemetry JSONL file.

    Args:
        path: Location of ``telemetry.jsonl``.

    Returns:
        The records in file order. Blank lines are skipped.

    Raises:
        ValueError: If a line is not valid JSON or lacks a field from
            ``telemetry_fields``; the message names the line number.
    """
    samples: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path}:{number}: invalid JSON: {exc.msg}"
                ) from exc
            missing = [
                field for field in telemetry_fields if field not in record
            ]
            if missing:
                raise ValueError(f"{path}:{number}: missing fields {missing}")
            samples.append(record)
    return samples


def load_sysinfo(path: Path) -> dict[str, Any]:
    """Parse ``sysinfo.json``.

    Raises:
        ValueError: If the document is not an object or lacks a key
            from ``sysinfo_fields``.
    """
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be an object")
    missing = [field for field in sysinfo_fields if field not in data]
    if missing:
        raise ValueError(f"{path}: missing keys {missing}")
    return data


def load_result_dir(result_dir: Path) -> RunData:
    """Load ``sysinfo.json`` and ``telemetry.jsonl`` from ``result_dir``."""
    return RunData(
        sysinfo=load_sysinfo(result_dir / sysinfo_file),
        samples=load_telemetry(result_dir / telemetry_file),
    )
