"""Produce every report file of a result folder (DevSpec 4.5, 4.6.1).

Order: charts, dashboard, Markdown and HTML reports, ``report.docx``
with a schema check, then ``report.pdf``. When the PDF is longer than
one page the Word file is rebuilt with only the WARN and FAIL rules and
converted again.
"""

from __future__ import annotations

import base64
import html
from dataclasses import dataclass, field
from pathlib import Path

from gpubench.charts import catalog, interactive_plotly
from gpubench.charts.theme import grade_colours
from gpubench.report import content as content_tools
from gpubench.report import docx2pdf, docx_builder, ooxml
from gpubench.report.content import Cell, Content
from gpubench.report.context import ReportContext, build, strings

docx_file = "report.docx"
pdf_file = "report.pdf"
html_file = "report.html"
markdown_file = "report.md"
max_pages = 1
max_problems_shown = 5


class ReportError(RuntimeError):
    """The report could not be produced as DevSpec 4.6.1 requires."""


@dataclass
class ReportFiles:
    """Paths written by ``render`` and what had to be skipped."""

    docx: Path
    html: Path
    markdown: Path
    dashboard: Path
    charts: dict[str, dict[str, Path]]
    pdf: Path | None = None
    pdf_pages: int | None = None
    rules_filtered: bool = False
    notes: list[str] = field(default_factory=list)


def cell_label(cell: Cell) -> str:
    """Return the display text of a cell, with the grade label."""
    if cell.grade and cell.text != strings()["grades"][cell.grade]:
        return f"{cell.text} {strings()['grades'][cell.grade]}"
    return cell.text


def markdown_row(values: list[str]) -> str:
    """Return one Markdown table row."""
    escaped = [v.replace("|", "&#124;") for v in values]
    return "| " + " | ".join(escaped) + " |"


def markdown_table(header: list[str], rows: list[list[str]]) -> list[str]:
    """Return the lines of a Markdown table."""
    lines = [markdown_row(header), markdown_row(["---"] * len(header))]
    lines.extend(markdown_row(row) for row in rows)
    return lines


def pair_rows(report: Content) -> list[list[str]]:
    """Return system and condition rows side by side."""
    count = max(len(report.system_rows), len(report.condition_rows))
    rows = []
    for number in range(count):
        row: list[str] = []
        for source in (report.system_rows, report.condition_rows):
            label, value = source[number] if number < len(source) else ("", "")
            row.extend([label, value])
        rows.append(row)
    return rows


def rule_table_rows(report: Content) -> list[list[str]]:
    """Return the rule rows as plain strings."""
    return [
        [row.name, row.criterion, *map(cell_label, row.cells), row.source]
        for row in report.rule_rows
    ]


def chart_title(name: str) -> str:
    """Return the localized title of chart ``name``."""
    return strings()["charts"].get(name, name)


