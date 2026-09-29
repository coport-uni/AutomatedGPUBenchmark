"""Collect everything the charts and reports show about one run.

The context is built from the result folder alone, so ``gpubench plot``
can re-render a run on a PC without a GPU (DevSpec 4.7).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from gpubench import __version__, evaluate
from gpubench.analysis import loader
from gpubench.analysis import phases as phase_tools

templates_dir = Path(__file__).parent / "templates"
summary_file = "summary.json"
seconds_per_minute = 60
mib_per_gb = 1024
phase_order = ("idle", "burn_warmup", "burn_steady", "cooldown", "vram")


@cache
def strings(language: str = "ko") -> dict[str, Any]:
    """Return the report strings for ``language``."""
    path = templates_dir / f"{language}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def parse_ts(text: str) -> dt.datetime:
    """Parse an ISO 8601 UTC timestamp with a ``Z`` suffix."""
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


@dataclass
class Series:
    """Time series of one GPU, aligned on elapsed minutes."""

    index: int
    minutes: list[float] = field(default_factory=list)
    phases: list[str] = field(default_factory=list)
    columns: dict[str, list[Any]] = field(default_factory=dict)


@dataclass
class ReportContext:
    """Inputs of every chart and report for one result folder."""

    result_dir: Path
    sysinfo: dict[str, Any]
    evaluation: dict[str, Any]
    series: list[Series]
    phase_spans: list[tuple[str, float, float]]
    started: dt.datetime | None
    duration_s: float
    synthetic: bool
    version: str = __version__

    @property
    def gpus(self) -> list[dict[str, Any]]:
        """Return the static GPU descriptions."""
        return self.sysinfo["gpus"]

    @property
    def metrics(self) -> dict[int, dict[str, Any]]:
        """Return the evaluation metrics keyed by GPU index."""
        return {g["index"]: g for g in self.evaluation.get("gpus", [])}


series_columns = (
    "temp_gpu",
    "power_draw",
    "power_limit",
    "clk_sm",
    "util_gpu",
    "mem_used",
    "fan_speed",
    "clk_event_reasons",
)


def build_series(samples: list[dict], start: dt.datetime) -> list[Series]:
    """Split samples into per-GPU series on a shared time axis."""
    grouped = phase_tools.by_gpu_and_phase(samples)
    result = []
    for index in sorted(grouped):
        rows = [
            s
            for phase in grouped[index].values()
            for s in phase
            if s["phase"] != "preflight"
        ]
        rows.sort(key=lambda s: s["ts"])
        series = Series(index)
        for row in rows:
            elapsed = (parse_ts(row["ts"]) - start).total_seconds()
            series.minutes.append(elapsed / seconds_per_minute)
            series.phases.append(row["phase"])
        for column in series_columns:
            series.columns[column] = [row.get(column) for row in rows]
        result.append(series)
    return result


def spans_of(series: Series) -> list[tuple[str, float, float]]:
    """Return ``(phase, start, end)`` in minutes for consecutive phases."""
    spans: list[tuple[str, float, float]] = []
    for phase, minute in zip(series.phases, series.minutes, strict=True):
        if spans and spans[-1][0] == phase:
            spans[-1] = (phase, spans[-1][1], minute)
        else:
            spans.append((phase, minute, minute))
    # Extend each span to the start of the next so the bands touch.
    joined = []
    for number, (phase, start, end) in enumerate(spans):
        if number + 1 < len(spans):
            end = spans[number + 1][1]
        joined.append((phase, start, end))
    return joined


def load_evaluation(result_dir: Path) -> dict[str, Any]:
    """Return the evaluation stored in ``summary.json`` or compute it."""
    path = result_dir / summary_file
    if path.is_file():
        summary = json.loads(path.read_text(encoding="utf-8"))
        if "verdict" in summary and "rules" in summary:
            return summary
    return evaluate.evaluate_result_dir(result_dir)


def build(result_dir: Path) -> ReportContext:
    """Assemble the report context of ``result_dir``."""
    run = loader.load_result_dir(result_dir)
    stamps = sorted(parse_ts(s["ts"]) for s in run.samples)
    start = stamps[0] if stamps else None
    timed = [s for s in run.samples if s["phase"] != "preflight"]
    first = min((parse_ts(s["ts"]) for s in timed), default=start)
    series = build_series(run.samples, first) if first else []
    duration_s = (stamps[-1] - stamps[0]).total_seconds() if stamps else 0.0
    return ReportContext(
        result_dir=result_dir,
        sysinfo=run.sysinfo,
        evaluation=load_evaluation(result_dir),
        series=series,
        phase_spans=spans_of(series[0]) if series else [],
        started=start,
        duration_s=duration_s,
        synthetic=bool(run.sysinfo.get("synthetic")),
    )


def format_duration(seconds: float, text: dict[str, Any]) -> str:
    """Format a duration as minutes and seconds."""
    whole = int(round(seconds))
    return text["duration"].format(
        minutes=whole // seconds_per_minute,
        seconds=whole % seconds_per_minute,
    )
