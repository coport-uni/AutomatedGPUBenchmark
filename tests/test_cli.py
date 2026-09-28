"""Tests for the gpubench command-line skeleton."""

import pytest

from gpubench import __version__, cli
from gpubench.runtime.exit_codes import ExitCode

stub_invocations = [
    ["run", "--profile", "quick"],
    ["run", "--gpu-class", "workstation", "--output", "json"],
    ["status"],
    ["attach"],
    ["stop"],
    ["plot", "results/example"],
    ["compare", "results/a", "results/b"],
    ["pdf", "results/example"],
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
