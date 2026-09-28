"""Describe the host and its GPUs for ``sysinfo.json``.

CPU and memory come from ``/proc``, the OS from ``/etc/os-release``
and ``uname`` (DevSpec 4.3). The parsers take text so the tests can
feed them captured files on any platform.
"""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

import pynvml

from gpubench import detect

kib_per_mib = 1024
bytes_per_mib = 1024 * 1024
cuda_major_divisor = 1000
cuda_minor_divisor = 10


def parse_cpuinfo(text: str) -> dict[str, Any]:
    """Extract model name, physical core count, and thread count.

    Physical cores are the distinct ``(physical id, core id)`` pairs.
    When the kernel omits those keys, as some virtual machines do,
    ``cores`` is ``None`` rather than a guess.
    """
    model = None
    threads = 0
    cores: set[tuple[str, str]] = set()
    physical_id = core_id = None
    for line in text.splitlines() + [""]:
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key == "processor":
            threads += 1
        elif key == "model name" and model is None:
            model = value
        elif key == "physical id":
            physical_id = value
        elif key == "core id":
            core_id = value
        elif not key:
            if physical_id is not None and core_id is not None:
                cores.add((physical_id, core_id))
            physical_id = core_id = None
    return {
        "model": model,
        "cores": len(cores) or None,
        "threads": threads or None,
    }


def parse_meminfo(text: str) -> dict[str, Any]:
    """Return total memory in MiB from ``/proc/meminfo``."""
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "MemTotal":
            return {"total_mib": int(value.split()[0]) // kib_per_mib}
    return {"total_mib": None}


def parse_os_release(text: str) -> dict[str, Any]:
    """Return the ``PRETTY_NAME`` of ``/etc/os-release``."""
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "PRETTY_NAME":
            return {"name": value.strip().strip("\"'")}
    return {"name": None}


def read_text(path: Path) -> str:
    """Read ``path``, returning an empty string if it does not exist."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def collect_host(root: Path = Path("/")) -> dict[str, Any]:
    """Collect CPU, memory, and OS details of the machine.

    The memory module layout needs ``dmidecode`` and root, which the
    unprivileged runtime container does not have, so ``configuration``
    is ``None``.
    """
    memory = parse_meminfo(read_text(root / "proc" / "meminfo"))
    memory["configuration"] = None
    os_info = parse_os_release(read_text(root / "etc" / "os-release"))
    os_info["kernel"] = platform.release()
    return {
        "cpu": parse_cpuinfo(read_text(root / "proc" / "cpuinfo")),
        "memory": memory,
        "os": os_info,
    }


def optional(call: Any, *args: Any) -> Any:
    """Return ``call(*args)``, or ``None`` if NVML reports an error."""
    try:
        return call(*args)
    except pynvml.NVMLError:
        return None


def describe_gpu(
    nvml: Any, handle: Any, index: int, unsupported: list[str]
) -> dict[str, Any]:
    """Return the static description of one GPU."""
    brand = detect.brand_name(nvml.nvmlDeviceGetBrand(handle))
    memory = optional(nvml.nvmlDeviceGetMemoryInfo, handle)
    ecc_mode = optional(nvml.nvmlDeviceGetEccMode, handle)
    default_limit = optional(
        nvml.nvmlDeviceGetPowerManagementDefaultLimit, handle
    )
    threshold = nvml.nvmlDeviceGetTemperatureThreshold
    return {
        "index": index,
        "uuid": nvml.nvmlDeviceGetUUID(handle),
        "name": nvml.nvmlDeviceGetName(handle),
        "brand": detect.brand_display(brand),
        "gpu_class": detect.classify(brand),
        "vbios": optional(nvml.nvmlDeviceGetVbiosVersion, handle),
        "memory_total_mib": (
            None if memory is None else memory.total // bytes_per_mib
        ),
        "ecc_mode": (
            None
            if ecc_mode is None
            else ("enabled" if ecc_mode[0] else "disabled")
        ),
        "temp_slowdown_c": optional(
            threshold, handle, nvml.NVML_TEMPERATURE_THRESHOLD_SLOWDOWN
        ),
        "temp_shutdown_c": optional(
            threshold, handle, nvml.NVML_TEMPERATURE_THRESHOLD_SHUTDOWN
        ),
        "power_limit_default_w": (
            None if default_limit is None else default_limit / 1000
        ),
        "clk_sm_max": optional(
            nvml.nvmlDeviceGetMaxClockInfo, handle, nvml.NVML_CLOCK_SM
        ),
        "clk_mem_max": optional(
            nvml.nvmlDeviceGetMaxClockInfo, handle, nvml.NVML_CLOCK_MEM
        ),
        "pcie_gen_max": optional(
            nvml.nvmlDeviceGetMaxPcieLinkGeneration, handle
        ),
        "pcie_width_max": optional(nvml.nvmlDeviceGetMaxPcieLinkWidth, handle),
        "unsupported_fields": unsupported,
    }


def cuda_version(nvml: Any) -> str | None:
    """Return the CUDA version the driver supports, e.g. "13.2"."""
    code = optional(nvml.nvmlSystemGetCudaDriverVersion)
    if code is None:
        return None
    major = code // cuda_major_divisor
    minor = code % cuda_major_divisor // cuda_minor_divisor
    return f"{major}.{minor}"


def build_sysinfo(
    nvml: Any,
    gpus: list[dict[str, Any]],
    hostname: str,
    captured_at: str,
    host: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the ``sysinfo.json`` document."""
    return {
        "hostname": hostname,
        "captured_at": captured_at,
        "synthetic": False,
        "gpus": gpus,
        "driver_version": nvml.nvmlSystemGetDriverVersion(),
        "cuda_version": cuda_version(nvml),
        **host,
    }