def write_markdown(
    report: Content, charts: dict[str, dict[str, Path]], path: Path
) -> Path:
    """Write ``report.md`` with relative links to the chart PNGs."""
    text = strings()
    lines = [
        f"# {report.title}",
        "",
    ]
    if report.sample_mark:
        lines += [f"**{report.sample_mark}**", ""]
    lines += [
        report.meta,
        "",
        f"**{text['final_verdict']}: {text['grades'][report.verdict]}**",
        "",
        f"> **{text['summary_label']}** {report.summary}",
        "",
        f"## {text['section_system']}",
        "",
        *markdown_table(["", "", "", ""], pair_rows(report)),
        "",
        f"## {text['section_charts']}",
        "",
        report.notes["charts"],
        "",
    ]
    for name, files in charts.items():
        relative = files["png"].relative_to(path.parent).as_posix()
        lines += [f"![{chart_title(name)}]({relative})", ""]
    lines += [
        f"## {text['section_gpus']}",
        "",
        report.notes["gpus"],
        "",
        *markdown_table(
            report.gpu_header,
            [[cell_label(c) for c in row] for row in report.gpu_rows],
        ),
        "",
        f"## {text['section_rules']}",
        "",
        report.notes["rules"],
        "",
        *markdown_table(report.rule_header, rule_table_rows(report)),
        "",
        "---",
        "",
        report.footer,
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


html_style = """
body { font-family: 'Noto Sans CJK KR', 'Noto Sans KR', sans-serif;
  color: #0b0b0b; max-width: 1040px; margin: 24px auto; padding: 0 16px;
  font-size: 14px; }
h1 { margin-bottom: 4px; } h2 { font-size: 16px; margin-top: 24px; }
.meta, .note, footer { color: #52514e; font-size: 12px; }
.sample { color: #d03b3b; font-size: 13px; margin-left: 8px; }
.verdict { font-size: 28px; font-weight: bold; }
.summary { background: #f7f6f2; border-left: 4px solid #fab219;
  padding: 8px 12px; }
table { border-collapse: collapse; width: 100%; font-size: 12px; }
th, td { border-bottom: 1px solid #e2e1dc; padding: 3px 6px;
  text-align: left; }
th { border-top: 1px solid #0b0b0b; }
td.num { text-align: right; } td.hi { background: #fff4dc;
  font-weight: bold; }
.charts { display: grid; grid-template-columns: repeat(auto-fit,
  minmax(320px, 1fr)); gap: 8px; }
.charts img { width: 100%; }
"""


def html_cells(cells: list[str], tag: str = "td") -> str:
    """Return escaped table cells."""
    return "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in cells)


def graded_span(cell: Cell) -> str:
    """Return a cell's text with its coloured grade label."""
    text = strings()["grades"]
    if not cell.grade:
        return html.escape(cell.text)
    label = (
        f'<b style="color:{grade_colours[cell.grade]}">'
        f"{html.escape(text[cell.grade])}</b>"
    )
    if cell.text == text[cell.grade]:
        return label
    return f"{html.escape(cell.text)} {label}"


def write_html(report: Content, charts: list[Path], path: Path) -> Path:
    """Write ``report.html`` with the chart PNGs embedded."""
    text = strings()
    parts = [
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{html.escape(report.title)}</title>",
        f"<style>{html_style}</style></head><body>",
        f"<h1>{html.escape(report.title)}",
    ]
    if report.sample_mark:
        parts.append(
            f"<span class='sample'>{html.escape(report.sample_mark)}</span>"
        )
    parts += [
        "</h1>",
        f"<div class='meta'>{html.escape(report.meta)}</div>",
        f"<div class='verdict' style='color:{grade_colours[report.verdict]}'>",
        f"{html.escape(text['grades'][report.verdict])}</div>",
        f"<p class='summary'><b>{html.escape(text['summary_label'])}</b> ",
        f"{html.escape(report.summary)}</p>",
        f"<h2>{html.escape(text['section_system'])}</h2><table>",
    ]
    parts += [f"<tr>{html_cells(row)}</tr>" for row in pair_rows(report)]
    parts += [
        "</table>",
        f"<h2>{html.escape(text['section_charts'])} <span class='note'>",
        f"{html.escape(report.notes['charts'])}</span></h2>",
        "<div class='charts'>",
    ]
    for png in charts:
        encoded = base64.b64encode(png.read_bytes()).decode("ascii")
        parts.append(
            f"<img alt='{html.escape(chart_title(png.stem))}' "
            f"src='data:image/png;base64,{encoded}'>"
        )
    parts += [
        "</div>",
        f"<h2>{html.escape(text['section_gpus'])} <span class='note'>",
        f"{html.escape(report.notes['gpus'])}</span></h2><table>",
        f"<tr>{html_cells(report.gpu_header, 'th')}</tr>",
    ]
    for row in report.gpu_rows:
        cells = "".join(
            f"<td class='{'num hi' if c.highlight else 'num'}'>"
            f"{graded_span(c)}</td>"
            for c in row
        )
        parts.append(f"<tr>{cells}</tr>")
    parts += [
        "</table>",
        f"<h2>{html.escape(text['section_rules'])} <span class='note'>",
        f"{html.escape(report.notes['rules'])}</span></h2><table>",
        f"<tr>{html_cells(report.rule_header, 'th')}</tr>",
    ]
    for row in report.rule_rows:
        graded = "".join(f"<td>{graded_span(c)}</td>" for c in row.cells)
        parts.append(
            f"<tr>{html_cells([row.name, row.criterion])}{graded}"
            f"{html_cells([row.source])}</tr>"
        )
    parts += [
        "</table>",
        f"<footer><hr>{html.escape(report.footer)}</footer>",
        "</body></html>",
    ]
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def write_docx(report: Content, charts: list[Path], path: Path) -> list[str]:
    """Build ``report.docx`` and check it against the OOXML schemas.

    Returns:
        Notes about skipped checks.

    Raises:
        ReportError: If the package violates the schemas.
    """
    docx_builder.build_docx(report, strings(), charts, path)
    if not ooxml.schemas_available():
        return [f"schema check skipped: no schemas in {ooxml.schema_dir()}"]
    problems = ooxml.validate_docx(path)
    if problems:
        shown = "; ".join(map(str, problems[:max_problems_shown]))
        raise ReportError(
            f"{path.name} violates the OOXML schema "
            f"({len(problems)} problems): {shown}"
        )
    return []


def convert_pdf(result_dir: Path) -> tuple[Path, int]:
    """Convert ``report.docx`` to ``report.pdf`` (``gpubench pdf``).

    Raises:
        ReportError: If LibreOffice is missing or the export fails.
    """
    docx = result_dir / docx_file
    if not docx.is_file():
        raise ReportError(f"{docx} does not exist")
    if not docx2pdf.available():
        raise ReportError("LibreOffice with python3-uno is not installed")
    try:
        pdf = docx2pdf.convert(docx, result_dir / pdf_file)
    except docx2pdf.ConversionError as exc:
        raise ReportError(str(exc)) from exc
    return pdf, docx2pdf.page_count(pdf)


def render_context(ctx: ReportContext, pdf: bool = True) -> ReportFiles:
    """Write every report file for ``ctx``; see the module docstring."""
    result_dir = ctx.result_dir
    rendered = catalog.render_all(ctx)
    report_charts = catalog.report_charts(rendered)
    report = content_tools.build(ctx)
    files = ReportFiles(
        docx=result_dir / docx_file,
        html=write_html(
            report,
            [files["png"] for files in rendered.values()],
            result_dir / html_file,
        ),
        markdown=write_markdown(report, rendered, result_dir / markdown_file),
        dashboard=interactive_plotly.write_dashboard(ctx),
        charts=rendered,
    )
    files.notes += write_docx(report, report_charts, files.docx)
    if not pdf:
        return files
    if not docx2pdf.available():
        files.notes.append("pdf skipped: LibreOffice is not installed")
        return files
    files.pdf, files.pdf_pages = convert_pdf(result_dir)
    if files.pdf_pages > max_pages:
        files.rules_filtered = True
        filtered = content_tools.build(ctx, only_issues=True)
        write_docx(filtered, report_charts, files.docx)
        files.pdf, files.pdf_pages = convert_pdf(result_dir)
        if files.pdf_pages > max_pages:
            files.notes.append(
                f"{pdf_file} has {files.pdf_pages} pages even with only "
                "WARN and FAIL rules"
            )
    return files


def render(result_dir: Path, pdf: bool = True) -> ReportFiles:
    """Build the context of ``result_dir`` and write every report file."""
    return render_context(build(result_dir), pdf=pdf)
