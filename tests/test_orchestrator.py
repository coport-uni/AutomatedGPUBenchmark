"""Tests for the run orchestration up to the idle phase."""

import datetime as dt
import io
from pathlib import Path

import pynvml
import pytest

from conftest import FakeNvml, make_device
from gpubench import config, orchestrator
from gpubench.analysis.loader import load_result_dir
from gpubench.collectors import telemetry
from gpubench.runtime.exit_codes import ExitCode

host_dir = Path(__file__).parent / "fixtures" / "host_wsl2"


@pytest.fixture
def instant_sampler(monkeypatch):
    """Run the sampler without sleeping."""
    original = telemetry.run_sampler

    def frozen_clock():
        return 0.0

    def no_sleep(seconds):
        return None

    def fast(tick, duration_s, interval_s):
        return original(
            tick, duration_s, interval_s, clock=frozen_clock, sleep=no_sleep
        )

    monkeypatch.setattr(telemetry, "run_sampler", fast)


def write_comm(proc_root, pid, name):
    directory = proc_root / str(pid)
    directory.mkdir(parents=True)
    (directory / "comm").write_text(name + "\n", encoding="utf-8")


def test_leftover_gpu_burn_is_found(tmp_path):
    write_comm(tmp_path, 41, "bash")
    write_comm(tmp_path, 42, "gpu_burn")
    assert orchestrator.find_leftover_processes(tmp_path) == [(42, "gpu_burn")]


def test_result_dir_gets_suffix_when_taken(tmp_path):
    now = dt.datetime(2026, 9, 29, 1, 2, 3, tzinfo=dt.UTC)
    first = orchestrator.make_result_dir(tmp_path, "host", now)
    second = orchestrator.make_result_dir(tmp_path, "host", now)
    assert first.name == "host_20260929-010203"
    assert second.name == "host_20260929-010203-2"


def test_leftover_process_aborts_before_touching_nvml(tmp_path):
    write_comm(tmp_path / "proc", 7, "gpu_burn")
    nvml = FakeNvml([])
    options = orchestrator.RunOptions("quick", None, tmp_path / "results")
    out = io.StringIO()
    code = orchestrator.run(options, nvml, out, proc_root=tmp_path / "proc")
    assert code == ExitCode.ERROR
    assert "gpu_burn still running" in out.getvalue()
    assert not nvml.initialised
    assert not (tmp_path / "results").exists()


def test_mixed_classes_abort(tmp_path, fake_system):
    nvml = FakeNvml(
        [
            make_device(0, pynvml.NVML_BRAND_GEFORCE),
            make_device(1, pynvml.NVML_BRAND_TESLA),
        ],
        fake_system,
    )
    options = orchestrator.RunOptions("quick", None, tmp_path)
    out = io.StringIO()
    code = orchestrator.run(options, nvml, out, proc_root=tmp_path)
    assert code == ExitCode.ERROR
    assert "--gpu-class" in out.getvalue()


def test_quick_run_writes_preflight_and_idle(
    tmp_path, fake_system, instant_sampler
):
    nvml = FakeNvml(
        [
            make_device(i, pynvml.NVML_BRAND_QUADRO_RTX, ecc=False)
            for i in (0, 1)
        ],
        fake_system,
    )
    options = orchestrator.RunOptions("quick", None, tmp_path / "results")
    out = io.StringIO()
    code = orchestrator.run(
        options, nvml, out, proc_root=tmp_path, host_root=host_dir
    )
    assert code == ExitCode.INCOMPLETE
    (result_dir,) = (tmp_path / "results").iterdir()
    run = load_result_dir(result_dir)
    assert run.phases == ["preflight", "idle"]
    expected_run = {"profile": "quick", "gpu_class": "workstation"}
    assert run.sysinfo["run"] == expected_run
    idle = [s for s in run.samples if s["phase"] == "idle"]
    per_gpu = len(idle) // len(run.gpu_indices)
    assert per_gpu == config.load_profile("quick")["phases"]["idle_s"]
    assert all(s["ecc_corr"] is None for s in run.samples)
    assert not nvml.initialised
