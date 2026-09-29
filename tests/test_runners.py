"""Parser and command-line tests for the gpu_burn and cuda_memtest runners.

Logs whose names start with ``synthetic_`` are hand-written from the
tools' format strings; the others were captured on 2x Quadro RTX 6000
on 2026-09-28 (see tests/fixtures/README.md).
"""

import os
import re
import sys
import time
from pathlib import Path

import pytest

from gpubench.runners import base, cuda_memtest, gpu_burn

logs = Path(__file__).parent / "fixtures" / "logs"


def read_log(name):
    return (logs / name).read_text(encoding="utf-8")


def test_gpu_burn_command_uses_absolute_compare_kernel(tmp_path):
    binary = tmp_path / "gpu_burn"
    argv = gpu_burn.build_command(45, 90, binary=str(binary))
    assert argv[0] == str(binary)
    assert argv[argv.index("-m") + 1] == "90%"
    kernel = Path(argv[argv.index("-c") + 1])
    assert kernel.is_absolute()
    assert kernel.name == gpu_burn.compare_kernel_name
    assert argv[-1] == "45"
    assert "-d" not in argv and "-tc" not in argv


def test_gpu_burn_optional_flags():
    argv = gpu_burn.build_command(10, 50, True, True, 5, binary="gpu_burn")
    assert "-d" in argv and "-tc" in argv
    assert argv[argv.index("-stts") + 1] == "5"
    assert argv[-1] == "10"


def test_real_gpu_burn_log_is_complete_and_ok():
    text = read_log("gpu_burn_quadro_rtx6000_x2_ok.log")
    result = gpu_burn.parse(text)
    assert result.complete
    assert not result.faulty
    assert [g.index for g in result.gpus] == [0, 1]
    assert [g.verdict for g in result.gpus] == ["OK", "OK"]
    # Every throughput figure printed in the log must end up in a sample.
    printed = {float(v) for v in re.findall(r"\((\d+) Gflop/s\)", text)}
    parsed = {v for g in result.gpus for v in g.gflops_samples}
    assert parsed <= printed
    assert max(printed) == max(g.gflops_max for g in result.gpus)


def test_synthetic_faulty_log_sums_error_windows():
    result = gpu_burn.parse(read_log("synthetic_gpu_burn_faulty.log"))
    gpu0, gpu1 = result.gpus
    assert result.complete and result.faulty
    assert gpu0.errors == 0 and gpu0.verdict == "OK"
    # Windows end at each summary: 3, then max(2, 5) as the last value.
    first_window, second_window = 3, 5
    assert gpu1.errors == first_window + second_window
    assert gpu1.died
    assert gpu1.verdict == "FAULTY"


def test_truncated_gpu_burn_log_is_incomplete():
    text = read_log("gpu_burn_quadro_rtx6000_x2_ok.log")
    truncated = text[: text.index("Tested")]
    result = gpu_burn.parse(truncated)
    assert not result.complete
    assert result.records > 0


def test_cuda_memtest_command_per_device():
    argv = cuda_memtest.build_command(1)
    assert argv[argv.index("--device") + 1] == "1"
    assert "--stress" in argv
    passes = int(argv[argv.index("--num_passes") + 1])
    assert passes == cuda_memtest.unbounded_passes


def test_cuda_memtest_without_stress_still_exits_on_error():
    argv = cuda_memtest.build_command(0, stress=False)
    assert "--stress" not in argv and "--exit_on_error" in argv


def test_real_cuda_memtest_log_passes():
    text = read_log("cuda_memtest_quadro_rtx6000_dev0_ok.log")
    result = cuda_memtest.parse(text, 0)
    assert not result.failed
    assert result.tests_finished == text.count("finished in")
    assert result.allocated_mib is not None


def test_terminated_cuda_memtest_log_counts_finished_tests():
    text = read_log("cuda_memtest_quadro_rtx6000_dev1_terminated.log")
    result = cuda_memtest.parse(text, 1)
    assert not result.failed
    assert result.tests_finished == text.count("finished in")


def test_synthetic_cuda_memtest_errors_are_counted():
    text = read_log("synthetic_cuda_memtest_errors.log")
    result = cuda_memtest.parse(text, 0)
    first_block, second_block = 4, 2
    assert result.pattern_errors == first_block + second_block
    assert result.failed
    assert result.tests_finished == 1


def test_tool_process_writes_log_and_exit_status(tmp_path):
    log = tmp_path / "logs" / "tool.log"
    argv = [sys.executable, "-c", "print('hello'); raise SystemExit(3)"]
    process = base.ToolProcess(argv, log)
    assert process.finish() == 3
    assert process.read_log().strip() == "hello"
    assert not process.stopped


@pytest.mark.skipif(os.name != "posix", reason="process groups need POSIX")
def test_stop_terminates_the_whole_group(tmp_path):
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(60)'])\n"
        f"open({str(child_pid_file)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    process = base.ToolProcess([sys.executable, "-c", script], tmp_path / "l")
    deadline = time.monotonic() + 10
    while not child_pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    child_pid = int(child_pid_file.read_text())
    process.stop(grace_s=5)
    assert process.stopped
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def is_running(pid):
    """Return whether ``pid`` exists and is not a zombie (Linux)."""
    try:
        status = Path(f"/proc/{pid}/status").read_text()
    except FileNotFoundError:
        return False
    state = next(line for line in status.splitlines() if line[:6] == "State:")
    return "Z" not in state.split()[1]


@pytest.mark.skipif(
    not Path("/proc/self/status").exists(), reason="needs Linux /proc"
)
def test_stop_kills_a_worker_that_ignores_sigterm(tmp_path):
    child_pid_file = tmp_path / "child.pid"
    worker = (
        "import signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
    )
    script = (
        "import subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, '-c', {worker!r}])\n"
        f"open({str(child_pid_file)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    process = base.ToolProcess([sys.executable, "-c", script], tmp_path / "l")
    deadline = time.monotonic() + 10
    while not child_pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.5)
    child_pid = int(child_pid_file.read_text())
    process.stop(grace_s=5)
    time.sleep(0.2)
    assert not is_running(child_pid)
