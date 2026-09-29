"""Tests for the run orchestration through every phase."""

import datetime as dt
import io
import json
import signal
from pathlib import Path

import pynvml
import pytest

from conftest import FakeNvml, make_device
from gpubench import config, orchestrator
from gpubench.analysis.loader import load_result_dir
from gpubench.collectors import telemetry
from gpubench.runtime import lock, signals
from gpubench.runtime import state as run_state
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

    def fast(tick, duration_s, interval_s, until=None):
        return original(
            tick,
            duration_s,
            interval_s,
            clock=frozen_clock,
            sleep=no_sleep,
            until=until,
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
    # The lock and state files exist, but no result folder.
    assert not [p for p in (tmp_path / "results").iterdir() if p.is_dir()]


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
    assert code == ExitCode.PASS
    (result_dir,) = [p for p in (tmp_path / "results").iterdir() if p.is_dir()]
    run = load_result_dir(result_dir)
    assert run.phases == expected_phases
    profile = config.load_profile("quick")
    assert run.sysinfo["run"]["profile"] == "quick"
    assert run.sysinfo["run"]["gpu_class"] == "workstation"
    interval = profile["sampling_interval_s"]
    assert run.sysinfo["run"]["sampling_interval_s"] == interval
    assert run.sysinfo["run"]["phases"] == profile["phases"]
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
    assert summary["status"] == "PASS"
    assert summary["exit_code"] == ExitCode.PASS
    burn = summary["runners"]["gpu_burn"]
    assert burn["complete"]
    assert [g["verdict"] for g in burn["gpus"]] == ["OK", "OK"]
    assert [m["index"] for m in summary["runners"]["cuda_memtest"]] == [0, 1]
    assert (result_dir / "logs" / "gpu_burn.log").is_file()
    # Raw tool output stays in logs/; progress records never reach the
    # console (DevSpec 4.8).
    assert "proc'd" not in out.getvalue()
    assert "Test10" not in out.getvalue()
    # The reports follow the verdict (DevSpec 4.5).
    for name in ("report.docx", "report.html", "report.md", "dashboard.html"):
        assert (result_dir / name).is_file()
    assert (result_dir / "charts" / "png" / "temperature.png").is_file()
    assert not nvml.initialised


def quadro_pair(fake_system):
    return FakeNvml(
        [
            make_device(i, pynvml.NVML_BRAND_QUADRO_RTX, ecc=False)
            for i in (0, 1)
        ],
        fake_system,
    )


def result_dirs(root):
    return [p for p in root.iterdir() if p.is_dir()]


def interrupting_launcher(launched, number):
    """Launch like fake_launcher, but deliver ``number`` at gpu_burn."""
    inner = fake_launcher(launched)

    def launch(argv, log_path):
        process = inner(argv, log_path)
        if Path(argv[0]).name == "gpu_burn":
            signal.raise_signal(number)
        return process

    return launch


@pytest.mark.parametrize("number", [signal.SIGINT, signal.SIGTERM])
def test_stop_signal_during_burn_gives_incomplete_report(
    tmp_path, fake_system, instant_sampler, number
):
    root = tmp_path / "results"
    options = orchestrator.RunOptions("quick", None, root)
    out = io.StringIO()
    code = orchestrator.run(
        options,
        quadro_pair(fake_system),
        out,
        proc_root=tmp_path,
        host_root=host_dir,
        launch=interrupting_launcher([], number),
    )
    name = signal.Signals(number).name
    assert code == ExitCode.INCOMPLETE
    (result_dir,) = result_dirs(root)
    summary = json.loads((result_dir / "summary.json").read_text())
    assert summary["verdict"] == "INCOMPLETE"
    assert summary["exit_code"] == ExitCode.INCOMPLETE
    assert summary["incomplete_reasons"][0] == f"interrupted by {name}"
    assert (result_dir / "report.docx").is_file()
    state = run_state.read_state(root)
    assert state["status"] == run_state.status_interrupted
    assert state["exit_code"] == ExitCode.INCOMPLETE
    assert not lock.is_held(root)
    text = out.getvalue()
    assert f"run: {name} received; stopping the test tools" in text
    assert "run: stopped; verdict INCOMPLETE" in text
    # console.log carries the same plain lines for attach.
    log = (result_dir / "console.log").read_text(encoding="utf-8")
    assert log.startswith("preflight: 2 GPU(s)")
    assert "run: stopped; verdict INCOMPLETE" in log
    # The default handlers are back after the run.
    assert signal.getsignal(number) is not signals.raise_interrupted


def test_second_run_is_refused_while_the_lock_is_held(tmp_path, fake_system):
    root = tmp_path / "results"
    holder = lock.RunLock(root)
    assert holder.acquire()
    try:
        nvml = quadro_pair(fake_system)
        out = io.StringIO()
        options = orchestrator.RunOptions("quick", None, root)
        code = orchestrator.run(options, nvml, out, proc_root=tmp_path)
    finally:
        holder.release()
    assert code == ExitCode.ERROR
    assert "another run holds" in out.getvalue()
    assert not nvml.initialised
    assert result_dirs(root) == []


def test_json_output_is_one_object_per_line(
    tmp_path, fake_system, instant_sampler
):
    options = orchestrator.RunOptions(
        "quick", None, tmp_path / "results", output="json"
    )
    out = io.StringIO()
    code = orchestrator.run(
        options,
        quadro_pair(fake_system),
        out,
        proc_root=tmp_path,
        host_root=host_dir,
        launch=fake_launcher([]),
    )
    assert code == ExitCode.PASS
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    kinds = {line["type"] for line in lines}
    assert kinds == {"event", "tick", "verdict"}
    (verdict,) = [line for line in lines if line["type"] == "verdict"]
    assert verdict["verdict"] == "PASS"


class SlowExitProcess(FakeProcess):
    """gpu_burn that keeps running for a few polls after its window."""

    running_polls = 3

    def poll(self):
        if self.running_polls:
            self.running_polls -= 1
            return None
        return 0


def test_telemetry_continues_while_gpu_burn_finishes(
    tmp_path, fake_system, instant_sampler
):
    def launch(argv, log_path):
        name = Path(argv[0]).name
        kind = SlowExitProcess if name == "gpu_burn" else FakeProcess
        return kind(argv, log_path, logs_dir / launched_logs[name])

    root = tmp_path / "results"
    code = orchestrator.run(
        orchestrator.RunOptions("quick", None, root),
        quadro_pair(fake_system),
        io.StringIO(),
        proc_root=tmp_path,
        host_root=host_dir,
        launch=launch,
    )
    assert code == ExitCode.PASS
    (result_dir,) = result_dirs(root)
    run = load_result_dir(result_dir)
    finish = [s for s in run.samples if s["phase"] == "burn_finish"]
    assert len(finish) == SlowExitProcess.running_polls * len(run.gpu_indices)
    assert run.phases.index("burn_finish") == run.phases.index("cooldown") - 1
