"""Tests for the gpubench command-line skeleton."""

import pytest

from gpubench import __version__, cli, orchestrator
from gpubench.runtime.exit_codes import ExitCode

stub_invocations = [
    ["compare", "results/a", "results/b"],
]


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == ExitCode.PASS
    assert __version__ in capsys.readouterr().out


def test_missing_subcommand_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == ExitCode.ERROR
    assert "error" in capsys.readouterr().err


def test_invalid_gpu_class_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--gpu-class", "amd"])
    assert exc.value.code == ExitCode.ERROR


@pytest.mark.parametrize("argv", stub_invocations)
def test_stub_subcommands_report_not_implemented(argv, capsys):
    assert cli.main(argv) == ExitCode.ERROR
    assert "not implemented" in capsys.readouterr().err


def test_run_passes_options_to_orchestrator(monkeypatch, tmp_path):
    received = []

    def fake_run(options):
        received.append(options)
        return ExitCode.INCOMPLETE

    monkeypatch.setattr(orchestrator, "run", fake_run)
    argv = [
        "run",
        "--profile",
        "quick",
        "--gpu-class",
        "workstation",
        "--results-root",
        str(tmp_path),
    ]
    assert cli.main(argv) == ExitCode.INCOMPLETE
    (options,) = received
    assert options.profile == "quick"
    assert options.gpu_class == "workstation"
    assert options.results_root == tmp_path


def test_plot_rejects_a_missing_folder(tmp_path, capsys):
    assert cli.main(["plot", str(tmp_path / "missing")]) == ExitCode.ERROR
    assert "not a folder" in capsys.readouterr().err


def test_pdf_needs_a_report_docx(tmp_path, capsys):
    assert cli.main(["pdf", str(tmp_path)]) == ExitCode.ERROR
    assert "report.docx" in capsys.readouterr().err


def test_unexpected_error_exits_with_error(monkeypatch, capsys):
    def broken_run(options):
        raise RuntimeError("boom")

    monkeypatch.setattr(orchestrator, "run", broken_run)
    assert cli.main(["run", "--profile", "quick"]) == ExitCode.ERROR
    assert "unexpected error" in capsys.readouterr().err


def test_status_without_a_run_exits_zero(tmp_path, capsys):
    code = cli.main(["status", "--results-root", str(tmp_path)])
    assert code == ExitCode.PASS
    assert "no run in progress" in capsys.readouterr().out
