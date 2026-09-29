"""Per-GPU metrics that the verdict and the report are built from.

Every value is derived from the result folder alone: telemetry,
``sysinfo.json``, and the raw tool logs. Values a GPU cannot report
stay ``None`` so the evaluation can grade them N/A.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pynvml

from gpubench.analysis import phases as phase_tools
from gpubench.runners.cuda_memtest import CudaMemtestResult
from gpubench.runners.gpu_burn import GpuBurnResult

# NVML clocks event reasons (group__nvmlClocksEventReasons). The first
# three are hardware-initiated slowdowns, graded together.
reason_hw_slowdown = pynvml.nvmlClocksEventReasonHwSlowdown
reason_hw_thermal = pynvml.nvmlClocksEventReasonHwThermalSlowdown
reason_power_brake = pynvml.nvmlClocksEventReasonHwPowerBrakeSlowdown
reason_sw_thermal = pynvml.nvmlClocksEventReasonSwThermalSlowdown
reason_sw_power_cap = pynvml.nvmlClocksEventReasonSwPowerCap

throttle_reasons = {
    "hw_slowdown": reason_hw_slowdown,
    "hw_thermal": reason_hw_thermal,
    "power_brake": reason_power_brake,
    "sw_thermal": reason_sw_thermal,
    "sw_power_cap": reason_sw_power_cap,
}


@dataclass
class GpuMetrics:
    """Measured values of one GPU over the judged phases."""

    index: int
    uuid: str
    name: str
    judged_samples: int = 0
    temp_max: float | None = None
    temp_slowdown: float | None = None
    temp_steady_mean: float | None = None
    power_max: float | None = None
    clk_sm_max_rated: float | None = None
    clk_sm_steady_mean: float | None = None
    throttle_s: dict[str, float | None] = field(default_factory=dict)
    ecc_uncorr_increase: int | None = None
    ecc_corr_increase: int | None = None
    gflops_mean: float | None = None
    gflops_max: float | None = None
    burn_errors: int | None = None
    burn_died: bool | None = None
    burn_verdict: str | None = None
    vram_tests: int | None = None
    vram_errors: int | None = None
    vram_tool_error: str | None = None

    @property
    def clk_sm_retention(self) -> float | None:
        """Return the steady SM clock as a fraction of the rated maximum."""
        if not self.clk_sm_steady_mean or not self.clk_sm_max_rated:
            return None
        return self.clk_sm_steady_mean / self.clk_sm_max_rated

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready dictionary including derived values."""
        data = asdict(self)
        data["clk_sm_retention"] = self.clk_sm_retention
        return data


def values(samples: list[dict], key: str) -> list[float]:
    """Return the non-null values of ``key``."""
    return [s[key] for s in samples if s.get(key) is not None]


def mean(numbers: list[float]) -> float | None:
    """Return the arithmetic mean, or ``None`` for no numbers."""
    return sum(numbers) / len(numbers) if numbers else None


def counter_increase(samples: list[dict], key: str) -> int | None:
    """Return last minus first non-null value of a monotonic counter."""
    readings = values(samples, key)
    if not readings:
        return None
    return readings[-1] - readings[0]


def throttle_seconds(
    samples: list[dict], interval_s: float
) -> dict[str, float | None]:
    """Return seconds with each clocks event reason active.

    ``None`` means the GPU never reported the bitmask.
    """
    masks = values(samples, "clk_event_reasons")
    if not masks:
        return {name: None for name in throttle_reasons}
    return {
        name: sum(1 for mask in masks if mask & bit) * interval_s
        for name, bit in throttle_reasons.items()
    }


def compute(
    samples: list[dict],
    sysinfo: dict[str, Any],
    interval_s: float,
    burn: GpuBurnResult | None,
    memtest: dict[int, CudaMemtestResult],
) -> list[GpuMetrics]:
    """Compute metrics for every GPU listed in ``sysinfo``."""
    grouped = phase_tools.by_gpu_and_phase(samples)
    burn_by_gpu = {g.index: g for g in burn.gpus} if burn else {}
    results = []
    for gpu in sysinfo["gpus"]:
        index = gpu["index"]
        phases = grouped.get(index, {})
        judged = phase_tools.select(phases, phase_tools.judged_phases)
        steady = phases.get("burn_steady", [])
        everything = [s for rows in phases.values() for s in rows]
        metrics = GpuMetrics(
            index=index,
            uuid=gpu["uuid"],
            name=gpu["name"],
            judged_samples=len(judged),
            temp_max=max(values(judged, "temp_gpu"), default=None),
            temp_slowdown=gpu.get("temp_slowdown_c"),
            temp_steady_mean=mean(values(steady, "temp_gpu")),
            power_max=max(values(judged, "power_draw"), default=None),
            clk_sm_max_rated=gpu.get("clk_sm_max"),
            clk_sm_steady_mean=mean(values(steady, "clk_sm")),
            throttle_s=throttle_seconds(judged, interval_s),
            # Counters span the whole run, preflight baseline included.
            ecc_uncorr_increase=counter_increase(everything, "ecc_uncorr"),
            ecc_corr_increase=counter_increase(everything, "ecc_corr"),
        )
        burn_gpu = burn_by_gpu.get(index)
        if burn_gpu is not None:
            metrics.gflops_mean = burn_gpu.gflops_mean
            metrics.gflops_max = burn_gpu.gflops_max
            metrics.burn_errors = burn_gpu.errors
            metrics.burn_died = burn_gpu.died
            metrics.burn_verdict = burn_gpu.verdict
        vram = memtest.get(index)
        if vram is not None:
            metrics.vram_tests = vram.tests_finished
            metrics.vram_errors = vram.pattern_errors
            # An ERROR line without a block count (a CUDA error, for
            # example) means the test could not judge the memory.
            if not vram.pattern_errors and vram.error_lines:
                metrics.vram_tool_error = vram.error_lines[0]
        results.append(metrics)
    return results
