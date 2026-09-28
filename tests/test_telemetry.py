"""Tests for NVML sampling and the sampling scheduler."""

import datetime as dt
import json

import pynvml
import pytest

from conftest import FakeNvml, make_device, nvml_error
from gpubench import detect
from gpubench.analysis.loader import load_telemetry, telemetry_fields
from gpubench.collectors import telemetry

interval_s = 1.0
read_cost_s = 0.3


def gpu_handle(nvml, index=0):
    return telemetry.GpuHandle(
        index,
        f"GPU-fake-{index}",
        index,
        frozenset(detect.probe_unsupported(nvml, index)),
    )


def test_sample_follows_loader_field_order():
    nvml = FakeNvml([make_device(0, pynvml.NVML_BRAND_NVIDIA)])
    record = telemetry.sample(nvml, gpu_handle(nvml), "idle", "t")
    assert tuple(record) == telemetry_fields


def test_sample_converts_units():
    device = make_device(0, pynvml.NVML_BRAND_NVIDIA)
    nvml = FakeNvml([device])
    record = telemetry.sample(nvml, gpu_handle(nvml), "idle", "t")
    milliwatts = device["nvmlDeviceGetPowerUsage"]
    assert record["power_draw"] == milliwatts / telemetry.milliwatts_per_watt
    used = device["nvmlDeviceGetMemoryInfo"].used
    assert record["mem_used"] == used // telemetry.bytes_per_mib
    state = device["nvmlDeviceGetPerformanceState"]
    assert record["pstate"] == f"P{state}"


def test_unsupported_fields_are_null_and_not_read():
    device = make_device(
        0, pynvml.NVML_BRAND_QUADRO_RTX, ecc=False, memory_temp=None
    )
    nvml = FakeNvml([device])
    gpu = gpu_handle(nvml)
    calls = []

    def counting_remap(*args):
        calls.append(args)
        raise nvml_error()

    device["nvmlDeviceGetRemappedRows"] = counting_remap
    record = telemetry.sample(nvml, gpu, "idle", "t")
    assert calls == []
    for field in gpu.unsupported:
        assert record[field] is None
    assert record["temp_gpu"] is not None


def test_transient_error_on_supported_field_becomes_null():
    device = make_device(0, pynvml.NVML_BRAND_NVIDIA)
    nvml = FakeNvml([device])
    gpu = gpu_handle(nvml)
    device["nvmlDeviceGetPowerUsage"] = nvml_error(pynvml.NVML_ERROR_UNKNOWN)
    record = telemetry.sample(nvml, gpu, "idle", "t")
    assert record["power_draw"] is None
    assert record["temp_gpu"] is not None


def test_legacy_throttle_reason_name_is_used_when_new_one_is_missing():
    device = make_device(0, pynvml.NVML_BRAND_NVIDIA)
    reasons = device.pop("nvmlDeviceGetCurrentClocksEventReasons")
    device["nvmlDeviceGetCurrentClocksThrottleReasons"] = reasons

    class LegacyNvml(FakeNvml):
        def __getattr__(self, name):
            if name == "nvmlDeviceGetCurrentClocksEventReasons":
                raise AttributeError(name)
            return super().__getattr__(name)

    nvml = LegacyNvml([device])
    record = telemetry.sample(nvml, gpu_handle(nvml), "idle", "t")
    assert record["clk_event_reasons"] == reasons


class FakeClock:
    """Monotonic clock that advances only when told to."""

    def __init__(self):
        self.now = 0.0
        self.tick_times = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def tick(self, number):
        self.tick_times.append(self.now)
        self.now += read_cost_s


def test_scheduler_does_not_drift_with_read_cost():
    clock = FakeClock()
    duration_s = 10 * interval_s
    count = telemetry.run_sampler(
        clock.tick, duration_s, interval_s, clock=clock, sleep=clock.sleep
    )
    assert count == int(duration_s // interval_s)
    expected = [number * interval_s for number in range(count)]
    assert clock.tick_times == expected


def test_scheduler_catches_up_after_a_slow_tick():
    clock = FakeClock()
    slow_s = 2.5 * interval_s

    def tick(number):
        clock.tick_times.append(clock.now)
        clock.now += slow_s if number == 0 else read_cost_s

    telemetry.run_sampler(
        tick, 5 * interval_s, interval_s, clock=clock, sleep=clock.sleep
    )
    # Ticks 1 to 3 are overdue and run back to back without sleeping;
    # tick 4 is back on the original grid.
    overdue = clock.tick_times[1:4]
    gaps = [b - a for a, b in zip(overdue, overdue[1:], strict=False)]
    assert gaps == pytest.approx([read_cost_s] * len(gaps))
    assert clock.tick_times[4] == 4 * interval_s


def test_utc_timestamp_has_milliseconds_and_z_suffix():
    moment = dt.datetime(2026, 9, 29, 1, 2, 3, 456789, tzinfo=dt.UTC)
    assert telemetry.utc_timestamp(moment) == "2026-09-29T01:02:03.456Z"


def test_writer_output_passes_the_loader(tmp_path):
    nvml = FakeNvml([make_device(i, pynvml.NVML_BRAND_NVIDIA) for i in (0, 1)])
    gpus = [gpu_handle(nvml, i) for i in (0, 1)]
    path = tmp_path / "telemetry.jsonl"
    writer = telemetry.TelemetryWriter(path)
    writer.write([telemetry.sample(nvml, g, "idle", "t") for g in gpus])
    writer.close()
    samples = load_telemetry(path)
    assert [s["gpu_index"] for s in samples] == [0, 1]
    assert json.loads(path.read_text().splitlines()[0])["phase"] == "idle"
