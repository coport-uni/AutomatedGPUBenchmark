"""Tests for console modes, the run lock, the state file, and signals."""

import io
import json
import signal
import sys

import pytest

from gpubench import evaluate
from gpubench.collectors import telemetry
from gpubench.console import live, mode, plain
from gpubench.console.mode import Tick
from gpubench.runtime import control, lock, signals
from gpubench.runtime import state as run_state
from gpubench.runtime.exit_codes import ExitCode

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="SIGHUP exists only on POSIX"
)
records = [
    {
        "gpu_index": 0,
        "temp_gpu": 61,
        "power_draw": 255.7,
        "clk_sm": 1545,
        "util_gpu": 100,
    },
    {
        "gpu_index": 1,
        "temp_gpu": 62,
        "power_draw": 252.6,
        "clk_sm": 1530,
        "util_gpu": 100,
    },
]
tick = Tick("burn_steady", 12, 30, records)


class FakeTty(io.StringIO):
    def isatty(self):
        return True


@pytest.mark.parametrize(
    ("requested", "stream", "term", "expected"),
    [
        ("auto", FakeTty(), "xterm", "live"),
        ("auto", io.StringIO(), "xterm", "plain"),
        ("auto", FakeTty(), "dumb", "plain"),
        ("json", FakeTty(), "xterm", "json"),
        ("plain", FakeTty(), "xterm", "plain"),
        ("live", io.StringIO(), "xterm", "live"),
    ],
)
def test_mode_resolution(requested, stream, term, expected):
    assert mode.resolve(requested, stream, {"TERM": term}) == expected


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        mode.resolve("fancy", io.StringIO(), {})


def test_plain_tick_line():
    out = io.StringIO()
    plain.PlainConsole(out).tick(tick)
    assert out.getvalue() == (
        "[burn_steady 12/30] gpu0 61 C 255.7 W 1545 MHz "
        "| gpu1 62 C 252.6 W 1530 MHz\n"
    )


def test_json_lines_are_objects_of_known_types():
    out = io.StringIO()
    console = plain.JsonConsole(out)
    console.event("burn: gpu_burn for 45 s")
    console.tick(tick)
    console.verdict(
        {"verdict": "PASS", "exit_code": 0, "rules": [], "gpus": [{}]}
    )
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [line["type"] for line in lines] == ["event", "tick", "verdict"]
    assert lines[1]["gpus"][1]["clk_sm"] == records[1]["clk_sm"]
    assert lines[2]["verdict"] == "PASS"
    assert "gpus" not in lines[2]


