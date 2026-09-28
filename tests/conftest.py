"""Shared test doubles.

``FakeNvml`` stands in for the ``pynvml`` module. Constants and error
classes come from the real module; device calls answer from a
per-device table, so tests run on machines without a GPU.
"""

from types import SimpleNamespace

import pynvml
import pytest

not_supported = pynvml.NVML_ERROR_NOT_SUPPORTED
bytes_per_mib = 1024 * 1024


def nvml_error(code=not_supported):
    """Return the pynvml exception instance for ``code``."""
    return pynvml.NVMLError(code)


class FakeNvml:
    """Minimal ``pynvml`` replacement driven by dictionaries.

    ``devices`` is a list of dicts keyed by NVML function name. A value
    may be a plain result, a callable that receives the arguments after
    the handle, or an exception instance to raise.
    """

    def __init__(self, devices, system=None):
        self.devices = devices
        self.system = system or {}
        self.initialised = False

    def __getattr__(self, name):
        if name.startswith(("NVML_", "NVMLError")):
            return getattr(pynvml, name)
        if name.startswith("nvmlSystem"):
            value = self.system[name]
            return lambda: self._resolve(value, ())
        if name.startswith("nvmlDevice"):
            return lambda handle, *args: self._resolve(
                self.devices[handle][name], args
            )
        raise AttributeError(name)

    @staticmethod
    def _resolve(value, args):
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(*args)
        return value

    def nvmlInit(self):
        self.initialised = True

    def nvmlShutdown(self):
        self.initialised = False

    def nvmlDeviceGetCount(self):
        return len(self.devices)

    def nvmlDeviceGetHandleByIndex(self, index):
        return index


def field_values(memory_temp):
    """Build a ``nvmlDeviceGetFieldValues`` answer for memory temp."""

    def answer(field_ids):
        if memory_temp is None:
            return [SimpleNamespace(nvmlReturn=not_supported)]
        return [
            SimpleNamespace(
                nvmlReturn=pynvml.NVML_SUCCESS,
                valueType=pynvml.NVML_VALUE_TYPE_UNSIGNED_INT,
                value=SimpleNamespace(uiVal=memory_temp),
            )
        ]

    return answer


def make_device(index, brand, ecc=True, memory_temp=45, fan=40):
    """Return a device table with every call the collectors use."""
    ecc_answer = (lambda kind, counter: 0) if ecc else nvml_error()
    remap_answer = (0, 0, 0, 0) if ecc else nvml_error()
    thresholds = {
        pynvml.NVML_TEMPERATURE_THRESHOLD_SLOWDOWN: 88,
        pynvml.NVML_TEMPERATURE_THRESHOLD_SHUTDOWN: 93,
    }
    clocks = {pynvml.NVML_CLOCK_SM: 1800, pynvml.NVML_CLOCK_MEM: 9500}
    return {
        "nvmlDeviceGetUUID": f"GPU-fake-{index}",
        "nvmlDeviceGetName": "Fake GPU",
        "nvmlDeviceGetBrand": brand,
        "nvmlDeviceGetVbiosVersion": "00.00.00.00.00",
        "nvmlDeviceGetMemoryInfo": SimpleNamespace(
            total=24 * 1024 * bytes_per_mib, used=512 * bytes_per_mib
        ),
        "nvmlDeviceGetEccMode": (1, 1) if ecc else (0, 0),
        "nvmlDeviceGetTemperatureThreshold": thresholds.get,
        "nvmlDeviceGetPowerManagementDefaultLimit": 300_000,
        "nvmlDeviceGetMaxClockInfo": clocks.get,
        "nvmlDeviceGetMaxPcieLinkGeneration": 4,
        "nvmlDeviceGetMaxPcieLinkWidth": 16,
        "nvmlDeviceGetTemperature": lambda sensor: 40 + index,
        "nvmlDeviceGetFieldValues": field_values(memory_temp),
        "nvmlDeviceGetPowerUsage": 25_500,
        "nvmlDeviceGetEnforcedPowerLimit": 300_000,
        "nvmlDeviceGetClockInfo": clocks.get,
        "nvmlDeviceGetUtilizationRates": SimpleNamespace(gpu=0, memory=0),
        "nvmlDeviceGetFanSpeed": nvml_error() if fan is None else fan,
        "nvmlDeviceGetPerformanceState": 8,
        "nvmlDeviceGetCurrentClocksEventReasons": 1,
        "nvmlDeviceGetTotalEccErrors": ecc_answer,
        "nvmlDeviceGetRemappedRows": remap_answer,
        "nvmlDeviceGetCurrPcieLinkGeneration": 3,
        "nvmlDeviceGetCurrPcieLinkWidth": 16,
    }


@pytest.fixture
def fake_system():
    """Driver-level answers shared by the fake devices."""
    return {
        "nvmlSystemGetDriverVersion": "999.99",
        "nvmlSystemGetCudaDriverVersion": 13020,
    }
