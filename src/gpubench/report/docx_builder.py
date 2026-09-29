"""Build the one-page A4 ``report.docx`` (DevSpec 4.6.1, step 2).

The layout follows ``example/GPU_Burn-in_Report_Sample.docx``. Every
property element is created here in the order the ECMA-376 schema
requires, because LibreOffice and the schema check reject other orders
(LearnedPatterns L3). Tables carry ``tblGrid``, ``tblW``, and a fixed
layout so their widths survive the PDF conversion (L2).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from gpubench.charts import theme
from gpubench.report.content import Cell, Content

font_name = "Noto Sans CJK KR"
# Sizes are in half points, as w:sz stores them.
size_title = 30
size_verdict = 34
size_meta = 14
size_heading = 16
size_body = 14
size_table = 13
size_note = 12
size_footer = 11

colour_text = "0B0B0B"
colour_muted = "52514E"
colour_faint = "7A7974"
colour_sample = "D03B3B"
colour_rule = "E2E1DC"
colour_summary_bar = "FAB219"
fill_summary = "F7F6F2"
fill_highlight = "FFF4DC"
# Word stores colours as hex without the leading "#".
grade_colours = {
    grade: colour.lstrip("#").upper()
    for grade, colour in theme.grade_colours.items()
}

# Page geometry in twentieths of a point (dxa): A4 with 10 mm side
# margins leaves 10773 dxa of text width.
page_width_mm = 210
page_height_mm = 297
margin_side_mm = 10
margin_top_mm = 9
margin_bottom_mm = 8
footer_distance_mm = 5
text_width = 10773
chart_width_mm = 86
cell_margin_vertical = 25
cell_margin_side = 55

header_widths = (7938, 2835)
system_widths = (1247, 4025, 1360, 4139)
chart_widths = (5386, 5387)
gpu_widths = (680, 737, 850, 737, 737, 850, 850, 737, 907, 1063, 737, 793, 1095)
rule_fixed_widths = (2778, 1587, 3005)

# Child order of the property elements this module writes (ECMA-376
# Part 1, 17.3.1.26 pPr, 17.3.2.28 rPr, 17.4.60 tblPr, 17.4.70 tcPr).
ppr_order = (
    "w:pStyle",
    "w:keepNext",
    "w:autoSpaceDE",
    "w:autoSpaceDN",
    "w:spacing",
    "w:jc",
)
rpr_order = ("w:rFonts", "w:b", "w:color", "w:sz", "w:szCs")
tblpr_order = (
    "w:tblStyle",
    "w:tblW",
    "w:jc",
    "w:tblBorders",
    "w:tblLayout",
    "w:tblCellMar",
    "w:tblLook",
)
tcpr_order = ("w:tcW", "w:gridSpan", "w:shd", "w:vAlign")
border_order = ("w:top", "w:left", "w:bottom", "w:right", "w:insideH")


def insert_ordered(parent, child, order: Sequence[str]) -> None:
    """Insert ``child`` into ``parent`` at its schema position.

    An existing element with the same tag is replaced.
    """
    tag = child.tag
    for existing in parent.findall(tag):
        parent.remove(existing)
    rank = {qn(name): number for number, name in enumerate(order)}
    position = rank[tag]
    for index, sibling in enumerate(parent):
        if rank.get(sibling.tag, -1) > position:
            parent.insert(index, child)
            return
    parent.append(child)


def element(name: str, **attributes: str):
    """Create ``w:<name>`` with ``w:`` attributes."""
    node = OxmlElement(name)
    for key, value in attributes.items():
        node.set(qn(f"w:{key}"), str(value))
    return node


def set_paragraph(
    paragraph: Paragraph,
    before: int = 0,
    after: int = 0,
    line: int = 240,
    align: str | None = None,
    keep_next: bool = False,
) -> None:
    """Set spacing, alignment, and CJK autospace off on ``paragraph``."""
    ppr = paragraph._p.get_or_add_pPr()
    if keep_next:
        insert_ordered(ppr, element("w:keepNext"), ppr_order)
    insert_ordered(ppr, element("w:autoSpaceDE", val="0"), ppr_order)
    insert_ordered(ppr, element("w:autoSpaceDN", val="0"), ppr_order)
    insert_ordered(
        ppr,
        element(
            "w:spacing",
            before=before,
            after=after,
            line=line,
            lineRule="auto",
        ),
        ppr_order,
    )
    if align:
        insert_ordered(ppr, element("w:jc", val=align), ppr_order)


def add_text(
    paragraph: Paragraph,
    text: str,
    size: int = size_body,
    bold: bool = False,
    colour: str = colour_text,
) -> None:
    """Append a run with the report font on all four font slots."""
    run = paragraph.add_run(text)
    rpr = run._r.get_or_add_rPr()
    insert_ordered(
        rpr,
        element(
            "w:rFonts",
            ascii=font_name,
            hAnsi=font_name,
            eastAsia=font_name,
            cs=font_name,
        ),
        rpr_order,
    )
    insert_ordered(rpr, element("w:b", val="1" if bold else "0"), rpr_order)
    insert_ordered(rpr, element("w:color", val=colour), rpr_order)
    insert_ordered(rpr, element("w:sz", val=size), rpr_order)
    insert_ordered(rpr, element("w:szCs", val=size), rpr_order)


def borders(
    top: tuple[int, str] | None = None,
    left: tuple[int, str] | None = None,
    bottom: tuple[int, str] | None = None,
    inside: tuple[int, str] | None = None,
):
    """Return ``w:tblBorders``; ``None`` sides are drawn as nil."""
    node = OxmlElement("w:tblBorders")
    sides = {
        "w:top": top,
        "w:left": left,
        "w:bottom": bottom,
        "w:right": None,
        "w:insideH": inside,
    }
    for name in border_order:
        spec = sides[name]
        if spec is None:
            node.append(element(name, val="nil"))
        else:
            size, colour = spec
            node.append(element(name, val="single", sz=size, color=colour))
    node.append(element("w:insideV", val="nil"))
    return node


def new_table(
    document: DocumentType,
    rows: int,
    widths: Sequence[int],
    table_borders,
) -> Table:
    """Add a fixed-layout table with explicit grid and cell widths."""
    table = document.add_table(rows=rows, cols=len(widths))
    tbl = table._tbl
    old = tbl.tblPr
    tblpr = OxmlElement("w:tblPr")
    tbl.replace(old, tblpr)
    for child in (
        element("w:tblW", w=sum(widths), type="dxa"),
        element("w:jc", val="center"),
        table_borders,
        element("w:tblLayout", type="fixed"),
    ):
        insert_ordered(tblpr, child, tblpr_order)
    margins = OxmlElement("w:tblCellMar")
    for side, value in (
        ("w:top", cell_margin_vertical),
        ("w:left", cell_margin_side),
        ("w:bottom", cell_margin_vertical),
        ("w:right", cell_margin_side),
    ):
        margins.append(element(side, w=value, type="dxa"))
    insert_ordered(tblpr, margins, tblpr_order)
    grid = tbl.tblGrid
    for column in list(grid):
        grid.remove(column)
    for width in widths:
        grid.append(element("w:gridCol", w=width))
    for row in table.rows:
        for cell, width in zip(row.cells, widths, strict=True):
            set_cell(cell, width)
    return table


def set_cell(
    cell: _Cell,
    width: int,
    fill: str | None = None,
    valign: str | None = None,
) -> None:
    """Set the width, shading, and vertical alignment of ``cell``."""
    tcpr = cell._tc.get_or_add_tcPr()
    insert_ordered(tcpr, element("w:tcW", w=width, type="dxa"), tcpr_order)
    if fill:
        insert_ordered(
            tcpr,
            element("w:shd", val="clear", color="auto", fill=fill),
            tcpr_order,
        )
    if valign:
        insert_ordered(tcpr, element("w:vAlign", val=valign), tcpr_order)


def cell_text(
    cell: _Cell,
    text: str,
    size: int = size_table,
    bold: bool = False,
    colour: str = colour_text,
    align: str | None = None,
) -> Paragraph:
    """Write ``text`` into the first paragraph of ``cell``."""
    paragraph = cell.paragraphs[0]
    set_paragraph(paragraph, align=align)
    add_text(paragraph, text, size=size, bold=bold, colour=colour)
    return paragraph


def spacer(document: DocumentType, line: int = 144) -> None:
    """Add an empty paragraph of reduced height."""
    set_paragraph(document.add_paragraph(), line=line)


def heading(document: DocumentType, text: str, note: str | None) -> None:
    """Add a section heading with an optional grey note."""
    paragraph = document.add_paragraph()
    set_paragraph(paragraph, before=100, after=30, line=252, keep_next=True)
    add_text(paragraph, text, size=size_heading, bold=True)
    if note:
        add_text(paragraph, f"  {note}", size=size_note, colour=colour_faint)


def add_header(document: DocumentType, content: Content, text: dict) -> None:
    """Title, run metadata, and the final verdict."""
    table = new_table(
        document, 1, header_widths, borders(bottom=(4, colour_text))
    )
    left, right = table.rows[0].cells
    set_cell(left, header_widths[0], valign="bottom")
    set_cell(right, header_widths[1], valign="bottom")
    title = left.paragraphs[0]
    set_paragraph(title)
    add_text(title, content.title, size=size_title, bold=True)
    if content.sample_mark:
        add_text(
            title,
            f"   {content.sample_mark}",
            size=size_note + 1,
            bold=True,
            colour=colour_sample,
        )
    meta = left.add_paragraph()
    set_paragraph(meta, before=20, after=40, line=252)
    add_text(meta, content.meta, size=size_meta, colour=colour_muted)
    cell_text(
        right,
        text["final_verdict"],
        size=size_note,
        colour=colour_muted,
        align="right",
    )
    verdict = right.add_paragraph()
    set_paragraph(verdict, after=40, line=252, align="right")
    add_text(
        verdict,
        text["grades"][content.verdict],
        size=size_verdict,
        bold=True,
        colour=grade_colours[content.verdict],
    )


def add_summary(document: DocumentType, content: Content, text: dict) -> None:
    """The one-paragraph conclusion with a coloured bar."""
    table = new_table(
        document,
        1,
        (text_width,),
        borders(left=(12, colour_summary_bar)),
    )
    cell = table.rows[0].cells[0]
    set_cell(cell, text_width, fill=fill_summary)
    paragraph = cell.paragraphs[0]
    set_paragraph(paragraph, line=276)
    add_text(paragraph, f"{text['summary_label']}   ", bold=True)
    add_text(paragraph, content.summary)


def data_borders():
    """Horizontal rules only, as DevSpec 4.6.1 step 2 requires."""
    return borders(
        top=(4, colour_text),
        bottom=(4, colour_rule),
        inside=(4, colour_rule),
    )


def add_system(document: DocumentType, content: Content, text: dict) -> None:
    """System information and test conditions side by side."""
    heading(document, text["section_system"], None)
    count = max(len(content.system_rows), len(content.condition_rows))
    table = new_table(document, count, system_widths, data_borders())
    for number in range(count):
        cells = table.rows[number].cells
        pairs = (
            content.system_rows[number : number + 1],
            content.condition_rows[number : number + 1],
        )
        for offset, pair in enumerate(pairs):
            label, value = pair[0] if pair else ("", "")
            cell_text(cells[offset * 2], label, colour=colour_muted)
            cell_text(cells[offset * 2 + 1], value)


def add_charts(
    document: DocumentType,
    content: Content,
    text: dict,
    charts: Sequence[Path],
) -> None:
    """The report charts in a two-column grid without borders."""
    heading(document, text["section_charts"], content.notes["charts"])
    rows = (len(charts) + 1) // 2
    table = new_table(document, rows, chart_widths, borders())
    for number, path in enumerate(charts):
        cell = table.rows[number // 2].cells[number % 2]
        paragraph = cell.paragraphs[0]
        set_paragraph(paragraph, align="center")
        paragraph.add_run().add_picture(str(path), width=Mm(chart_width_mm))


def add_gpu_table(document: DocumentType, content: Content, text: dict) -> None:
    """One row of results per GPU with highlighted rule violations."""
    heading(document, text["section_gpus"], content.notes["gpus"])
    table = new_table(
        document, len(content.gpu_rows) + 1, gpu_widths, data_borders()
    )
    last = len(gpu_widths) - 1
    for column, label in enumerate(content.gpu_header):
        align = "left" if column == 0 else "right"
        cell_text(table.rows[0].cells[column], label, bold=True, align=align)
    for number, row in enumerate(content.gpu_rows, start=1):
        cells = table.rows[number].cells
        for column, cell in enumerate(row):
            write_cell(cells[column], cell, gpu_widths[column], column, last)


def write_cell(
    target: _Cell, cell: Cell, width: int, column: int, last: int
) -> None:
    """Write one GPU table cell with grade colour or highlight."""
    if cell.highlight:
        set_cell(target, width, fill=fill_highlight)
    align = "left" if column == 0 else "right"
    if cell.grade:
        cell_text(
            target,
            cell.text,
            bold=True,
            colour=grade_colours[cell.grade],
            align=align,
        )
    else:
        cell_text(target, cell.text, bold=cell.highlight, align=align)


def rule_widths(gpu_count: int) -> tuple[int, ...]:
    """Split the free width of the rule table among the GPU columns."""
    name, criterion, source = rule_fixed_widths
    free = text_width - name - criterion - source
    each = free // max(gpu_count, 1)
    widths = [name, criterion, *([each] * gpu_count), source]
    widths[-1] += text_width - sum(widths)
    return tuple(widths)


def add_rules(document: DocumentType, content: Content, text: dict) -> None:
    """Rule, criterion, per-GPU measurement and grade, and source."""
    heading(document, text["section_rules"], content.notes["rules"])
    gpu_count = len(content.rule_header) - 3
    widths = rule_widths(gpu_count)
    table = new_table(
        document, len(content.rule_rows) + 1, widths, data_borders()
    )
    for column, label in enumerate(content.rule_header):
        align = "right" if column == 1 else None
        cell_text(table.rows[0].cells[column], label, bold=True, align=align)
    for number, row in enumerate(content.rule_rows, start=1):
        cells = table.rows[number].cells
        cell_text(cells[0], row.name)
        cell_text(cells[1], row.criterion, align="right")
        for offset, cell in enumerate(row.cells):
            paragraph = cell_text(cells[2 + offset], f"{cell.text}  ")
            add_text(
                paragraph,
                text["grades"][cell.grade],
                size=size_note,
                bold=True,
                colour=grade_colours[cell.grade],
            )
        cell_text(cells[-1], row.source, colour=colour_muted)


def add_field(paragraph: Paragraph, instruction: str) -> None:
    """Append a simple field such as PAGE with a placeholder result."""
    add_text(paragraph, "1", size=size_footer, colour=colour_faint)
    run = paragraph._p.r_lst[-1]
    field = element("w:fldSimple", instr=f" {instruction} ")
    run.addprevious(field)
    field.append(run)


def add_footer(document: DocumentType, content: Content, text: dict) -> None:
    """Tool version, source files, and ``page / pages``."""
    footer = document.sections[0].footer
    paragraph = footer.paragraphs[0]
    set_paragraph(paragraph)
    separator = text["footer_separator"]
    add_text(
        paragraph,
        content.footer + separator,
        size=size_footer,
        colour=colour_faint,
    )
    add_field(paragraph, "PAGE")
    add_text(paragraph, " / ", size=size_footer, colour=colour_faint)
    add_field(paragraph, "NUMPAGES")


def setup_page(document: DocumentType) -> None:
    """A4 portrait with the sample's margins and the report font."""
    section = document.sections[0]
    section.page_width = Mm(page_width_mm)
    section.page_height = Mm(page_height_mm)
    section.left_margin = Mm(margin_side_mm)
    section.right_margin = Mm(margin_side_mm)
    section.top_margin = Mm(margin_top_mm)
    section.bottom_margin = Mm(margin_bottom_mm)
    section.footer_distance = Mm(footer_distance_mm)
    normal = document.styles["Normal"]
    rpr = normal.element.get_or_add_rPr()
    insert_ordered(
        rpr,
        element(
            "w:rFonts",
            ascii=font_name,
            hAnsi=font_name,
            eastAsia=font_name,
            cs=font_name,
        ),
        rpr_order,
    )
    # The default template's w:zoom lacks the required w:percent (L4).
    settings = document.settings.element
    zoom = settings.find(qn("w:zoom"))
    if zoom is not None:
        zoom.set(qn("w:percent"), "100")


def build_docx(
    content: Content,
    strings: dict,
    charts: Sequence[Path],
    path: Path,
) -> Path:
    """Write the report to ``path``.

    Args:
        content: Report text and tables.
        strings: Localized labels (``report/templates/<language>.yaml``).
        charts: Report chart PNG files in layout order.
        path: Target ``report.docx``.

    Returns:
        ``path``.
    """
    document = Document()
    setup_page(document)
    # The template starts with one empty paragraph; reuse it as the
    # gap between the header and the summary.
    body = document.element.body
    for paragraph in list(body.iterchildren(qn("w:p"))):
        body.remove(paragraph)
    add_header(document, content, strings)
    spacer(document)
    add_summary(document, content, strings)
    add_system(document, content, strings)
    add_charts(document, content, strings, charts)
    add_gpu_table(document, content, strings)
    add_rules(document, content, strings)
    add_footer(document, content, strings)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))
    return path
