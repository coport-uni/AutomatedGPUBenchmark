"""Colours and fonts shared by the static charts and the dashboard.

Phases are drawn as background bands so every chart keeps a single Y
axis (DevSpec 4.6). Colours are distinguishable for the common forms of
colour blindness and the grades also carry an icon and text.
"""

from __future__ import annotations

import matplotlib

phase_colours = {
    "idle": "#eeeeee",
    "burn_warmup": "#fdf0dc",
    "burn_steady": "#fbe3d3",
    # gpu_burn finishing after its window: load ends inside this band.
    "burn_finish": "#f5ece6",
    "cooldown": "#e3eefa",
    "vram": "#e6f3e6",
}
gpu_colours = (
    "#1f6fd1",
    "#e8672a",
    "#2a9d4b",
    "#8a5cc4",
    "#c43d6b",
    "#6b7b8c",
    "#b8860b",
    "#17a2b8",
)
grade_colours = {
    "PASS": "#0c830c",
    "WARN": "#b07800",
    "FAIL": "#d03b3b",
    "N/A": "#7a7974",
    "INCOMPLETE": "#7a7974",
}
limit_colour = "#c62828"
text_colour = "#222222"
muted_colour = "#777777"

# Noto Sans CJK KR renders Korean; DejaVu Sans is the fallback that
# matplotlib always ships.
font_families = ["Noto Sans CJK KR", "Noto Sans CJK JP", "DejaVu Sans"]
base_font_pt = 8
png_dpi = 300


def gpu_colour(index: int) -> str:
    """Return the line colour of GPU ``index``."""
    return gpu_colours[index % len(gpu_colours)]


def apply() -> None:
    """Configure matplotlib for headless, consistent output."""
    matplotlib.use("Agg")
    matplotlib.rcParams.update(
        {
            "font.family": font_families,
            "font.size": base_font_pt,
            "axes.titlesize": base_font_pt + 1,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.edgecolor": muted_colour,
            "axes.linewidth": 0.6,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "legend.frameon": False,
            "svg.fonttype": "none",
        }
    )
