"""Turn a report context into the text and tables of the A4 report.

The content is independent of the output format, so the Word, HTML,
and Markdown reports show the same values (DevSpec 4.5, 4.6).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from gpubench.evaluate import Grade, grade_rank
from gpubench.report.context import (
    ReportContext,
    format_duration,
    mib_per_gb,
    seconds_per_minute,
    strings,
)

percent = 100
# Rules whose failure highlights a cell of the GPU table, keyed by the
# GPU table column.
highlight_rules = {
    "temp_max": "temperature",
    "ratio": "gpu_ratio",
    "sw_thermal": "sw_thermal",
    "hw_slowdown": "hw_slowdown",
    "compute_errors": "compute_errors",
    "vram_errors": "vram_errors",
}
issue_grades = (Grade.WARN, Grade.FAIL)
hw_reasons = ("hw_slowdown", "hw_thermal", "power_brake")


@dataclass
class Cell:
    """One table cell: display text and an optional grade."""

    text: str
    grade: str | None = None
    highlight: bool = False


@dataclass
class RuleRow:
    """One row of the rule table."""

    name: str
    criterion: str
    cells: list[Cell]
    source: str


@dataclass
class Content:
    """Everything the report shows, in reading order."""

    title: str
    sample_mark: str | None
    meta: str
    verdict: str
    summary: str
    system_rows: list[tuple[str, str]]
    condition_rows: list[tuple[str, str]]
    gpu_header: list[str]
    gpu_rows: list[list[Cell]]
    rule_header: list[str]
    rule_rows: list[RuleRow]
    rules_filtered: bool
    footer: str
    notes: dict[str, str] = field(default_factory=dict)


def worst(grades: list[str]) -> str:
    """Return the worst grade; N/A only when nothing else is present."""
    known = [Grade(g) for g in grades if g in grade_rank]
    if not known:
        return Grade.NA.value
    return max(known, key=grade_rank.__getitem__).value


def gpu_verdict(grades: dict[str, str], run_verdict: str | None) -> str:
    """Return the verdict of one GPU.

    In an INCOMPLETE run a GPU without WARN or FAIL is INCOMPLETE, not
    PASS, because some of its tests did not finish.
    """
    verdict = worst(list(grades.values()))
    if run_verdict == Grade.INCOMPLETE and verdict not in issue_grades:
        return Grade.INCOMPLETE.value
    return verdict


def mean_of(values: list[Any]) -> float | None:
    """Return the mean of the non-missing values."""
    present = [v for v in values if v is not None]
    return statistics.fmean(present) if present else None


def fmt_number(value: float | None, digits: int, unknown: str) -> str:
    """Format a number with thousands separators."""
    if value is None:
        return unknown
    return f"{value:,.{digits}f}"


def idle_temperature(ctx: ReportContext, index: int) -> float | None:
    """Return the mean idle temperature of GPU ``index``."""
    for series in ctx.series:
        if series.index == index:
            return mean_of(
                [
                    value
                    for phase, value in zip(
                        series.phases, series.columns["temp_gpu"], strict=True
                    )
                    if phase == "idle"
                ]
            )
    return None


def phase_seconds(ctx: ReportContext) -> dict[str, float]:
    """Return phase durations, configured values first, measured second."""
    measured = {
        phase: (end - start) * seconds_per_minute
        for phase, start, end in ctx.phase_spans
    }
    configured = ctx.sysinfo.get("run", {}).get("phases", {})
    durations = {}
    for phase in ("idle", "burn_warmup", "burn_steady", "cooldown", "vram"):
        value = configured.get(f"{phase}_s")
        if value is None:
            value = round(measured.get(phase, 0.0))
        durations[phase] = value
    return durations


def throttle_seconds(
    m: dict[str, Any], reasons: tuple[str, ...]
) -> float | None:
    """Return the summed throttle time of ``reasons``.

    None means no graded sample exists, as after an early stop.
    """
    values = [m.get("throttle_s", {}).get(r) for r in reasons]
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def measured_text(key: str, grade: str, m: dict[str, Any], best: float | None):
    """Return the localized measured value of rule ``key`` for one GPU."""
    text = strings()["measured"]
    if grade == Grade.NA:
        return text["not_applicable"]
    if key == "compute_errors":
        if m.get("burn_verdict") is None:
            return text["unknown"]
        if m.get("burn_errors"):
            return text["count"].format(count=m["burn_errors"])
        return text["ok"] if m["burn_verdict"] == "OK" else text["faulty"]
    if key == "vram_errors":
        if m.get("vram_tool_error"):
            return text["tool_error"]
        if m.get("vram_errors") is None:
            return text["unknown"]
        return text["count"].format(count=m["vram_errors"])
    if key == "ecc_dbe":
        value = m.get("ecc_uncorr_increase")
        if value is None:
            return text["unknown"]
        return text["count"].format(count=value)
    if key in ("hw_slowdown", "sw_thermal"):
        reasons = hw_reasons if key == "hw_slowdown" else ("sw_thermal",)
        seconds = throttle_seconds(m, reasons)
        if seconds is None:
            return text["unknown"]
        if not seconds:
            return text["none_seen"]
        return text["seconds"].format(seconds=seconds)
    if key == "temperature":
        if m.get("temp_max") is None:
            return text["unknown"]
        return text["celsius"].format(value=m["temp_max"])
    if key == "gpu_ratio":
        if not best or m.get("gflops_mean") is None:
            return text["unknown"]
        return text["percent"].format(value=m["gflops_mean"] / best * percent)
    return text["unknown"]


def best_gflops(ctx: ReportContext) -> float | None:
    """Return the highest mean throughput among the GPUs."""
    values = [
        m["gflops_mean"]
        for m in ctx.metrics.values()
        if m.get("gflops_mean") is not None
    ]
    return max(values, default=None)


def grades_by_gpu(ctx: ReportContext) -> dict[int, dict[str, str]]:
    """Return ``{gpu: {rule: grade}}`` from the evaluation."""
    result: dict[int, dict[str, str]] = {}
    for rule in ctx.evaluation.get("rules", []):
        for gpu in rule["gpus"]:
            result.setdefault(gpu["index"], {})[rule["key"]] = gpu["grade"]
    return result


def lowest_slowdown(ctx: ReportContext) -> float | None:
    """Return the lowest reported GPU slowdown temperature."""
    found = [
        g["temp_slowdown_c"]
        for g in ctx.gpus
        if g.get("temp_slowdown_c") is not None
    ]
    return min(found, default=None)


def gpu_list(indices: list[int]) -> str:
    """Return ``GPU 0, GPU 1`` style text."""
    return ", ".join(f"GPU {i}" for i in indices)


def build_summary(ctx: ReportContext) -> str:
    """Write the one-paragraph conclusion."""
    text = strings()
    evaluation = ctx.evaluation
    sentences = []
    if evaluation.get("verdict") == Grade.INCOMPLETE:
        reasons = ", ".join(evaluation.get("incomplete_reasons", []))
        sentences.append(text["summary_incomplete"].format(reasons=reasons))
    grades = grades_by_gpu(ctx)
    best = best_gflops(ctx)
    compute_bad = [
        i for i, g in grades.items() if g.get("compute_errors") == Grade.FAIL
    ]
    vram_bad = [
        i for i, g in grades.items() if g.get("vram_errors") == Grade.FAIL
    ]
    if compute_bad:
        sentences.append(
            text["summary_compute_fail"].format(gpus=gpu_list(compute_bad))
        )
    if vram_bad:
        count = sum(ctx.metrics[i].get("vram_errors") or 0 for i in vram_bad)
        sentences.append(
            text["summary_vram_fail"].format(
                gpus=gpu_list(vram_bad), count=count
            )
        )
    # "0 errors" is a claim only when both tests actually ran; after an
    # early stop they are N/A and the sentence would be false.
    both_passed = grades and all(
        g.get("compute_errors") == Grade.PASS
        and g.get("vram_errors") == Grade.PASS
        for g in grades.values()
    )
    if both_passed:
        sentences.append(text["summary_clean"])
    for rule in evaluation.get("rules", []):
        if rule["key"] in ("compute_errors", "vram_errors"):
            continue
        for grade in issue_grades:
            hit = [g["index"] for g in rule["gpus"] if g["grade"] == grade]
            if not hit:
                continue
            measured = ", ".join(
                measured_text(rule["key"], grade, ctx.metrics[i], best)
                for i in hit
            )
            sentences.append(
                text["summary_rule_issue"].format(
                    gpus=gpu_list(hit),
                    rule=text["rules"][rule["key"]][0],
                    grade=grade,
                    measured=measured,
                )
            )
    temps = [
        m["temp_max"]
        for m in ctx.metrics.values()
        if m.get("temp_max") is not None
    ]
    limit = lowest_slowdown(ctx)
    if temps and limit is not None:
        hottest = max(temps)
        relation = (
            text["summary_temperature_below"]
            if hottest < limit
            else text["summary_temperature_above"]
        )
        sentences.append(
            text["summary_temperature"].format(
                temp=hottest, limit=limit, relation=relation
            )
        )
    sentences.append(text["summary_basis"])
    return " ".join(sentences)


def build_system_rows(ctx: ReportContext) -> list[tuple[str, str]]:
    """Return the system information rows."""
    text = strings()
    labels = text["system_rows"]
    values = text["values"]
    unknown = values["unknown"]
    info = ctx.sysinfo
    gpus = ctx.gpus
    names: dict[str, list[dict]] = {}
    for gpu in gpus:
        names.setdefault(gpu["name"], []).append(gpu)
    gpu_text = "; ".join(
        values["gpu"].format(
            count=len(group),
            name=name,
            memory_gb=round(group[0]["memory_total_mib"] / mib_per_gb),
            gpu_class=group[0]["gpu_class"],
        )
        for name, group in names.items()
    )
    pcie = ", ".join(
        values["pcie_item"].format(
            index=g["index"], gen=g["pcie_gen_max"], width=g["pcie_width_max"]
        )
        for g in gpus
    )
    ecc = sorted({str(g.get("ecc_mode", unknown)) for g in gpus})
    fan_reported = any(
        value is not None
        for series in ctx.series
        for value in series.columns["fan_speed"]
    )
    cpu = info.get("cpu") or {}
    memory = info.get("memory") or {}
    os_info = info.get("os") or {}
    memory_text = unknown
    if memory.get("total_mib"):
        memory_text = values["memory"].format(
            total_gb=round(memory["total_mib"] / mib_per_gb)
        )
        if memory.get("configuration"):
            memory_text += f", {memory['configuration']}"
    return [
        (labels["gpu"], gpu_text),
        (
            labels["driver"],
            values["driver"].format(
                driver=info.get("driver_version", unknown),
                cuda=info.get("cuda_version", unknown),
            ),
        ),
        (labels["pcie"], pcie),
        (
            labels["ecc"],
            values["ecc"].format(
                ecc=", ".join(e.capitalize() for e in ecc),
                fan=values["fan_reported"]
                if fan_reported
                else values["fan_not_reported"],
            ),
        ),
        (
            labels["cpu"],
            values["cpu"].format(
                model=cpu.get("model", unknown),
                cores=cpu.get("cores", unknown),
                threads=cpu.get("threads", unknown),
            ),
        ),
        (labels["memory"], memory_text),
        (
            labels["os"],
            values["os"].format(
                name=os_info.get("name", unknown),
                kernel=os_info.get("kernel", unknown),
            ),
        ),
    ]


def build_condition_rows(ctx: ReportContext) -> list[tuple[str, str]]:
    """Return the test condition rows."""
    text = strings()
    labels = text["condition_rows"]
    values = text["values"]
    run = ctx.sysinfo.get("run", {})
    seconds = phase_seconds(ctx)
    burn_s = seconds["burn_warmup"] + seconds["burn_steady"]
    samples = max((len(s.minutes) for s in ctx.series), default=0)
    return [
        (labels["idle"], values["idle"].format(seconds=seconds["idle"])),
        (
            labels["burn"],
            values["burn"].format(
                seconds=burn_s,
                memory=run.get("gpu_burn_memory_percent", "?"),
                warmup=seconds["burn_warmup"],
            ),
        ),
        (
            labels["cooldown_vram"],
            values["cooldown_vram"].format(
                cooldown=seconds["cooldown"], vram=seconds["vram"]
            ),
        ),
        (
            labels["sampling"],
            values["sampling"].format(
                interval=run.get("sampling_interval_s", "?"),
                samples=f"{samples:,}",
            ),
        ),
        (labels["execution"], values["execution"]),
        (labels["versions"], values["versions"].format(version=ctx.version)),
        (labels["basis"], values["basis"]),
    ]


def build_gpu_rows(ctx: ReportContext) -> list[list[Cell]]:
    """Return one row per GPU for the GPU result table."""
    unknown = strings()["values"]["unknown"]
    grades = grades_by_gpu(ctx)
    best = best_gflops(ctx)
    rows = []
    for index, m in sorted(ctx.metrics.items()):
        own = grades.get(index, {})
        retention = m.get("clk_sm_retention")
        gflops = m.get("gflops_mean")
        values = {
            "gpu": f"GPU {index}",
            "idle_temp": fmt_number(idle_temperature(ctx, index), 1, unknown),
            "steady_mean": fmt_number(m.get("temp_steady_mean"), 1, unknown),
            "temp_max": fmt_number(m.get("temp_max"), 1, unknown),
            "power_max": fmt_number(m.get("power_max"), 0, unknown),
            "clk_retention": fmt_number(
                retention * percent if retention is not None else None,
                1,
                unknown,
            ),
            "gflops": fmt_number(gflops, 0, unknown),
            "ratio": fmt_number(
                gflops / best * percent if gflops and best else None,
                1,
                unknown,
            ),
            "sw_thermal": fmt_number(
                throttle_seconds(m, ("sw_thermal",)), 0, unknown
            ),
            "hw_slowdown": fmt_number(
                throttle_seconds(m, hw_reasons), 0, unknown
            ),
            "compute_errors": fmt_number(m.get("burn_errors"), 0, unknown),
            "vram_errors": fmt_number(m.get("vram_errors"), 0, unknown),
        }
        row = [
            Cell(
                text,
                highlight=own.get(highlight_rules.get(column, ""))
                in issue_grades,
            )
            for column, text in values.items()
        ]
        verdict = gpu_verdict(own, ctx.evaluation.get("verdict"))
        row.append(Cell(strings()["grades"][verdict], grade=verdict))
        rows.append(row)
    return rows


def build_rule_rows(ctx: ReportContext, only_issues: bool) -> list[RuleRow]:
    """Return the rule table rows, optionally only WARN and FAIL ones."""
    text = strings()
    best = best_gflops(ctx)
    run = ctx.sysinfo.get("run", {})
    ratio_min = run.get("gpu_ratio_min", 0.9)
    limit = lowest_slowdown(ctx)
    rows = []
    for rule in ctx.evaluation.get("rules", []):
        key = rule["key"]
        if only_issues and not any(
            g["grade"] in issue_grades for g in rule["gpus"]
        ):
            continue
        name, criterion, source = text["rules"][key]
        if key == "temperature":
            criterion = (
                criterion.format(limit=limit)
                if limit is not None
                else text["values"]["unknown"]
            )
        elif key == "gpu_ratio":
            criterion = criterion.format(percent=ratio_min * percent)
        cells = [
            Cell(
                measured_text(
                    key, g["grade"], ctx.metrics.get(g["index"], {}), best
                ),
                grade=g["grade"],
            )
            for g in rule["gpus"]
        ]
        rows.append(RuleRow(name, criterion, cells, source))
    return rows


def build(ctx: ReportContext, only_issues: bool = False) -> Content:
    """Assemble the report content of ``ctx``.

    Args:
        ctx: Report context of one result folder.
        only_issues: Keep only rules with a WARN or FAIL grade, used
            when the full report does not fit on one page.
    """
    text = strings()
    started = (
        ctx.started.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        if ctx.started
        else text["values"]["unknown"]
    )
    run = ctx.sysinfo.get("run", {})
    meta = text["header_meta"].format(
        host=ctx.sysinfo.get("hostname", text["values"]["unknown"]),
        started=started,
        profile=run.get("profile", text["values"]["unknown"]),
        duration=format_duration(ctx.duration_s, text),
    )
    verdict = ctx.evaluation.get("verdict", Grade.INCOMPLETE.value)
    footer_parts = [text["footer"].format(version=ctx.version)]
    if ctx.synthetic:
        footer_parts.append(text["footer_sample"])
    gpu_header = list(text["gpu_columns"].values())
    indices = [g["index"] for g in ctx.gpus]
    rule_columns = text["rule_columns"]
    return Content(
        title=text["title"],
        sample_mark=text["sample_mark"] if ctx.synthetic else None,
        meta=meta,
        verdict=verdict,
        summary=build_summary(ctx),
        system_rows=build_system_rows(ctx),
        condition_rows=build_condition_rows(ctx),
        gpu_header=gpu_header,
        gpu_rows=build_gpu_rows(ctx),
        rule_header=[
            rule_columns["rule"],
            rule_columns["criterion"],
            *(f"GPU {i}" for i in indices),
            rule_columns["source"],
        ],
        rule_rows=build_rule_rows(ctx, only_issues),
        rules_filtered=only_issues,
        footer=text["footer_separator"].join(footer_parts),
        notes={
            "charts": text["section_charts_note"],
            "gpus": text["section_gpus_note"],
            "rules": text["section_rules_filtered"]
            if only_issues
            else text["section_rules_note"],
        },
    )
