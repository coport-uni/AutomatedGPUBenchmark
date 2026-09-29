"""Which charts exist and when each one applies (DevSpec 4.7).

The first four are the report charts in the order of the A4 layout.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from gpubench.charts import static_mpl
from gpubench.report.context import ReportContext

charts_dir = "charts"


@dataclass(frozen=True)
class ChartSpec:
    """One static chart."""

    name: str
    draw: Callable
    in_report: bool
    applies: Callable[[ReportContext], bool] = lambda ctx: True


def reports_column(column: str) -> Callable[[ReportContext], bool]:
    """Return a predicate that is true when any GPU reports ``column``."""

    def applies(ctx: ReportContext) -> bool:
        return any(
            value is not None
            for series in ctx.series
            for value in series.columns[column]
        )

    return applies


catalog = (
    ChartSpec("temperature", static_mpl.temperature, True),
    ChartSpec("power", static_mpl.power, True),
    ChartSpec("clk_sm", static_mpl.clk_sm, True),
    ChartSpec("throttle", static_mpl.throttle, True),
    ChartSpec(
        "utilization",
        static_mpl.simple("util_gpu", "utilization", "%"),
        False,
    ),
    ChartSpec(
        "memory_used",
        static_mpl.simple("mem_used", "memory_used", "MiB"),
        False,
    ),
    ChartSpec(
        "fan_speed",
        static_mpl.simple("fan_speed", "fan_speed", "%"),
        False,
        reports_column("fan_speed"),
    ),
)


def render_all(ctx: ReportContext) -> dict[str, dict[str, Path]]:
    """Render every applicable chart into ``<result>/charts``."""
    out_dir = ctx.result_dir / charts_dir
    rendered = {}
    for spec in catalog:
        if spec.applies(ctx):
            rendered[spec.name] = static_mpl.save(
                spec.draw, ctx, spec.name, out_dir
            )
    return rendered


def report_charts(rendered: dict[str, dict[str, Path]]) -> list[Path]:
    """Return the PNG files of the report charts in layout order."""
    return [
        rendered[spec.name]["png"]
        for spec in catalog
        if spec.in_report and spec.name in rendered
    ]
