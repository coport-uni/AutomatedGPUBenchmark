"""NVML telemetry sampling at a fixed cadence.

Each sample is one JSON object per GPU in the field order of
``gpubench.analysis.loader.telemetry_fields`` (DevSpec 4.3). A field
the GPU does not support is written as ``null`` instead of being left
out, so every line has the same shape.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import pynvml

from gpubench.analysis.loader import telemetry_fields

milliwatts_per_watt = 1000
bytes_per_mib = 1024 * 1024
watt_digits = 2

# nvmlDeviceGetFieldValues returns a tagged union; the tag says which
# member holds the value.
field_value_members = {
    pynvml.NVML_VALUE_TYPE_DOUBLE: "dVal",
    pynvml.NVML_VALUE_TYPE_UNSIGNED_INT: "uiVal",
    pynvml.NVML_VALUE_TYPE_UNSIGNED_LONG: "ulVal",
    pynvml.NVML_VALUE_TYPE_UNSIGNED_LONG_LONG: "ullVal",
    pynvml.NVML_VALUE_TYPE_SIGNED_LONG_LONG: "sllVal",
}


@dataclass(frozen=True)
class MetricGroup:
    """Telemetry fields that one NVML call fills together."""

    fields: tuple[str, ...]
    read: Callable[[Any, Any], tuple[Any, ...]]


def read_field_value(nvml: Any, handle: Any, field_id: int) -> Any:
    """Read one NVML field value, raising if the GPU lacks it."""
    (value,) = nvml.nvmlDeviceGetFieldValues(handle, [field_id])
    if value.nvmlReturn != nvml.NVML_SUCCESS:
        raise pynvml.NVMLError(value.nvmlReturn)
    return getattr(value.value, field_value_members[value.valueType])


def read_clock_event_reasons(nvml: Any, handle: Any) -> int:
    """Read the clocks event bitmask under its current or legacy name."""
    reader = getattr(nvml, "nvmlDeviceGetCurrentClocksEventReasons", None)
    if reader is None:
        reader = nvml.nvmlDeviceGetCurrentClocksThrottleReasons
    return reader(handle)


def read_ecc(nvml: Any, handle: Any) -> tuple[int, int]:
    """Read volatile corrected and uncorrected ECC totals."""
    return tuple(
        nvml.nvmlDeviceGetTotalEccErrors(handle, kind, nvml.NVML_VOLATILE_ECC)
        for kind in (
            nvml.NVML_MEMORY_ERROR_TYPE_CORRECTED,
            nvml.NVML_MEMORY_ERROR_TYPE_UNCORRECTED,
        )
    )


def read_remap(nvml: Any, handle: Any) -> tuple[int, int, bool, bool]:
    """Read row-remap counts and the pending and failure flags."""
    corr, uncorr, pending, failure = nvml.nvmlDeviceGetRemappedRows(handle)
    return corr, uncorr, bool(pending), bool(failure)


def to_watts(milliwatts: int) -> float:
    """Convert an NVML power reading from mW to W."""
    return round(milliwatts / milliwatts_per_watt, watt_digits)


metric_groups = (
    MetricGroup(
        ("temp_gpu",),
        lambda n, h: (n.nvmlDeviceGetTemperature(h, n.NVML_TEMPERATURE_GPU),),
    ),
    MetricGroup(
        ("temp_mem",),
        lambda n, h: (read_field_value(n, h, n.NVML_FI_DEV_MEMORY_TEMP),),
    ),
    MetricGroup(
        ("power_draw",),
        lambda n, h: (to_watts(n.nvmlDeviceGetPowerUsage(h)),),
    ),
    MetricGroup(
        ("power_limit",),
        lambda n, h: (to_watts(n.nvmlDeviceGetEnforcedPowerLimit(h)),),
    ),
    MetricGroup(
        ("clk_sm",),
        lambda n, h: (n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_SM),),
    ),
    MetricGroup(
        ("clk_mem",),
        lambda n, h: (n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_MEM),),
    ),
    MetricGroup(
        ("util_gpu",),
        lambda n, h: (n.nvmlDeviceGetUtilizationRates(h).gpu,),
    ),
    MetricGroup(
        ("mem_used",),
        lambda n, h: (n.nvmlDeviceGetMemoryInfo(h).used // bytes_per_mib,),
    ),
    MetricGroup(("fan_speed",), lambda n, h: (n.nvmlDeviceGetFanSpeed(h),)),
    MetricGroup(
        ("pstate",),
        lambda n, h: (f"P{n.nvmlDeviceGetPerformanceState(h)}",),
    ),
    MetricGroup(
        ("clk_event_reasons",),
        lambda n, h: (read_clock_event_reasons(n, h),),
    ),
    MetricGroup(("ecc_corr", "ecc_uncorr"), read_ecc),
    MetricGroup(
        ("remap_corr", "remap_uncorr", "remap_pending", "remap_failure"),
        read_remap,
    ),
    MetricGroup(
        ("pcie_gen",),
        lambda n, h: (n.nvmlDeviceGetCurrPcieLinkGeneration(h),),
    ),
    MetricGroup(
        ("pcie_width",),
        lambda n, h: (n.nvmlDeviceGetCurrPcieLinkWidth(h),),
    ),
)


@dataclass(frozen=True)
class GpuHandle:
    """One GPU as the sampler sees it."""

    index: int
    uuid: str
    handle: Any
    unsupported: frozenset[str]


def utc_timestamp(now: dt.datetime | None = None) -> str:
    """Return an ISO 8601 UTC timestamp with millisecond precision."""
    moment = now or dt.datetime.now(dt.UTC)
    text = moment.astimezone(dt.UTC).isoformat(timespec="milliseconds")
    return text.replace("+00:00", "Z")


def sample(nvml: Any, gpu: GpuHandle, phase: str, ts: str) -> dict[str, Any]:
    """Read every telemetry field of one GPU.

    Fields in ``gpu.unsupported`` are not read. A supported field whose
    read fails transiently is also stored as ``None`` so a single bad
    reading never aborts a long run.
    """
    values: dict[str, Any] = {
        "ts": ts,
        "phase": phase,
        "gpu_index": gpu.index,
        "gpu_uuid": gpu.uuid,
    }
    for group in metric_groups:
        readings: tuple[Any, ...] = (None,) * len(group.fields)
        if not gpu.unsupported.issuperset(group.fields):
            try:
                readings = group.read(nvml, gpu.handle)
            except pynvml.NVMLError:
                pass
        values.update(zip(group.fields, readings, strict=True))
    return {field: values[field] for field in telemetry_fields}


def run_sampler(
    tick: Callable[[int], None],
    duration_s: float,
    interval_s: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    until: Callable[[], bool] | None = None,
) -> int:
    """Call ``tick`` once per interval for ``duration_s`` seconds.

    Tick ``k`` is scheduled at ``start + k * interval_s`` rather than
    one interval after the previous tick returned, so the time spent
    reading NVML does not accumulate into drift.

    Args:
        tick: Callback that receives the tick number from zero.
        duration_s: Length of the sampling window.
        interval_s: Target spacing between ticks.
        clock: Monotonic time source, injectable for tests.
        sleep: Sleep function, injectable for tests.
        until: Optional condition checked before each tick; sampling
            ends early once it returns True.

    Returns:
        The number of ticks performed.
    """
    count = int(duration_s // interval_s)
    start = clock()
    for number in range(count):
        delay = start + number * interval_s - clock()
        if delay > 0:
            sleep(delay)
        if until is not None and until():
            return number
        tick(number)
    return count


class TelemetryWriter:
    """Append samples to ``telemetry.jsonl``, flushing every line.

    Flushing per tick lets ``attach`` and a crash-time report read the
    file while the run is still in progress.
    """

    def __init__(self, path: Path) -> None:
        """Open ``path`` for appending."""
        self.handle: TextIO = path.open("a", encoding="utf-8", newline="\n")

    def write(self, records: Sequence[dict[str, Any]]) -> None:
        """Write one line per record and flush."""
        for record in records:
            self.handle.write(json.dumps(record, separators=(",", ":")))
            self.handle.write("\n")
        self.handle.flush()

    def close(self) -> None:
        """Close the file."""
        self.handle.close()
