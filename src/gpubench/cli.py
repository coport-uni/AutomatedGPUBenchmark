"""Command-line entry point for gpubench.

The subcommands follow DevSpec section 3: ``run``, ``status``,
``attach``, ``stop``, ``plot``, ``compare``, and ``pdf``. All but
``compare`` are implemented; ``compare`` parses its arguments and
reports that the implementation is missing, exiting with
``ExitCode.ERROR``.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

from gpubench import __version__
from gpubench.console import mode as console_mode
from gpubench.runtime.exit_codes import ExitCode

gpu_classes = ("consumer", "workstation", "datacenter")
default_profile = "auto"
default_results_root = "/results"


class GpubenchParser(argparse.ArgumentParser):
    """Argument parser that exits with ``ExitCode.ERROR`` on usage errors.

    argparse exits with status 2 by default, which this tool reserves
    for a FAIL verdict (DevSpec section 4.8).
    """

    def error(self, message: str) -> None:  # type: ignore[override]
        """Print the usage line and ``message``, then exit with ERROR."""
        self.print_usage(sys.stderr)
        self.exit(int(ExitCode.ERROR), f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser with one subparser per command."""
    parser = GpubenchParser(
        prog="gpubench",
        description="Automated NVIDIA GPU burn-in test with a report.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"gpubench {__version__}",
    )
    commands = parser.add_subparsers(
        dest="command", metavar="COMMAND", required=True
    )

    run = commands.add_parser(
        "run", help="Run the burn-in test on every visible GPU."
    )
    run.add_argument(
        "--profile",
        default=default_profile,
        help="Profile name under config/profiles/; 'auto' picks the "
        "profile matching the detected GPU class.",
    )
    run.add_argument(
        "--gpu-class",
        choices=gpu_classes,
        help="Override the GPU class detected from the product brand.",
    )
    run.add_argument(
        "--output",
        choices=console_mode.output_modes,
        default="auto",
        help="Console mode; 'auto' selects live on a TTY, plain otherwise.",
    )
    run.add_argument(
        "--results-root",
        default=default_results_root,
        help="Directory that receives one result folder per run.",
    )

    control_help = {
        "status": "Show the state of a running test.",
        "attach": "Follow the console of a running test; Ctrl+C detaches.",
        "stop": "Stop a running test and keep an INCOMPLETE report.",
    }
    for name, text in control_help.items():
        control = commands.add_parser(name, help=text)
        control.add_argument(
            "--results-root",
            default=default_results_root,
            help="Results directory of the run (default: %(default)s).",
        )

    plot = commands.add_parser(
        "plot", help="Re-render charts and reports from a result folder."
    )
    plot.add_argument("result_dir", help="Result folder to re-render.")

    compare = commands.add_parser(
        "compare", help="Compare telemetry of two result folders."
    )
    compare.add_argument("baseline_dir", help="Reference result folder.")
    compare.add_argument("candidate_dir", help="Result folder to compare.")

    pdf = commands.add_parser(
        "pdf", help="Convert an edited report.docx back to report.pdf."
    )
    pdf.add_argument("result_dir", help="Result folder with report.docx.")

    return parser


def plot(result_dir: Path) -> int:
    """Re-render charts, dashboard, and reports of ``result_dir``."""
    from gpubench.report import render

    if not result_dir.is_dir():
        print(f"gpubench plot: {result_dir} is not a folder", file=sys.stderr)
        return int(ExitCode.ERROR)
    try:
        files = render.render(result_dir)
    except (render.ReportError, OSError, KeyError, ValueError) as exc:
        print(f"gpubench plot: {exc}", file=sys.stderr)
        return int(ExitCode.ERROR)
    for note in files.notes:
        print(f"gpubench plot: {note}")
    written = [files.docx, files.html, files.markdown, files.dashboard]
    if files.pdf:
        written.append(files.pdf)
    for path in written:
        print(f"gpubench plot: wrote {path}")
    return int(ExitCode.PASS)


def pdf(result_dir: Path) -> int:
    """Convert an edited ``report.docx`` to ``report.pdf`` again."""
    from gpubench.report import render

    try:
        path, pages = render.convert_pdf(result_dir)
    except (render.ReportError, OSError) as exc:
        print(f"gpubench pdf: {exc}", file=sys.stderr)
        return int(ExitCode.ERROR)
    print(f"gpubench pdf: wrote {path} ({pages} page(s))")
    if pages > render.max_pages:
        print(
            f"gpubench pdf: warning: more than {render.max_pages} page",
            file=sys.stderr,
        )
    return int(ExitCode.PASS)


def dispatch(args: argparse.Namespace) -> int:
    """Run the command selected in ``args``."""
    if args.command == "run":
        # Imported here so that commands which never touch the GPU do
        # not pay for loading NVML bindings.
        from gpubench import orchestrator

        options = orchestrator.RunOptions(
            profile=args.profile,
            gpu_class=args.gpu_class,
            results_root=Path(args.results_root),
            output=args.output,
        )
        return int(orchestrator.run(options))
    if args.command in ("status", "attach", "stop"):
        from gpubench.runtime import control

        command = getattr(control, args.command)
        return int(command(Path(args.results_root), sys.stdout))
    if args.command == "plot":
        return plot(Path(args.result_dir))
    if args.command == "pdf":
        return pdf(Path(args.result_dir))
    print(
        f"gpubench {args.command}: not implemented yet",
        file=sys.stderr,
    )
    return int(ExitCode.ERROR)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` and dispatch to the selected command.

    An unexpected exception exits with ``ExitCode.ERROR``: Python's own
    status 1 would read as a WARN verdict to a calling script.

    Args:
        argv: Command-line arguments without the program name. ``None``
            reads ``sys.argv``.

    Returns:
        The process exit status as an ``ExitCode`` value.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return dispatch(args)
    except Exception:
        traceback.print_exc()
        print(
            f"gpubench {args.command}: unexpected error, exit status "
            f"{int(ExitCode.ERROR)}",
            file=sys.stderr,
        )
        return int(ExitCode.ERROR)


if __name__ == "__main__":
    sys.exit(main())
