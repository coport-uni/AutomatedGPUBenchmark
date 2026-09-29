"""Tests for the verdict rules of DevSpec 4.4 and the exit-code mapping.

Rule tests build ``GpuMetrics`` directly so each grade is reached by
exactly one changed value. The run-level tests use two real result
folders from quick runs on 2x Quadro RTX 6000 (2026-09-28).
"""

import json
import shutil
from pathlib import Path

import pytest

from gpubench import evaluate
from gpubench.analysis import metrics
from gpubench.analysis.metrics import GpuMetrics
from gpubench.evaluate import Grade
from gpubench.runners.gpu_burn import GpuBurnGpu, GpuBurnResult
from gpubench.runtime.exit_codes import ExitCode

runs_dir = Path(__file__).parent / "fixtures" / "runs"
slowdown_c = 91.0
healthy_gflops = 13000.0
reason_names = tuple(metrics.throttle_reasons)


def healthy(index=0, **changes):
    """Return metrics of a GPU that passes every rule."""
    values = {
        "index": index,
        "uuid": f"GPU-{index}",
        "name": "Test GPU",
        "judged_samples": 60,
        "temp_max": slowdown_c - 20,
        "temp_slowdown": slowdown_c,
        "throttle_s": dict.fromkeys(reason_names, 0.0),
        "ecc_uncorr_increase": 0,
        "gflops_mean": healthy_gflops,
        "burn_errors": 0,
        "burn_died": False,
        "burn_verdict": "OK",
        "vram_tests": 3,
        "vram_errors": 0,
    }
    values.update(changes)
    return GpuMetrics(**values)


def complete_burn(gpu_metrics):
    return GpuBurnResult(
        gpus=[
            GpuBurnGpu(m.index, [healthy_gflops], 0, False, m.burn_verdict)
            for m in gpu_metrics
        ],
        records=1,
        tested=len(gpu_metrics),
    )


def grade_of(result, key, index=0):
    (rule,) = [r for r in result["rules"] if r["key"] == key]
    return Grade(rule["gpus"][index]["grade"])


def run_rules(*gpu_metrics):
    return evaluate.evaluate(list(gpu_metrics), complete_burn(gpu_metrics))


def test_healthy_pair_passes_with_exit_zero():
    result = run_rules(healthy(0), healthy(1))
    assert result["verdict"] == Grade.PASS
    assert result["exit_code"] == ExitCode.PASS
    assert result["incomplete_reasons"] == []


@pytest.mark.parametrize(
    ("changes", "key", "grade"),
    [
        ({"burn_verdict": "FAULTY"}, "compute_errors", Grade.FAIL),
        ({"burn_errors": 1}, "compute_errors", Grade.FAIL),
        ({"burn_died": True}, "compute_errors", Grade.FAIL),
        ({"vram_errors": 1}, "vram_errors", Grade.FAIL),
        ({"ecc_uncorr_increase": 1}, "ecc_dbe", Grade.FAIL),
        ({"ecc_uncorr_increase": None}, "ecc_dbe", Grade.NA),
        ({"temp_max": slowdown_c}, "temperature", Grade.WARN),
        ({"temp_slowdown": None}, "temperature", Grade.NA),
    ],
)
def test_single_rule_grades(changes, key, grade):
    result = run_rules(healthy(0, **changes), healthy(1))
    assert grade_of(result, key) == grade
    assert grade_of(result, key, index=1) == Grade.PASS


@pytest.mark.parametrize(
    ("reason", "key"),
    [
        ("hw_slowdown", "hw_slowdown"),
        ("hw_thermal", "hw_slowdown"),
        ("power_brake", "hw_slowdown"),
        ("sw_thermal", "sw_thermal"),
    ],
)
def test_throttle_reasons_warn(reason, key):
    throttle = dict.fromkeys(reason_names, 0.0)
    throttle[reason] = 3.0
    result = run_rules(healthy(0, throttle_s=throttle))
    assert grade_of(result, key) == Grade.WARN
    assert result["verdict"] == Grade.WARN
    assert result["exit_code"] == ExitCode.WARN


