"""Interactive ``dashboard.html`` with Plotly (DevSpec 4.5, 4.7).

The Plotly library is embedded in the file so the dashboard opens
offline; this adds about 3 MB. The panels share the X axis so zooming
one zooms all of them.
"""

from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from gpubench.charts import theme
from gpubench.report.context import ReportContext, strings

dashboard_file = "dashboard.html"
panel_height_px = 230
vertical_spacing = 0.04
# (column, chart title key, unit); fan speed only when reported.
panels = (
    ("temp_gpu", "temperature", "°C"),
    ("power_draw", "power", "W"),
    ("clk_sm", "clk_sm", "MHz"),
    ("util_gpu", "utilization", "%"),
    ("mem_used", "memory_used", "MiB"),
    ("fan_speed", "fan_speed", "%"),
)


def reported(ctx: ReportContext, column: str) -> bool:
    """Return whether any GPU has a value in ``column``."""
    return any(
        value is not None
        for series in ctx.series
        for value in series.columns[column]
    )


def build_figure(ctx: ReportContext) -> go.Figure:
    """Build the dashboard figure of ``ctx``."""
    text = strings()
    shown = [p for p in panels if reported(ctx, p[0])]
    figure = make_subplots(
        rows=len(shown),
        cols=1,
        shared_xaxes=True,
        vertical_spacing=vertical_spacing,
        subplot_titles=[text["charts"][key] for _, key, _ in shown],
    )
    for row, (column, _, unit) in enumerate(shown, start=1):
        for phase, start, end in ctx.phase_spans:
            colour = theme.phase_colours.get(phase)
            if colour is None:
                continue
            figure.add_vrect(
                x0=start,
                x1=end,
                fillcolor=colour,
                opacity=1.0,
                layer="below",
                line_width=0,
                row=row,
                col=1,
            )
        for series in ctx.series:
            figure.add_trace(
                go.Scatter(
                    x=series.minutes,
                    y=series.columns[column],
                    mode="lines",
                    name=f"GPU {series.index}",
                    legendgroup=f"gpu{series.index}",
                    showlegend=row == 1,
                    line={"color": theme.gpu_colour(series.index)},
                    customdata=[
                        text["phases"].get(p, p) for p in series.phases
                    ],
                    hovertemplate=(
                        f"GPU {series.index}: %{{y}} {unit}"
                        "<br>%{x:.2f} min, %{customdata}<extra></extra>"
                    ),
                ),
                row=row,
                col=1,
            )
        figure.update_yaxes(title_text=unit, row=row, col=1)
    figure.update_xaxes(title_text=text["charts"]["x_minutes"], row=len(shown))
    figure.update_layout(
        title=text["dashboard_title"].format(
            host=ctx.sysinfo.get("hostname", "")
        ),
        height=panel_height_px * len(shown),
        hovermode="x unified",
        template="plotly_white",
        font={"family": ", ".join(theme.font_families)},
    )
    return figure


def write_dashboard(ctx: ReportContext) -> Path:
    """Write ``dashboard.html`` into the result folder of ``ctx``."""
    path = ctx.result_dir / dashboard_file
    build_figure(ctx).write_html(
        str(path), include_plotlyjs=True, full_html=True
    )
    return path
