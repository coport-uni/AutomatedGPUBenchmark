# Capture idle NVML samples from the real GPUs into a fixture directory.
# Read-only: it never loads the GPU. Run inside the runtime image so the
# NVML library comes from the host driver:
#   docker run --rm --gpus all --hostname "$(hostname)" -v "$PWD:/work" -w /work \
#       gpubench:dev python claude_test/capture_idle_fixture.py \
#       --seconds 10 --out tests/fixtures/workstation
# The record layout must match gpubench.analysis.loader.telemetry_fields;
# the M2 collector will replace this script.

import argparse
import datetime as dt
import json
import pathlib
import platform
import socket
import sys
import time

import pynvml as nv

root = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))

from gpubench.analysis.loader import (  # noqa: E402
    sysinfo_fields,
    telemetry_fields,
)

brand_words = {
    "rtx": "RTX",
    "nvidia": "NVIDIA",
    "nvs": "NVS",
    "grid": "GRID",
    "geforce": "GeForce",
    "titan": "TITAN",
}


def brand_name(code):
    names = {
        value: name
        for name, value in vars(nv).items()
        if name.startswith("NVML_BRAND_") and isinstance(value, int)
    }
    raw = names.get(code, "NVML_BRAND_UNKNOWN").removeprefix("NVML_BRAND_")
    return " ".join(
        brand_words.get(word, word.capitalize())
        for word in raw.lower().split("_")
    )


def optional(call, *args):
    try:
        return call(*args)
    except nv.NVMLError:
        return None


def field_value(handle, field_id):
    values = optional(nv.nvmlDeviceGetFieldValues, handle, [field_id])
    if not values or values[0].nvmlReturn != nv.NVML_SUCCESS:
        return None
    return values[0].value.uiVal


def sample(handle, index, phase, ts):
    def ecc(kind):
        return optional(
            nv.nvmlDeviceGetTotalEccErrors, handle, kind, nv.NVML_VOLATILE_ECC
        )

    remap = optional(nv.nvmlDeviceGetRemappedRows, handle)
    power = optional(nv.nvmlDeviceGetPowerUsage, handle)
    limit = optional(nv.nvmlDeviceGetEnforcedPowerLimit, handle)
    util = optional(nv.nvmlDeviceGetUtilizationRates, handle)
    mem = optional(nv.nvmlDeviceGetMemoryInfo, handle)
    pstate = optional(nv.nvmlDeviceGetPerformanceState, handle)
    reasons_call = (
        getattr(nv, "nvmlDeviceGetCurrentClocksEventReasons", None)
        or nv.nvmlDeviceGetCurrentClocksThrottleReasons
    )
    record = {
        "ts": ts,
        "phase": phase,
        "gpu_index": index,
        "gpu_uuid": nv.nvmlDeviceGetUUID(handle),
        "temp_gpu": optional(
            nv.nvmlDeviceGetTemperature, handle, nv.NVML_TEMPERATURE_GPU
        ),
        "temp_mem": field_value(handle, nv.NVML_FI_DEV_MEMORY_TEMP),
        "power_draw": None if power is None else round(power / 1000, 2),
        "power_limit": None if limit is None else round(limit / 1000, 2),
        "clk_sm": optional(nv.nvmlDeviceGetClockInfo, handle, nv.NVML_CLOCK_SM),
        "clk_mem": optional(
            nv.nvmlDeviceGetClockInfo, handle, nv.NVML_CLOCK_MEM
        ),
        "util_gpu": None if util is None else util.gpu,
        "mem_used": None if mem is None else mem.used // (1024 * 1024),
        "fan_speed": optional(nv.nvmlDeviceGetFanSpeed, handle),
        "pstate": None if pstate is None else f"P{pstate}",
        "clk_event_reasons": optional(reasons_call, handle),
        "ecc_corr": ecc(nv.NVML_MEMORY_ERROR_TYPE_CORRECTED),
        "ecc_uncorr": ecc(nv.NVML_MEMORY_ERROR_TYPE_UNCORRECTED),
        "remap_corr": None if remap is None else remap[0],
        "remap_uncorr": None if remap is None else remap[1],
        "remap_pending": None if remap is None else bool(remap[2]),
        "remap_failure": None if remap is None else bool(remap[3]),
        "pcie_gen": optional(nv.nvmlDeviceGetCurrPcieLinkGeneration, handle),
        "pcie_width": optional(nv.nvmlDeviceGetCurrPcieLinkWidth, handle),
    }
    assert tuple(record) == telemetry_fields, "schema drift"
    return record


