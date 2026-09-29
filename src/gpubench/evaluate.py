"""Grade a result folder against the rules of DevSpec section 4.4.

Only thresholds documented by NVIDIA or by the tool in use are graded.
Grades follow DCGM error severity: ISOLATE and RESET map to FAIL,
MONITOR maps to WARN, and a rule that cannot apply is N/A. Reference
values (SM clock retention, steady mean temperature, maximum power) are
reported but never graded.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from gpubench import config
from gpubench.analysis import loader
from gpubench.analysis import metrics as metric_tools
from gpubench.analysis.metrics import GpuMetrics
from gpubench.runners import cuda_memtest, gpu_burn
from gpubench.runtime.exit_codes import ExitCode

logs_dir = "logs"
gpu_burn_log = "gpu_burn.log"
cuda_memtest_log = "cuda_memtest_gpu{index}.log"

# gpu-fryer fails a GPU whose throughput is more than 10 % below the
# fastest one (its default tolerance).
gpu_ratio_min_default = 0.90


class Grade(StrEnum):
    """Outcome of one rule for one GPU, or of the whole run."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    NA = "N/A"
    INCOMPLETE = "INCOMPLETE"


# Worst first; N/A never makes a run worse than PASS.
grade_rank = {Grade.FAIL: 3, Grade.WARN: 2, Grade.PASS: 1, Grade.NA: 0}

exit_codes = {
    Grade.PASS: ExitCode.PASS,
    Grade.WARN: ExitCode.WARN,
    Grade.FAIL: ExitCode.FAIL,
    Grade.INCOMPLETE: ExitCode.INCOMPLETE,
}


@dataclass(frozen=True)
class Context:
    """Run-wide values a rule may need besides the GPU's own metrics."""

    gflops_best: float | None
    gpu_count: int
    gpu_ratio_min: float


Check = Callable[[GpuMetrics, Context], tuple[Grade, str]]


@dataclass(frozen=True)
class Rule:
    """One graded criterion with the source of its threshold."""

    key: str
    title: str
    criterion: str
    source: str
    check: Check


def check_compute(m: GpuMetrics, ctx: Context) -> tuple[Grade, str]:
    """Return FAIL when gpu_burn saw errors or judged the GPU FAULTY."""
    if m.burn_verdict is None:
        return Grade.NA, "no verdict"
    failed = (
        m.burn_verdict == gpu_burn.verdict_faulty
        or bool(m.burn_errors)
        or bool(m.burn_died)
    )
    measured = f"{m.burn_verdict}, {m.burn_errors} errors"
    return (Grade.FAIL if failed else Grade.PASS), measured


def check_vram(m: GpuMetrics, ctx: Context) -> tuple[Grade, str]:
    """Return FAIL for any cuda_memtest pattern error."""
    if m.vram_errors is None:
        return Grade.NA, "not run"
    measured = f"{m.vram_errors} errors in {m.vram_tests} tests"
    return (Grade.FAIL if m.vram_errors else Grade.PASS), measured


def check_ecc(m: GpuMetrics, ctx: Context) -> tuple[Grade, str]:
    """Return FAIL when uncorrectable (double-bit) ECC errors increased."""
    if m.ecc_uncorr_increase is None:
        return Grade.NA, "ECC not reported"
    measured = f"+{m.ecc_uncorr_increase}"
    return (Grade.FAIL if m.ecc_uncorr_increase else Grade.PASS), measured


def throttle_check(names: tuple[str, ...]) -> Check:
    """Build a WARN check for time spent in the given event reasons."""

    def check(m: GpuMetrics, ctx: Context) -> tuple[Grade, str]:
        seconds = [m.throttle_s.get(name) for name in names]
        if any(s is None for s in seconds):
            return Grade.NA, "reasons not reported"
        total = sum(seconds)
        return (Grade.WARN if total else Grade.PASS), f"{total:g} s"

    return check


def check_temperature(m: GpuMetrics, ctx: Context) -> tuple[Grade, str]:
    """Return WARN when the GPU reached its reported slowdown temperature."""
    if m.temp_max is None or m.temp_slowdown is None:
        return Grade.NA, "temperature or limit not reported"
    measured = f"{m.temp_max:g} C (limit {m.temp_slowdown:g} C)"
    below = m.temp_max < m.temp_slowdown
    return (Grade.PASS if below else Grade.WARN), measured


def check_gpu_ratio(m: GpuMetrics, ctx: Context) -> tuple[Grade, str]:
    """Return FAIL when throughput trails the fastest GPU too far."""
    if ctx.gpu_count < 2:
        return Grade.NA, "single GPU"
    if m.gflops_mean is None or not ctx.gflops_best:
        return Grade.NA, "no throughput"
    ratio = m.gflops_mean / ctx.gflops_best
    measured = f"{ratio:.1%} of fastest ({m.gflops_mean:.0f} Gflop/s)"
    return (Grade.PASS if ratio >= ctx.gpu_ratio_min else Grade.FAIL), measured


rules = (
    Rule(
        "compute_errors",
        "Compute errors",
        "gpu_burn reports OK",
        "gpu-burn verdict",
        check_compute,
    ),
    Rule(
        "vram_errors",
        "VRAM pattern errors",
        "0 errors",
        "DCGM memtest: any error fails",
        check_vram,
    ),
    Rule(
        "ecc_dbe",
        "ECC uncorrectable increase",
        "0",
        "DCGM: DBE error is ISOLATE",
        check_ecc,
    ),
    Rule(
        "hw_slowdown",
        "HW slowdown, HW thermal, power brake",
        "never active",
        "NVML clocks event reasons; DCGM clocks event is MONITOR",
        throttle_check(("hw_slowdown", "hw_thermal", "power_brake")),
    ),
    Rule(
        "sw_thermal",
        "SW thermal slowdown",
        "never active",
        "NVML clocks event reasons; DCGM clocks event is MONITOR",
        throttle_check(("sw_thermal",)),
    ),
    Rule(
        "temperature",
        "Maximum temperature",
        "below the reported GPU slowdown temperature",
        "nvidia-smi; DCGM temperature violation is MONITOR",
        check_temperature,
    ),
    Rule(
        "gpu_ratio",
        "GPU-to-GPU throughput",
        "at least 90 % of the fastest GPU",
        "gpu-fryer default tolerance 10 %",
        check_gpu_ratio,
    ),
)


