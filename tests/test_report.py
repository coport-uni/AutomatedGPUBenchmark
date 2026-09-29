"""Tests for the charts, report content, Word builder, and pipeline."""

import copy
import shutil
import zipfile
from pathlib import Path

import pytest
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from gpubench.charts import catalog, interactive_plotly
from gpubench.report import (
    content,
    context,
    docx2pdf,
    docx_builder,
    ooxml,
    render,
)

fixture_dir = Path(__file__).parent / "fixtures" / "runs"
fixture_dir /= "workstation_quick_ok"
wml = {"w": ooxml.wml_ns}
needs_schemas = pytest.mark.skipif(
    not ooxml.schemas_available(), reason="OOXML schemas not installed"
)
needs_office = pytest.mark.skipif(
    not docx2pdf.available(), reason="LibreOffice with UNO not installed"
)


@pytest.fixture(scope="module")
def result_dir(tmp_path_factory):
    target = tmp_path_factory.mktemp("run") / "result"
    shutil.copytree(fixture_dir, target)
    return target


@pytest.fixture(scope="module")
def ctx(result_dir):
    return context.build(result_dir)


@pytest.fixture(scope="module")
def rendered(ctx):
    return catalog.render_all(ctx)


def warn_context(ctx):
    """Return a copy of ``ctx`` where GPU 1 had SW thermal slowdown."""
    changed = copy.deepcopy(ctx)
    throttled_s = 313
    for rule in changed.evaluation["rules"]:
        if rule["key"] == "sw_thermal":
            rule["gpus"][1]["grade"] = "WARN"
    changed.evaluation["gpus"][1]["throttle_s"]["sw_thermal"] = throttled_s
    changed.evaluation["verdict"] = "WARN"
    return changed


def document_xml(path):
    with zipfile.ZipFile(path) as package:
        return etree.fromstring(package.read("word/document.xml"))


def test_context_spans_cover_every_phase_in_order(ctx):
    assert [p for p, _, _ in ctx.phase_spans] == list(context.phase_order)
    ends = [end for _, _, end in ctx.phase_spans]
    starts = [start for _, start, _ in ctx.phase_spans]
    assert starts[1:] == ends[:-1]


def test_every_applicable_chart_has_png_and_svg(rendered):
    report_names = [s.name for s in catalog.catalog if s.in_report]
    assert set(report_names) <= set(rendered)
    for files in rendered.values():
        assert files["png"].stat().st_size > 0
        assert files["svg"].stat().st_size > 0
    assert [p.stem for p in catalog.report_charts(rendered)] == report_names


def test_content_of_a_clean_run(ctx):
    report = content.build(ctx)
    assert report.verdict == "PASS"
    assert report.sample_mark is None
    assert len(report.rule_rows) == len(ctx.evaluation["rules"])
    assert [row[0].text for row in report.gpu_rows] == ["GPU 0", "GPU 1"]
    assert not any(cell.highlight for row in report.gpu_rows for cell in row)
    assert context.strings()["summary_clean"] in report.summary
    # Rule cells carry the Korean measurement, not the evaluator text.
    temperature = next(r for r in report.rule_rows if r.name == "최고 온도")
    assert temperature.criterion == "Slowdown 91 °C 미만"
    assert [c.text for c in temperature.cells] == ["71.0 °C", "71.0 °C"]
    ecc = next(r for r in report.rule_rows if r.name == "ECC DBE 증가")
    assert {c.text for c in ecc.cells} == {"해당 없음"}


def test_only_issue_rules_remain_when_filtered(ctx):
    assert content.build(ctx, only_issues=True).rule_rows == []
    report = content.build(warn_context(ctx), only_issues=True)
    assert [r.name for r in report.rule_rows] == ["SW Thermal Slowdown"]
    assert report.rules_filtered
    assert report.notes["rules"] == context.strings()["section_rules_filtered"]


def test_warn_highlights_the_cell_and_names_it_in_the_summary(ctx):
    report = content.build(warn_context(ctx))
    header = report.gpu_header
    column = header.index(context.strings()["gpu_columns"]["sw_thermal"])
    assert report.gpu_rows[1][column].highlight
    assert report.gpu_rows[1][column].text == "313"
    assert not report.gpu_rows[0][column].highlight
    assert report.gpu_rows[1][-1].grade == "WARN"
    assert "GPU 1: SW Thermal Slowdown WARN (313 s)." in report.summary


def test_insert_ordered_follows_the_schema_sequence():
    ppr = OxmlElement("w:pPr")
    for name in ("w:jc", "w:spacing", "w:autoSpaceDE", "w:keepNext"):
        docx_builder.insert_ordered(
            ppr, OxmlElement(name), docx_builder.ppr_order
        )
    docx_builder.insert_ordered(
        ppr, OxmlElement("w:spacing"), docx_builder.ppr_order
    )
    tags = [etree.QName(child).localname for child in ppr]
    assert tags == ["keepNext", "autoSpaceDE", "spacing", "jc"]