def gpu_info(handle, index):
    ecc_mode = optional(nv.nvmlDeviceGetEccMode, handle)
    mem = optional(nv.nvmlDeviceGetMemoryInfo, handle)
    return {
        "index": index,
        "uuid": nv.nvmlDeviceGetUUID(handle),
        "name": nv.nvmlDeviceGetName(handle),
        "brand": brand_name(optional(nv.nvmlDeviceGetBrand, handle)),
        "gpu_class": None,
        "vbios": optional(nv.nvmlDeviceGetVbiosVersion, handle),
        "memory_total_mib": None if mem is None else mem.total // (1024 * 1024),
        "ecc_mode": None
        if ecc_mode is None
        else ("enabled" if ecc_mode[0] else "disabled"),
        "temp_slowdown_c": optional(
            nv.nvmlDeviceGetTemperatureThreshold,
            handle,
            nv.NVML_TEMPERATURE_THRESHOLD_SLOWDOWN,
        ),
        "temp_shutdown_c": optional(
            nv.nvmlDeviceGetTemperatureThreshold,
            handle,
            nv.NVML_TEMPERATURE_THRESHOLD_SHUTDOWN,
        ),
        "pcie_gen_max": optional(nv.nvmlDeviceGetMaxPcieLinkGeneration, handle),
        "pcie_width_max": optional(nv.nvmlDeviceGetMaxPcieLinkWidth, handle),
    }


def read_proc_field(path, key, sep=":"):
    for line in (
        pathlib.Path(path)
        .read_text(encoding="utf-8", errors="replace")
        .splitlines()
    ):
        name, _, value = line.partition(sep)
        if name.strip() == key:
            return value.strip()
    return None


def host_info():
    cpuinfo = pathlib.Path("/proc/cpuinfo").read_text(
        encoding="utf-8", errors="replace"
    )
    cores = sum(
        1 for line in cpuinfo.splitlines() if line.startswith("processor")
    )
    os_name = read_proc_field("/etc/os-release", "PRETTY_NAME", "=")
    meminfo_kib = read_proc_field("/proc/meminfo", "MemTotal")
    return {
        "cpu": {
            "model": read_proc_field("/proc/cpuinfo", "model name"),
            "cores": cores,
        },
        "memory": {
            "total_mib": None
            if meminfo_kib is None
            else int(meminfo_kib.split()[0]) // 1024
        },
        "os": {
            "name": None if os_name is None else os_name.strip('"'),
            "kernel": platform.release(),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()

    nv.nvmlInit()
    try:
        count = nv.nvmlDeviceGetCount()
        handles = [nv.nvmlDeviceGetHandleByIndex(i) for i in range(count)]
        cuda = nv.nvmlSystemGetCudaDriverVersion()
        info = {
            "hostname": socket.gethostname(),
            "captured_at": dt.datetime.now(dt.UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "synthetic": False,
            "gpus": [gpu_info(h, i) for i, h in enumerate(handles)],
            "driver_version": nv.nvmlSystemGetDriverVersion(),
            "cuda_version": f"{cuda // 1000}.{cuda % 1000 // 10}",
            **host_info(),
        }
        assert set(sysinfo_fields) <= set(info), "schema drift"
        args.out.mkdir(parents=True, exist_ok=True)
        with (args.out / "sysinfo.json").open(
            "w", encoding="utf-8", newline="\n"
        ) as handle:
            json.dump(info, handle, indent=2)
            handle.write("\n")
        with (args.out / "telemetry.jsonl").open(
            "w", encoding="utf-8", newline="\n"
        ) as handle:
            for _ in range(args.seconds):
                ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                for i, h in enumerate(handles):
                    record = sample(h, i, "idle", ts)
                    handle.write(
                        json.dumps(record, separators=(",", ":")) + "\n"
                    )
                    print(
                        f"{ts} gpu{i} {record['temp_gpu']} C {record['power_draw']} W {record['clk_sm']} MHz"
                    )
                time.sleep(1)
    finally:
        nv.nvmlShutdown()
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