def test_power_cap_alone_is_not_graded():
    throttle = dict.fromkeys(reason_names, 0.0)
    throttle["sw_power_cap"] = 60.0
    result = run_rules(healthy(0, throttle_s=throttle))
    assert result["verdict"] == Grade.PASS


def test_unreported_reasons_are_not_applicable():
    result = run_rules(healthy(0, throttle_s=dict.fromkeys(reason_names)))
    assert grade_of(result, "hw_slowdown") == Grade.NA
    assert grade_of(result, "sw_thermal") == Grade.NA
    assert result["verdict"] == Grade.PASS


def test_gpu_ratio_fails_below_tolerance():
    slow = healthy_gflops * (evaluate.gpu_ratio_min_default - 0.01)
    result = run_rules(healthy(0), healthy(1, gflops_mean=slow))
    assert grade_of(result, "gpu_ratio") == Grade.PASS
    assert grade_of(result, "gpu_ratio", index=1) == Grade.FAIL
    assert result["exit_code"] == ExitCode.FAIL


def test_gpu_ratio_at_tolerance_passes():
    edge = healthy_gflops * evaluate.gpu_ratio_min_default
    result = run_rules(healthy(0), healthy(1, gflops_mean=edge))
    assert grade_of(result, "gpu_ratio", index=1) == Grade.PASS


def test_gpu_ratio_is_not_applicable_to_a_single_gpu():
    assert grade_of(run_rules(healthy(0)), "gpu_ratio") == Grade.NA


def test_fail_outranks_warn():
    result = run_rules(
        healthy(0, temp_max=slowdown_c), healthy(1, vram_errors=2)
    )
    assert result["verdict"] == Grade.FAIL


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"judged_samples": 0}, "no telemetry"),
        ({"vram_tests": None, "vram_errors": None}, "log missing"),
        ({"vram_tests": 0}, "finished no test"),
        ({"vram_tool_error": "ERROR: CUDA error"}, "cuda_memtest error"),
    ],
)
def test_missing_results_make_the_run_incomplete(changes, fragment):
    result = run_rules(healthy(0, **changes))
    assert result["verdict"] == Grade.INCOMPLETE
    assert result["exit_code"] == ExitCode.INCOMPLETE
    assert any(fragment in r for r in result["incomplete_reasons"])


def test_missing_burn_log_is_incomplete():
    result = evaluate.evaluate([healthy(0)], None)
    assert result["verdict"] == Grade.INCOMPLETE


def test_every_rule_names_its_source():
    for rule in evaluate.rules:
        assert rule.source and rule.criterion


def test_real_complete_run_passes(tmp_path):
    result = evaluate.evaluate_result_dir(runs_dir / "workstation_quick_ok")
    assert result["verdict"] == Grade.PASS
    gpus = {g["index"]: g for g in result["gpus"]}
    assert set(gpus) == {0, 1}
    for gpu in gpus.values():
        # Both boards ran at their power limit (SW power cap) without
        # any graded slowdown.
        assert gpu["throttle_s"]["sw_power_cap"] > 0
        assert gpu["throttle_s"]["hw_slowdown"] == 0
        assert gpu["temp_max"] < gpu["temp_slowdown"]
        assert gpu["ecc_uncorr_increase"] is None
    assert grade_of(result, "ecc_dbe") == Grade.NA


def test_real_run_without_gpu_burn_verdict_is_incomplete():
    folder = runs_dir / "workstation_quick_lost_verdict"
    result = evaluate.evaluate_result_dir(folder)
    assert result["verdict"] == Grade.INCOMPLETE
    assert "gpu_burn did not report" in result["incomplete_reasons"][0]


def test_write_evaluation_updates_summary(tmp_path):
    folder = tmp_path / "run"
    shutil.copytree(runs_dir / "workstation_quick_ok", folder)
    evaluate.write_evaluation(folder, "summary.json")
    summary = json.loads((folder / "summary.json").read_text())
    assert summary["status"] == Grade.PASS
    assert "runners" in summary
    assert "reason" not in summary