@pytest.mark.parametrize("gpu_count", [1, 2, 4, 8])
def test_rule_table_fills_the_text_width(gpu_count):
    widths = docx_builder.rule_widths(gpu_count)
    assert len(widths) == gpu_count + 3
    assert sum(widths) == docx_builder.text_width


def test_docx_tables_have_grid_width_and_fixed_layout(ctx, rendered, tmp_path):
    path = docx_builder.build_docx(
        content.build(ctx),
        context.strings(),
        catalog.report_charts(rendered),
        tmp_path / "report.docx",
    )
    root = document_xml(path)
    tables = root.findall(".//w:tbl", wml)
    assert tables
    for table in tables:
        grid = [
            int(col.get(qn("w:w")))
            for col in table.findall("w:tblGrid/w:gridCol", wml)
        ]
        width = table.find("w:tblPr/w:tblW", wml)
        assert int(width.get(qn("w:w"))) == sum(grid)
        layout = table.find("w:tblPr/w:tblLayout", wml)
        assert layout.get(qn("w:type")) == "fixed"
    assert len(root.findall(".//w:drawing", wml)) == len(
        catalog.report_charts(rendered)
    )
    fonts = root.findall(".//w:rFonts", wml)
    assert fonts
    assert all(f.get(qn("w:eastAsia")) == docx_builder.font_name for f in fonts)
    with zipfile.ZipFile(path) as package:
        settings = etree.fromstring(package.read("word/settings.xml"))
        footer = package.read("word/footer1.xml").decode("utf-8")
    zoom = settings.find("w:zoom", wml)
    assert zoom.get(qn("w:percent")) == "100"
    assert "PAGE" in footer and "NUMPAGES" in footer


@needs_schemas
def test_docx_is_schema_valid(ctx, rendered, tmp_path):
    for only_issues in (False, True):
        path = docx_builder.build_docx(
            content.build(warn_context(ctx), only_issues=only_issues),
            context.strings(),
            catalog.report_charts(rendered),
            tmp_path / f"report_{only_issues}.docx",
        )
        assert ooxml.validate_docx(path) == []


def test_dashboard_embeds_plotly(ctx):
    path = interactive_plotly.write_dashboard(ctx)
    html = path.read_text(encoding="utf-8")
    assert "GPU 0" in html and "GPU 1" in html
    # The library is inlined, not loaded from a CDN.
    assert '<script src="http' not in html
    assert "Plotly" in html


def test_render_without_pdf_writes_every_file(result_dir):
    files = render.render(result_dir, pdf=False)
    for path in (files.docx, files.html, files.markdown, files.dashboard):
        assert path.is_file()
    assert files.pdf is None
    markdown = files.markdown.read_text(encoding="utf-8")
    assert "](charts/png/temperature.png)" in markdown
    html = files.html.read_text(encoding="utf-8")
    assert "data:image/png;base64," in html
    assert "✓ PASS" in html


def test_long_pdf_is_rebuilt_with_issue_rules_only(result_dir, monkeypatch):
    two_pages, one_page = 2, 1
    pages = iter([two_pages, one_page])
    built = []
    original = content.build

    def spy_build(ctx, only_issues=False):
        built.append(only_issues)
        return original(ctx, only_issues)

    monkeypatch.setattr(render.docx2pdf, "available", lambda: True)
    monkeypatch.setattr(
        render,
        "convert_pdf",
        lambda d: (d / render.pdf_file, next(pages)),
    )
    monkeypatch.setattr(render.content_tools, "build", spy_build)
    files = render.render(result_dir)
    assert built == [False, True]
    assert files.rules_filtered
    assert files.pdf_pages == one_page
    assert files.notes == [] or all("schema" in n for n in files.notes)


def test_schema_violation_fails_the_report(result_dir, monkeypatch):
    problem = ooxml.Problem("word/document.xml", 1, "broken")
    monkeypatch.setattr(render.ooxml, "schemas_available", lambda: True)
    monkeypatch.setattr(render.ooxml, "validate_docx", lambda p: [problem])
    with pytest.raises(render.ReportError, match="broken"):
        render.render(result_dir, pdf=False)


@needs_office
def test_pdf_is_one_page_without_cjk_digit_spacing(result_dir):
    files = render.render(result_dir)
    assert files.pdf_pages == 1
    from pypdf import PdfReader

    text = PdfReader(str(files.pdf)).pages[0].extract_text()
    assert "0건" in text
    assert "0 건" not in text
