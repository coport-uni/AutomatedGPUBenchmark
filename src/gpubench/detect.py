"""Classify GPUs by product brand and probe their telemetry support.

The class selects the profile and the optional runner (DevSpec 4.2).
It is derived from the NVML brand rather than the product name, which
is what ``nvidia-smi -q`` reports as "Product Brand".
"""

from __future__ import annotations

from collections.abc import Iterable
from types import ModuleType
from typing import Any

import pynvml

from gpubench.collectors import telemetry

gpu_classes = ("consumer", "workstation", "datacenter")

# Keys are NVML brand constant names without the ``NVML_BRAND_``
# prefix. Anything not listed is datacenter, as agreed in ToDo.md
# section 1 and extended for Titan and plain Quadro in section 4.
consumer_brands = frozenset({"GEFORCE", "GEFORCE_RTX", "TITAN", "TITAN_RTX"})
workstation_brands = frozenset({"QUADRO", "QUADRO_RTX", "NVIDIA_RTX"})

brand_display_names = {
    "GEFORCE": "GeForce",
    "GEFORCE_RTX": "GeForce RTX",
    "TITAN": "Titan",
    "TITAN_RTX": "Titan RTX",
    "QUADRO": "Quadro",
    "QUADRO_RTX": "Quadro RTX",
    "NVIDIA_RTX": "NVIDIA RTX",
    "NVIDIA": "NVIDIA",
    "TESLA": "Tesla",
}

brand_prefix = "NVML_BRAND_"
brand_count_name = "COUNT"


def brand_name(code: int) -> str:
    """Return the NVML brand constant name for ``code``.

    Args:
        code: Value returned by ``nvmlDeviceGetBrand``.

    Returns:
        The constant name without its prefix, for example
        ``"QUADRO_RTX"``, or ``"UNKNOWN"`` for an unlisted value.
    """
    for name, value in vars(pynvml).items():
        if not name.startswith(brand_prefix):
            continue
        short = name.removeprefix(brand_prefix)
        if short != brand_count_name and value == code:
            return short
    return "UNKNOWN"


def brand_display(brand: str) -> str:
    """Return the brand as ``nvidia-smi`` spells it, e.g. "Quadro RTX"."""
    if brand in brand_display_names:
        return brand_display_names[brand]
    return " ".join(word.capitalize() for word in brand.split("_"))


def classify(brand: str) -> str:
    """Map an NVML brand constant name to a GPU class."""
    if brand in consumer_brands:
        return "consumer"
    if brand in workstation_brands:
        return "workstation"
    return "datacenter"


def resolve_class(detected: Iterable[str], override: str | None) -> str:
    """Pick the single class that governs the run.

    Args:
        detected: The class of every GPU in the run.
        override: Value of ``--gpu-class``, or ``None``.

    Returns:
        ``override`` when given, otherwise the common detected class.

    Raises:
        ValueError: If the GPUs belong to different classes and no
            override was given, or no GPU was detected.
    """
    if override is not None:
        if override not in gpu_classes:
            raise ValueError(f"unknown GPU class {override!r}")
        return override
    classes = sorted(set(detected))
    if not classes:
        raise ValueError("no GPU detected")
    if len(classes) > 1:
        raise ValueError(
            f"GPUs of different classes {classes}; choose one with --gpu-class"
        )
    return classes[0]


def probe_unsupported(nvml: ModuleType | Any, handle: Any) -> list[str]:
    """Return the telemetry fields this GPU cannot report.

    Every reader is called once. A reader that raises an NVML error is
    marked unsupported for the whole run, so the sampler stores
    ``null`` without calling it again (LearnedPatterns E3).
    """
    unsupported: list[str] = []
    for group in telemetry.metric_groups:
        try:
            group.read(nvml, handle)
        except pynvml.NVMLError:
            unsupported.extend(group.fields)
    return unsupported
