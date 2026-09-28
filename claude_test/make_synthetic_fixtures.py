# Generate the synthetic consumer and datacenter fixtures under tests/fixtures/.
# Deterministic: rerun it after changing the telemetry schema in
# gpubench.analysis.loader and commit the regenerated files.
# Usage (repository root): python claude_test/make_synthetic_fixtures.py

import json
import pathlib
import sys

root = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))

from gpubench.analysis.loader import (  # noqa: E402
    sysinfo_fields,
    telemetry_fields,
)

fixtures = root / "tests" / "fixtures"
captured_at = "2026-09-28T00:00:00Z"
samples_per_phase = 4
phases = ("idle", "burn_warmup", "burn_steady")
# NVML clocks event reason bit for "GPU idle".
reason_gpu_idle = 0x1

profiles = {
    "consumer": {
        "hostname": "synthetic-consumer",
        "gpus": [
            {
                "index": 0,
                "uuid": "GPU-00000000-0000-4000-8000-00000000c001",
                "name": "NVIDIA GeForce RTX 4090",
                "brand": "GeForce",
                "gpu_class": "consumer",
                "vbios": "95.02.3C.40.7F",
                "memory_total_mib": 24564,
                "ecc_mode": "disabled",
                "temp_slowdown_c": 88,
                "temp_shutdown_c": 93,
                "pcie_gen_max": 4,
                "pcie_width_max": 16,
            }
        ],
        "idle": {
            "temp_gpu": 34,
            "power_draw": 22.0,
            "clk_sm": 210,
            "clk_mem": 405,
            "util_gpu": 0,
            "mem_used": 812,
            "fan_speed": 0,
            "pstate": "P8",
        },
        "load": {
            "temp_gpu": 61,
            "power_draw": 421.0,
            "clk_sm": 2520,
            "clk_mem": 10501,
            "util_gpu": 100,
            "mem_used": 22104,
            "fan_speed": 58,
            "pstate": "P0",
        },
        "power_limit": 450.0,
        "has_ecc": False,
        "has_temp_mem": False,
        "has_fan": True,
        "pcie_gen": 4,
        "pcie_width": 16,
    },
    "datacenter": {
        "hostname": "synthetic-datacenter",
        "gpus": [
            {
                "index": index,
                "uuid": f"GPU-00000000-0000-4000-8000-00000000d00{index}",
                "name": "NVIDIA H100 80GB HBM3",
                "brand": "NVIDIA",
                "gpu_class": "datacenter",
                "vbios": "96.00.74.00.01",
                "memory_total_mib": 81559,
                "ecc_mode": "enabled",
                "temp_slowdown_c": 85,
                "temp_shutdown_c": 90,
                "pcie_gen_max": 5,
                "pcie_width_max": 16,
            }
            for index in range(2)
        ],
        "idle": {
            "temp_gpu": 31,
            "power_draw": 68.0,
            "clk_sm": 345,
            "clk_mem": 2619,
            "util_gpu": 0,
            "mem_used": 1,
            "fan_speed": None,
            "pstate": "P0",
        },
        "load": {
            "temp_gpu": 58,
            "power_draw": 690.0,
            "clk_sm": 1980,
            "clk_mem": 2619,
            "util_gpu": 100,
            "mem_used": 73400,
            "fan_speed": None,
            "pstate": "P0",
        },
        "power_limit": 700.0,
        "has_ecc": True,
        "has_temp_mem": True,
        "has_fan": False,
        "pcie_gen": 5,
        "pcie_width": 16,
    },
}


def interpolate(idle, load, fraction):
    if idle is None or load is None:
        return None
    if isinstance(idle, str):
        return load if fraction > 0 else idle
    value = idle + (load - idle) * fraction
    return round(value, 1) if isinstance(idle, float) else int(round(value))


def make_samples(spec):
    samples = []
    second = 0
    for phase_index, phase in enumerate(phases):
        for step in range(samples_per_phase):
            # Idle stays flat, warm-up ramps, steady holds the load values.
            if phase == "idle":
                fraction = 0.0
            elif phase == "burn_warmup":
                fraction = (step + 1) / samples_per_phase
            else:
                fraction = 1.0
            for gpu in spec["gpus"]:
                ts = f"2026-09-28T00:00:{second:02d}Z"
                metrics = {
                    key: interpolate(
                        spec["idle"][key], spec["load"][key], fraction
                    )
                    for key in spec["idle"]
                }
                ecc = 0 if spec["has_ecc"] else None
                record = {
                    "ts": ts,
                    "phase": phase,
                    "gpu_index": gpu["index"],
                    "gpu_uuid": gpu["uuid"],
                    "temp_gpu": metrics["temp_gpu"] + gpu["index"],
                    "temp_mem": (metrics["temp_gpu"] + 4)
                    if spec["has_temp_mem"]
                    else None,
                    "power_draw": metrics["power_draw"],
                    "power_limit": spec["power_limit"],
                    "clk_sm": metrics["clk_sm"],
                    "clk_mem": metrics["clk_mem"],
                    "util_gpu": metrics["util_gpu"],
                    "mem_used": metrics["mem_used"],
                    "fan_speed": metrics["fan_speed"]
                    if spec["has_fan"]
                    else None,
                    "pstate": metrics["pstate"],
                    "clk_event_reasons": reason_gpu_idle
                    if fraction == 0.0
                    else 0,
                    "ecc_corr": ecc,
                    "ecc_uncorr": ecc,
                    "remap_corr": ecc,
                    "remap_uncorr": ecc,
                    "remap_pending": False if spec["has_ecc"] else None,
                    "remap_failure": False if spec["has_ecc"] else None,
                    "pcie_gen": spec["pcie_gen"],
                    "pcie_width": spec["pcie_width"],
                }
                assert tuple(record) == telemetry_fields, "schema drift"
                samples.append(record)
            second += 1
        del phase_index
    return samples


def make_sysinfo(spec):
    info = {
        "hostname": spec["hostname"],
        "captured_at": captured_at,
        "synthetic": True,
        "gpus": spec["gpus"],
        "driver_version": "580.00",
        "cuda_version": "13.0",
        "cpu": {"model": "Synthetic CPU", "cores": 16, "threads": 32},
        "memory": {"total_mib": 131072, "configuration": "4 x 32 GiB DDR5"},
        "os": {"name": "Ubuntu 24.04.3 LTS", "kernel": "6.8.0-synthetic"},
    }
    assert set(sysinfo_fields) <= set(info), "schema drift"
    return info


def main():
    for name, spec in profiles.items():
        target = fixtures / name
        target.mkdir(parents=True, exist_ok=True)
        with (target / "sysinfo.json").open(
            "w", encoding="utf-8", newline="\n"
        ) as handle:
            json.dump(make_sysinfo(spec), handle, indent=2)
            handle.write("\n")
        with (target / "telemetry.jsonl").open(
            "w", encoding="utf-8", newline="\n"
        ) as handle:
            for record in make_samples(spec):
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        print(f"wrote {target}")


if __name__ == "__main__":
    main()
