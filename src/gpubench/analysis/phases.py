"""Group telemetry samples by GPU and phase.

The phase label is written by the orchestrator into every sample, so
the boundaries come from the data itself rather than from the profile.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

# Phases whose samples count toward the verdict. Warm-up is kept apart
# from the aggregate (DevSpec 4.1); idle and cooldown are context.
judged_phases = ("burn_steady", "vram")
burn_phases = ("burn_warmup", "burn_steady")

Sample = dict[str, Any]


def by_gpu_and_phase(samples: list[Sample]) -> dict[int, dict[str, list]]:
    """Return ``{gpu_index: {phase: [samples in file order]}}``."""
    grouped: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for sample in samples:
        grouped[sample["gpu_index"]][sample["phase"]].append(sample)
    return {gpu: dict(phases) for gpu, phases in grouped.items()}


def select(phases: dict[str, list], names: tuple[str, ...]) -> list[Sample]:
    """Return the samples of the named phases, in phase-name order."""
    selected: list[Sample] = []
    for name in names:
        selected.extend(phases.get(name, []))
    return selected


def phase_seconds(
    phases: dict[str, list], interval_s: float
) -> dict[str, float]:
    """Return the sampled length of every phase in seconds."""
    return {name: len(rows) * interval_s for name, rows in phases.items()}