def incomplete_reasons(
    gpu_metrics: list[GpuMetrics],
    burn: gpu_burn.GpuBurnResult | None,
) -> list[str]:
    """Return why the run cannot be graded; empty when it can."""
    reasons = []
    if burn is None:
        reasons.append("gpu_burn log missing")
    elif not burn.complete:
        reasons.append("gpu_burn did not report a verdict for every GPU")
    for m in gpu_metrics:
        if m.judged_samples == 0:
            reasons.append(f"gpu{m.index}: no telemetry in the judged phases")
        if m.vram_tests is None:
            reasons.append(f"gpu{m.index}: cuda_memtest log missing")
        elif m.vram_tests == 0 and not m.vram_errors:
            reasons.append(f"gpu{m.index}: cuda_memtest finished no test")
        if m.vram_tool_error:
            reasons.append(
                f"gpu{m.index}: cuda_memtest error: {m.vram_tool_error}"
            )
    return reasons


def evaluate(
    gpu_metrics: list[GpuMetrics],
    burn: gpu_burn.GpuBurnResult | None,
    gpu_ratio_min: float = gpu_ratio_min_default,
) -> dict[str, Any]:
    """Grade every rule for every GPU and derive the run verdict."""
    means = [m.gflops_mean for m in gpu_metrics if m.gflops_mean]
    ctx = Context(max(means, default=None), len(gpu_metrics), gpu_ratio_min)
    rule_results = []
    worst = Grade.NA
    for rule in rules:
        per_gpu = []
        for m in gpu_metrics:
            grade, measured = rule.check(m, ctx)
            per_gpu.append(
                {"index": m.index, "grade": str(grade), "measured": measured}
            )
            if grade_rank[grade] > grade_rank[worst]:
                worst = grade
        rule_results.append(
            {
                "key": rule.key,
                "title": rule.title,
                "criterion": rule.criterion,
                "source": rule.source,
                "gpus": per_gpu,
            }
        )
    reasons = incomplete_reasons(gpu_metrics, burn)
    if reasons:
        verdict = Grade.INCOMPLETE
    elif worst == Grade.NA:
        verdict = Grade.PASS
    else:
        verdict = worst
    return {
        "verdict": str(verdict),
        "exit_code": int(exit_codes[verdict]),
        "incomplete_reasons": reasons,
        "rules": rule_results,
        "gpus": [m.as_dict() for m in gpu_metrics],
    }


def interval_of(sysinfo: dict[str, Any]) -> float:
    """Return the sampling interval recorded for the run."""
    run = sysinfo.get("run", {})
    if "sampling_interval_s" in run:
        return run["sampling_interval_s"]
    default = config.load_yaml(config.config_dir() / config.default_file)
    return default["sampling_interval_s"]


def evaluate_result_dir(result_dir: Path) -> dict[str, Any]:
    """Re-read a result folder and return its evaluation.

    The tool logs are parsed again rather than read from
    ``summary.json``, so an old folder can be re-evaluated after a
    parser fix.
    """
    run = loader.load_result_dir(result_dir)
    burn_path = result_dir / logs_dir / gpu_burn_log
    burn = None
    if burn_path.is_file():
        burn = gpu_burn.parse(burn_path.read_text(errors="replace"))
    memtest = {}
    for gpu in run.sysinfo["gpus"]:
        path = result_dir / logs_dir / cuda_memtest_log.format(**gpu)
        if path.is_file():
            text = path.read_text(errors="replace")
            memtest[gpu["index"]] = cuda_memtest.parse(text, gpu["index"])
    gpu_metrics = metric_tools.compute(
        run.samples, run.sysinfo, interval_of(run.sysinfo), burn, memtest
    )
    ratio_min = run.sysinfo.get("run", {}).get(
        "gpu_ratio_min", gpu_ratio_min_default
    )
    return evaluate(gpu_metrics, burn, ratio_min)


def mark_interrupted(evaluation: dict[str, Any], reason: str) -> None:
    """Force the verdict of an interrupted run to INCOMPLETE.

    The rule grades stay as measured, so the report still shows what
    was found before the stop (DevSpec 4.8).
    """
    evaluation["incomplete_reasons"] = [
        reason,
        *evaluation.get("incomplete_reasons", []),
    ]
    evaluation["verdict"] = Grade.INCOMPLETE.value
    evaluation["exit_code"] = int(ExitCode.INCOMPLETE)


def write_evaluation(
    result_dir: Path, summary_file: str, interrupted: str | None = None
) -> dict[str, Any]:
    """Evaluate ``result_dir`` and merge the result into its summary.

    Args:
        result_dir: Result folder to evaluate.
        summary_file: Name of the summary inside ``result_dir``.
        interrupted: Reason the run was stopped early, if it was; the
            verdict is then INCOMPLETE regardless of the grades.
    """
    evaluation = evaluate_result_dir(result_dir)
    if interrupted:
        mark_interrupted(evaluation, interrupted)
    path = result_dir / summary_file
    summary = json.loads(path.read_text()) if path.is_file() else {}
    summary.update(evaluation)
    summary["status"] = evaluation["verdict"]
    summary.pop("reason", None)
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return evaluation
