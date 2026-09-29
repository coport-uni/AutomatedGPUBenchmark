# Render charts and report.docx from a copied result folder and schema-check it (M5 debugging).
import sys
import warnings
from pathlib import Path

from gpubench.charts import catalog
from gpubench.report import content, context, docx_builder, ooxml

warnings.filterwarnings("ignore")
result_dir = Path(sys.argv[1])
only_issues = "--issues" in sys.argv
ctx = context.build(result_dir)
rendered = catalog.render_all(ctx)
report = content.build(ctx, only_issues=only_issues)
path = docx_builder.build_docx(
    report,
    context.strings(),
    catalog.report_charts(rendered),
    result_dir / "report.docx",
)
print(path, path.stat().st_size)
if ooxml.schemas_available():
    problems = ooxml.validate_docx(path)
    for problem in problems:
        print(problem)
    print("schema problems:", len(problems))
else:
    print("schemas not installed; validation skipped")
