"""Command-line entry point for gpubench.

The subcommands follow DevSpec section 3: ``run``, ``status``,
``attach``, ``stop``, ``plot``, ``compare``, and ``pdf``. In the M1
skeleton every subcommand parses its arguments and then reports that
the implementation is missing, exiting with ``ExitCode.ERROR``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from gpubench import __version__
from gpubench.runtime.exit_codes import ExitCode

gpu_classes = ("consumer", "workstation", "datacenter")
output_modes = ("auto", "live", "plain", "json")
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
        choices=output_modes,
        default="auto",
        help="Console mode; 'auto' selects live on a TTY, plain otherwise.",
    )
    run.add_argument(
        "--results-root",
        default=default_results_root,
        help="Directory that receives one result folder per run.",
    )

    commands.add_parser("status", help="Show the state of a running test.")
    commands.add_parser("attach", help="Follow the console of a running test.")
    commands.add_parser("stop", help="Stop a running test and keep a report.")

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


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` and dispatch to the selected command.

    Args:
        argv: Command-line arguments without the program name. ``None``
            reads ``sys.argv``.

    Returns:
        The process exit status as an ``ExitCode`` value.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    print(
        f"gpubench {args.command}: not implemented yet (M1 skeleton)",
        file=sys.stderr,
    )
    return int(ExitCode.ERROR)


if __name__ == "__main__":
    sys.exit(main())
