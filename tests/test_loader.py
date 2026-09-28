"""Fixture-based smoke tests for gpubench.analysis.loader."""

from pathlib import Path

import pytest

from gpubench.analysis import loader

fixtures_dir = Path(__file__).parent / "fixtures"
synthetic_fixtures = ("consumer", "datacenter")
measured_fixtures = ("workstation",)
all_fixtures = synthetic_fixtures + measured_fixtures
expected_phases = ["idle", "burn_warmup", "burn_steady"]
# ECC is disabled on the Quadro RTX 6000 pair, so NVML reports these
# fields as unsupported and the collector stores null (LP E3).
unsupported_on_workstation = ("temp_mem", "ecc_corr", "ecc_uncorr")


@pytest.mark.parametrize("name", synthetic_fixtures)
def test_fixture_is_marked_synthetic(name):
    run = loader.load_result_dir(fixtures_dir / name)
    assert run.sysinfo["synthetic"] is True


@pytest.mark.parametrize("name", measured_fixtures)
def test_measured_fixture_is_idle_only_and_not_synthetic(name):
    run = loader.load_result_dir(fixtures_dir / name)
    assert run.sysinfo["synthetic"] is False
    assert run.phases == ["idle"]


def test_workstation_fixture_stores_null_for_unsupported_fields():
    run = loader.load_result_dir(fixtures_dir / "workstation")
    for sample in run.samples:
        for field in unsupported_on_workstation:
            assert sample[field] is None


@pytest.mark.parametrize("name", all_fixtures)
def test_every_listed_gpu_has_the_same_number_of_samples(name):
    run = loader.load_result_dir(fixtures_dir / name)
    listed = [gpu["index"] for gpu in run.sysinfo["gpus"]]
    assert run.gpu_indices == listed
    counts = {
        index: sum(1 for s in run.samples if s["gpu_index"] == index)
        for index in run.gpu_indices
    }
    assert len(set(counts.values())) == 1


@pytest.mark.parametrize("name", all_fixtures)
def test_samples_carry_every_telemetry_field(name):
    run = loader.load_result_dir(fixtures_dir / name)
    for sample in run.samples:
        assert set(loader.telemetry_fields) <= set(sample)


@pytest.mark.parametrize("name", synthetic_fixtures)
def test_phases_appear_in_test_order(name):
    run = loader.load_result_dir(fixtures_dir / name)
    assert run.phases == expected_phases


def test_missing_field_is_reported_with_line_number(tmp_path):
    path = tmp_path / loader.telemetry_file
    path.write_text('{"ts": "2026-09-28T00:00:00Z"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r":1: missing fields"):
        loader.load_telemetry(path)


def test_invalid_json_is_reported_with_line_number(tmp_path):
    path = tmp_path / loader.telemetry_file
    path.write_text("\n{not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r":2: invalid JSON"):
        loader.load_telemetry(path)


def test_sysinfo_requires_top_level_keys(tmp_path):
    path = tmp_path / loader.sysinfo_file
    path.write_text('{"hostname": "x"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"missing keys"):
        loader.load_sysinfo(path)
