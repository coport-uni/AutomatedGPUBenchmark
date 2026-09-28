"""Tests for GPU class detection and field probing."""

import pynvml
import pytest

from conftest import FakeNvml, make_device
from gpubench import detect

brand_cases = [
    (pynvml.NVML_BRAND_GEFORCE, "consumer"),
    (pynvml.NVML_BRAND_GEFORCE_RTX, "consumer"),
    (pynvml.NVML_BRAND_TITAN, "consumer"),
    (pynvml.NVML_BRAND_TITAN_RTX, "consumer"),
    (pynvml.NVML_BRAND_QUADRO, "workstation"),
    (pynvml.NVML_BRAND_QUADRO_RTX, "workstation"),
    (pynvml.NVML_BRAND_NVIDIA_RTX, "workstation"),
    (pynvml.NVML_BRAND_TESLA, "datacenter"),
    (pynvml.NVML_BRAND_NVIDIA, "datacenter"),
    (pynvml.NVML_BRAND_GRID, "datacenter"),
]


@pytest.mark.parametrize(("code", "expected"), brand_cases)
def test_brand_code_maps_to_class(code, expected):
    assert detect.classify(detect.brand_name(code)) == expected


def test_unknown_brand_code_is_datacenter():
    assert detect.brand_name(pynvml.NVML_BRAND_COUNT) == "UNKNOWN"
    assert detect.classify("UNKNOWN") == "datacenter"


def test_brand_display_matches_nvidia_smi_spelling():
    assert detect.brand_display("QUADRO_RTX") == "Quadro RTX"
    assert detect.brand_display("NVIDIA_VWS") == "Nvidia Vws"


def test_resolve_class_uses_common_class():
    assert detect.resolve_class(["workstation"] * 2, None) == "workstation"


def test_override_wins_over_mixed_classes():
    mixed = ["consumer", "datacenter"]
    assert detect.resolve_class(mixed, "datacenter") == "datacenter"


def test_mixed_classes_without_override_are_rejected():
    with pytest.raises(ValueError, match="--gpu-class"):
        detect.resolve_class(["consumer", "datacenter"], None)


def test_no_gpu_is_rejected():
    with pytest.raises(ValueError, match="no GPU"):
        detect.resolve_class([], None)


def test_probe_reports_fields_that_raise():
    device = make_device(
        0, pynvml.NVML_BRAND_QUADRO_RTX, ecc=False, memory_temp=None
    )
    nvml = FakeNvml([device])
    unsupported = detect.probe_unsupported(nvml, 0)
    assert unsupported == [
        "temp_mem",
        "ecc_corr",
        "ecc_uncorr",
        "remap_corr",
        "remap_uncorr",
        "remap_pending",
        "remap_failure",
    ]


def test_probe_of_fully_supported_gpu_is_empty():
    nvml = FakeNvml([make_device(0, pynvml.NVML_BRAND_NVIDIA)])
    assert detect.probe_unsupported(nvml, 0) == []
