"""Tests for the host and GPU description in sysinfo.json."""

from pathlib import Path

import pynvml

from conftest import FakeNvml, make_device
from gpubench.analysis.loader import sysinfo_fields
from gpubench.collectors import sysinfo

host_dir = Path(__file__).parent / "fixtures" / "host_wsl2"
kib_per_mib = 1024


def read(relative):
    return (host_dir / relative).read_text(encoding="utf-8")


def field_values(text, key):
    return [
        line.partition(":")[2].strip()
        for line in text.splitlines()
        if line.partition(":")[0].strip() == key
    ]


def test_cpuinfo_counts_threads_and_physical_cores():
    text = read("proc/cpuinfo")
    info = sysinfo.parse_cpuinfo(text)
    assert info["threads"] == len(field_values(text, "processor"))
    # The kernel reports cores per socket; this capture has one socket.
    assert len(set(field_values(text, "physical id"))) == 1
    assert info["cores"] == int(field_values(text, "cpu cores")[0])
    assert info["model"] == field_values(text, "model name")[0]


def test_cpuinfo_without_topology_reports_unknown_cores():
    text = "processor\t: 0\nmodel name\t: X\n\nprocessor\t: 1\n"
    info = sysinfo.parse_cpuinfo(text)
    assert info == {"model": "X", "cores": None, "threads": 2}


def test_meminfo_total_in_mib():
    text = read("proc/meminfo")
    kib = int(field_values(text, "MemTotal")[0].split()[0])
    assert sysinfo.parse_meminfo(text) == {"total_mib": kib // kib_per_mib}


def test_os_release_pretty_name_is_unquoted():
    info = sysinfo.parse_os_release(read("etc/os-release"))
    assert info["name"].startswith("Ubuntu")
    assert '"' not in info["name"]


def test_collect_host_tolerates_missing_files(tmp_path):
    host = sysinfo.collect_host(tmp_path)
    assert host["cpu"] == {"model": None, "cores": None, "threads": None}
    assert host["memory"] == {"total_mib": None, "configuration": None}


def test_describe_gpu_reports_class_and_thresholds():
    device = make_device(0, pynvml.NVML_BRAND_QUADRO_RTX, ecc=False)
    nvml = FakeNvml([device])
    gpu = sysinfo.describe_gpu(nvml, 0, 0, ["ecc_corr"])
    assert gpu["brand"] == "Quadro RTX"
    assert gpu["gpu_class"] == "workstation"
    assert gpu["ecc_mode"] == "disabled"
    thresholds = device["nvmlDeviceGetTemperatureThreshold"]
    slowdown = pynvml.NVML_TEMPERATURE_THRESHOLD_SLOWDOWN
    assert gpu["temp_slowdown_c"] == thresholds(slowdown)
    assert gpu["unsupported_fields"] == ["ecc_corr"]


def test_build_sysinfo_has_every_loader_key(fake_system):
    nvml = FakeNvml([make_device(0, pynvml.NVML_BRAND_NVIDIA)], fake_system)
    gpus = [sysinfo.describe_gpu(nvml, 0, 0, [])]
    info = sysinfo.build_sysinfo(
        nvml, gpus, "host", "t", sysinfo.collect_host(host_dir)
    )
    assert set(sysinfo_fields) <= set(info)
    assert info["synthetic"] is False
    code = fake_system["nvmlSystemGetCudaDriverVersion"]
    major, minor = code // 1000, code % 1000 // 10
    assert info["cuda_version"] == f"{major}.{minor}"
