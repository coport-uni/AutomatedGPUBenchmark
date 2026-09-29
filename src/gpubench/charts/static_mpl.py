"""Static matplotlib charts for the reports (PNG at 300 dpi and SVG).

python-docx cannot embed SVG, so Word and PDF use the PNG files; the
SVG files are for editing (DevSpec 4.6.1, step 1).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from gpubench.analysis import metrics
from gpubench.charts import theme
from gpubench.report.context import ReportContext, Series, strings

figure_size_in = (3.6, 2.2)
line_width = 0.9
limit_headroom = 0.2
throttle_bar_height = 0.6
burn_phase_names = ("burn_warmup", "burn_steady")
throttle_row_bits = {
    "sw_thermal": metrics.reason_sw_thermal,
    "hw": metrics.reason_hw_slowdown
    | metrics.reason_hw_thermal
    | metrics.reason_power_brake,
    "sw_power_cap": metrics.reason_sw_power_cap,
}


def draw_phase_bands(ax: Axes, ctx: ReportContext, label: bool) -> None:
    """Shade each phase and optionally name it above the plot."""
    text = strings()["phases"]
    for phase, start, end in ctx.phase_spans:
        colour = theme.phase_colours.get(phase)
        if colour is None:
            continue
        ax.axvspan(start, end, color=colour, zorder=0, linewidth=0)
        if label:
            ax.text(
                (start + end) / 2,
                1.01,
                text.get(phase, phase),
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="bottom",
                fontsize=theme.base_font_pt - 1,
                color=theme.muted_colour,
            )


def plot_series(
    ax: Axes, ctx: ReportContext, column: str, only: tuple[str, ...] = ()
) -> None:
    """Draw one line per GPU for ``column``."""
    for series in ctx.series:
        points = [
            (minute, value)
            for minute, phase, value in zip(
                series.minutes,
                series.phases,
                series.columns[column],
                strict=True,
            )
            if value is not None and (not only or phase in only)
        ]
        if not points:
            continue
        xs, ys = zip(*points, strict=True)
        ax.plot(
            xs,
            ys,
            color=theme.gpu_colour(series.index),
            linewidth=line_width,
            label=f"GPU {series.index}",
        )


def finish(ax: Axes, title: str, unit: str) -> None:
    """Apply the shared title, axis labels, and legend."""
    ax.set_title(title, pad=10)
    ax.set_xlabel(strings()["charts"]["x_minutes"])
    ax.set_ylabel(unit)
    if ax.get_legend_handles_labels()[0]:
        # Outside the axes so it never covers data or the limit label;
        # constrained layout reserves the space.
        ax.figure.legend(
            loc="outside lower right",
            ncols=len(ax.get_legend_handles_labels()[0]),
            fontsize=theme.base_font_pt - 1,
        )


def limit_line(ax: Axes, value: float | None, label: str) -> None:
    """Draw a dashed horizontal limit with its label."""
    if value is None:
        return
    # Leave room above the line so its label stays inside the axes and
    # clear of the phase names above them.
    bottom, top = ax.get_ylim()
    ax.set_ylim(bottom, max(top, value + (value - bottom) * limit_headroom))
    ax.axhline(value, color=theme.limit_colour, linestyle="--", linewidth=0.8)
    ax.text(
        1.0,
        value,
        label,
        transform=ax.get_yaxis_transform(),
        ha="right",
        va="bottom",
        fontsize=theme.base_font_pt - 1,
        color=theme.limit_colour,
    )


def lowest(ctx: ReportContext, key: str) -> float | None:
    """Return the lowest value of ``key`` across the GPU descriptions."""
    found = [g[key] for g in ctx.gpus if g.get(key) is not None]
    return min(found, default=None)


def temperature(fig: Figure, ctx: ReportContext) -> None:
    """GPU core temperature over the whole run."""
    ax = fig.subplots()
    draw_phase_bands(ax, ctx, label=True)
    plot_series(ax, ctx, "temp_gpu")
    text = strings()["charts"]
    limit = lowest(ctx, "temp_slowdown_c")
    if limit is not None:
        limit_line(ax, limit, text["slowdown_line"].format(limit=limit))
    finish(ax, text["temperature"], "°C")


def power(fig: Figure, ctx: ReportContext) -> None:
    """Power draw over the whole run with the enforced limit."""
    ax = fig.subplots()
    draw_phase_bands(ax, ctx, label=False)
    plot_series(ax, ctx, "power_draw")
    text = strings()["charts"]
    limits = [
        value
        for series in ctx.series
        for value in series.columns["power_limit"]
        if value is not None
    ]
    ax.set_ylim(bottom=0)
    if limits:
        limit = min(limits)
        limit_line(ax, limit, text["power_limit_line"].format(limit=limit))
    finish(ax, text["power"], "W")


def clk_sm(fig: Figure, ctx: ReportContext) -> None:
    """SM clock during the burn phases."""
    ax = fig.subplots()
    draw_phase_bands(ax, ctx, label=False)
    plot_series(ax, ctx, "clk_sm", burn_phase_names)
    burn = [s for s in ctx.phase_spans if s[0] in burn_phase_names]
    if burn:
        ax.set_xlim(burn[0][1], burn[-1][2])
    finish(ax, strings()["charts"]["clk_sm"], "MHz")


def throttle_intervals(
    series: Series, bits: int, interval_min: float
) -> list[tuple[float, float]]:
    """Return ``(start, width)`` bars where any of ``bits`` was set."""
    bars = []
    for minute, mask in zip(
        series.minutes, series.columns["clk_event_reasons"], strict=True
    ):
        if mask is not None and mask & bits:
            bars.append((minute, interval_min))
    return bars


def throttle(fig: Figure, ctx: ReportContext) -> None:
    """Timeline of throttling reasons per GPU."""
    ax = fig.subplots()
    draw_phase_bands(ax, ctx, label=False)
    text = strings()
    interval_min = ctx.sysinfo.get("run", {}).get("sampling_interval_s", 1)
    interval_min /= 60
    labels = []
    row = 0
    for series in ctx.series:
        for key, bits in throttle_row_bits.items():
            bars = throttle_intervals(series, bits, interval_min)
            y = row
            labels.append(f"GPU {series.index}  {text['throttle_rows'][key]}")
            if bars:
                ax.broken_barh(
                    bars,
                    (y - throttle_bar_height / 2, throttle_bar_height),
                    color=theme.gpu_colour(series.index),
                    alpha=0.35 if key == "sw_power_cap" else 0.9,
                )
            else:
                ax.text(
                    1.0,
                    y,
                    text["charts"]["none"],
                    transform=ax.get_yaxis_transform(),
                    ha="right",
                    va="center",
                    color=theme.muted_colour,
                    fontsize=theme.base_font_pt - 1,
                )
            row += 1
    ax.set_yticks(range(len(labels)), labels)
    ax.set_ylim(len(labels) - 0.5, -0.5)
    ax.tick_params(axis="y", length=0)
    ax.set_title(text["charts"]["throttle"], pad=10)
    ax.set_xlabel(text["charts"]["x_minutes"])


def simple(column: str, title_key: str, unit: str):
    """Build a chart function for a plain time series."""

    def draw(fig: Figure, ctx: ReportContext) -> None:
        ax = fig.subplots()
        draw_phase_bands(ax, ctx, label=False)
        plot_series(ax, ctx, column)
        finish(ax, strings()["charts"][title_key], unit)

    return draw


def save(
    draw: Any, ctx: ReportContext, name: str, out_dir: Path
) -> dict[str, Path]:
    """Render ``draw`` to ``png/<name>.png`` and ``svg/<name>.svg``."""
    theme.apply()
    fig = plt.figure(figsize=figure_size_in, layout="constrained")
    try:
        draw(fig, ctx)
        paths = {}
        for fmt in ("png", "svg"):
            target = out_dir / fmt / f"{name}.{fmt}"
            target.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(target, dpi=theme.png_dpi if fmt == "png" else None)
            paths[fmt] = target
        return paths
    finally:
        plt.close(fig)