def test_live_redraws_the_status_block_in_place():
    out = io.StringIO()
    console = live.LiveConsole(out, clock=lambda: 0.0)
    console.tick(tick)
    first = out.getvalue()
    assert first.count("\n") == 1 + len(records)
    assert live.cursor_up_lines(1) not in first
    console.event("burn: gpu0 13953.0 Gflop/s max")
    console.tick(tick)
    block = 1 + len(records)
    erase = live.cursor_up_lines(block) + live.clear_to_end
    assert out.getvalue().count(erase) == 2
    assert "burn: gpu0 13953.0 Gflop/s max\n" in out.getvalue()
    assert "[" + live.bar_done * (live.bar_width * 12 // 30) in out.getvalue()


def test_buffered_log_writes_early_lines_once_opened(tmp_path):
    log = plain.BufferedLog()
    log.event("preflight: 2 GPU(s)")
    path = tmp_path / "console.log"
    log.open(path)
    log.event("burn: start")
    log.close()
    text = path.read_text(encoding="utf-8")
    assert text == "preflight: 2 GPU(s)\nburn: start\n"


def test_lock_admits_one_run(tmp_path):
    first = lock.RunLock(tmp_path)
    second = lock.RunLock(tmp_path)
    assert not lock.is_held(tmp_path)
    assert first.acquire()
    assert lock.is_held(tmp_path)
    assert not second.acquire()
    first.release()
    assert not lock.is_held(tmp_path)
    assert second.acquire()
    second.release()


def test_state_console_tracks_progress(tmp_path):
    tracker = run_state.StateConsole(tmp_path, pid=1234)
    tracker.set_result_dir(tmp_path / "host_20260929-000000")
    tracker.tick(tick)
    tracker.event("burn: gpu_burn for 45 s")
    state = run_state.read_state(tmp_path)
    assert state["pid"] == 1234
    assert state["status"] == run_state.status_running
    assert (state["phase"], state["number"], state["total"]) == (
        "burn_steady",
        12,
        30,
    )
    assert state["gpus"][0]["temp_gpu"] == records[0]["temp_gpu"]
    tracker.finish(run_state.status_interrupted, int(ExitCode.INCOMPLETE))
    state = run_state.read_state(tmp_path)
    assert state["status"] == run_state.status_interrupted
    assert state["exit_code"] == ExitCode.INCOMPLETE
    # The temporary file is renamed away, never left behind.
    assert [p.name for p in tmp_path.iterdir()] == [run_state.state_file]


def test_read_state_without_a_file(tmp_path):
    assert run_state.read_state(tmp_path) is None


@pytest.mark.parametrize("number", signals.stop_signals)
def test_stop_signals_raise_interrupted(number):
    with signals.run_signals():
        with pytest.raises(signals.Interrupted) as caught:
            signal.raise_signal(number)
    assert caught.value.name == signal.Signals(number).name
    assert signal.getsignal(number) is not signals.raise_interrupted


@posix_only
def test_sighup_is_ignored_during_a_run():
    with signals.run_signals():
        signal.raise_signal(signal.SIGHUP)
    assert signal.getsignal(signal.SIGHUP) is not signal.SIG_IGN


def test_shielded_cleanup_reports_instead_of_stopping():
    notes = []
    with signals.shielded(notes.append):
        signal.raise_signal(signal.SIGTERM)
    assert notes == ["run: SIGTERM ignored while the report is written"]


def test_mark_interrupted_forces_incomplete():
    evaluation = {
        "verdict": "PASS",
        "exit_code": 0,
        "incomplete_reasons": ["no samples"],
    }
    evaluate.mark_interrupted(evaluation, "interrupted by SIGINT")
    assert evaluation["verdict"] == "INCOMPLETE"
    assert evaluation["exit_code"] == ExitCode.INCOMPLETE
    assert evaluation["incomplete_reasons"][0] == "interrupted by SIGINT"


def test_sampler_stops_when_the_condition_holds():
    ticks = []
    polls = iter([False, False, True])
    count = telemetry.run_sampler(
        ticks.append,
        10,
        1,
        clock=lambda: 0.0,
        sleep=lambda s: None,
        until=lambda: next(polls),
    )
    assert count == 2
    assert ticks == [0, 1]


def running_state(root, result_dir, pid=4321):
    run_state.write_state(
        root,
        {
            "pid": pid,
            "status": run_state.status_running,
            "started": "2026-09-29T00:00:00.000Z",
            "result_dir": str(result_dir),
            "phase": "burn_steady",
            "number": 12,
            "total": 30,
            "last_event": "burn: gpu_burn for 45 s",
            "gpus": [{"index": r["gpu_index"], **r} for r in records[:1]],
        },
    )


def test_status_without_a_run(tmp_path):
    out = io.StringIO()
    assert control.status(tmp_path, out) == ExitCode.PASS
    assert out.getvalue() == "status: no run in progress\n"


def test_status_of_a_running_test(tmp_path):
    result_dir = tmp_path / "host_20260929-000000"
    running_state(tmp_path, result_dir)
    holder = lock.RunLock(tmp_path)
    assert holder.acquire()
    try:
        out = io.StringIO()
        assert control.status(tmp_path, out) == ExitCode.PASS
    finally:
        holder.release()
    text = out.getvalue()
    assert "status: running, pid 4321" in text
    assert "status: phase burn_steady 12/30" in text
    assert "status: gpu0 61 C 255.7 W 1545 MHz util 100 %" in text


def test_stop_without_a_run(tmp_path):
    out = io.StringIO()
    assert control.stop(tmp_path, out) == ExitCode.ERROR
    assert "no run in progress" in out.getvalue()


def test_stop_signals_the_run_and_waits(tmp_path):
    result_dir = tmp_path / "host_20260929-000000"
    running_state(tmp_path, result_dir)
    holder = lock.RunLock(tmp_path)
    assert holder.acquire()
    sent = []

    def fake_kill(pid, number):
        sent.append((pid, number))
        # The run handles SIGTERM, records its end, and drops the lock.
        state = run_state.read_state(tmp_path)
        state.update(status="interrupted", verdict="INCOMPLETE", exit_code=3)
        run_state.write_state(tmp_path, state)
        holder.release()

    out = io.StringIO()
    code = control.stop(tmp_path, out, kill=fake_kill, sleep=lambda s: None)
    assert code == ExitCode.PASS
    assert sent == [(4321, signal.SIGTERM)]
    assert "stop: run ended: interrupted, verdict INCOMPLETE, exit 3" in (
        out.getvalue()
    )


def test_attach_follows_the_log_until_the_run_ends(tmp_path):
    result_dir = tmp_path / "host_20260929-000000"
    result_dir.mkdir()
    log = result_dir / control.console_log_file
    log.write_text("preflight: 2 GPU(s)\n", encoding="utf-8")
    running_state(tmp_path, result_dir)
    holder = lock.RunLock(tmp_path)
    assert holder.acquire()

    def finish_run(seconds):
        with log.open("a", encoding="utf-8") as handle:
            handle.write("run: finished in 102 s; verdict PASS\n")
        state = run_state.read_state(tmp_path)
        state.update(status="finished", exit_code=0)
        run_state.write_state(tmp_path, state)
        holder.release()

    out = io.StringIO()
    code = control.attach(tmp_path, out, sleep=finish_run)
    assert code == ExitCode.PASS
    text = out.getvalue()
    assert "preflight: 2 GPU(s)\n" in text
    assert "run: finished in 102 s; verdict PASS\n" in text
    assert text.endswith("attach: run ended with exit 0\n")


def test_attach_without_a_run(tmp_path):
    out = io.StringIO()
    assert control.attach(tmp_path, out) == ExitCode.ERROR
