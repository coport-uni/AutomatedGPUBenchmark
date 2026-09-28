"""Tests for the run orchestration up to the idle phase."""

import datetime as dt
import io
import json
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


class FakeProcess:
    """Stands in for ToolProcess: copies a captured log and exits 0."""

    def __init__(self, argv, log_path, source):
        self.argv = list(argv)
        self.log_path = log_path
        self.stopped = False
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_bytes(source.read_bytes())

    def poll(self):
        return 0

    def wait(self, timeout_s=None):
        return 0

    def stop(self, grace_s=None):
        return 0

    def finish(self):
        return 0

    def read_log(self):
        return self.log_path.read_text(encoding="utf-8")


def fake_launcher(launched):
    def launch(argv, log_path):
        name = Path(argv[0]).name
        source = logs_dir / launched_logs[name]
        process = FakeProcess(argv, log_path, source)
        launched.append(process)
        return process

    return launch


logs_dir = Path(__file__).parent / "fixtures" / "logs"
launched_logs = {
    "gpu_burn": "gpu_burn_quadro_rtx6000_x2_ok.log",
    "cuda_memtest": "cuda_memtest_quadro_rtx6000_dev0_ok.log",
}
expected_phases = [
    "preflight",
    "idle",
    "burn_warmup",
    "burn_steady",
    "cooldown",
    "vram",
]


def test_phase_at_follows_the_schedule():
    schedule = [("a", 2.0), ("b", 3.0)]
    assert [orchestrator.phase_at(schedule, t) for t in range(6)] == [
        "a",
        "a",
        "b",
        "b",
        "b",
        "b",
    ]


def test_quick_run_goes_through_every_phase(
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
    launched = []
    code = orchestrator.run(
        options,
        nvml,
        out,
        proc_root=tmp_path,
        host_root=host_dir,
        launch=fake_launcher(launched),
    )
    assert code == ExitCode.INCOMPLETE
    (result_dir,) = (tmp_path / "results").iterdir()
    run = load_result_dir(result_dir)
    assert run.phases == expected_phases
    expected_run = {"profile": "quick", "gpu_class": "workstation"}
    assert run.sysinfo["run"] == expected_run
    profile = config.load_profile("quick")
    idle = [s for s in run.samples if s["phase"] == "idle"]
    assert len(idle) // len(run.gpu_indices) == profile["phases"]["idle_s"]
    assert all(s["ecc_corr"] is None for s in run.samples)
    assert [Path(p.argv[0]).name for p in launched] == [
        "gpu_burn",
        "cuda_memtest",
        "cuda_memtest",
    ]
    burn_seconds = profile["phases"]["burn_warmup_s"]
    burn_seconds += profile["phases"]["burn_steady_s"]
    assert launched[0].argv[-1] == str(burn_seconds)
    summary = json.loads((result_dir / "summary.json").read_text())
    assert summary["status"] == "INCOMPLETE"
    burn = summary["runners"]["gpu_burn"]
    assert burn["complete"]
    assert [g["verdict"] for g in burn["gpus"]] == ["OK", "OK"]
    assert [m["index"] for m in summary["runners"]["cuda_memtest"]] == [0, 1]
    assert (result_dir / "logs" / "gpu_burn.log").is_file()
    assert "Gflop/s" not in out.getvalue().replace("Gflop/s max", "")
    assert not nvml.initialised
