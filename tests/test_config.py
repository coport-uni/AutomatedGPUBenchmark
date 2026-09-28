"""Tests for gpubench.config against the committed config/ directory."""

import pytest

from gpubench import config

expected_profiles = ["consumer", "datacenter", "quick", "workstation"]


def test_list_profiles_matches_committed_files():
    assert config.list_profiles() == expected_profiles


@pytest.mark.parametrize("name", expected_profiles)
def test_profile_keeps_every_default_key(name):
    default = config.load_yaml(config.config_dir() / config.default_file)
    profile = config.load_profile(name)
    assert set(default) <= set(profile)
    assert set(default["phases"]) <= set(profile["phases"])


def test_quick_profile_is_never_longer_than_default():
    default = config.load_yaml(config.config_dir() / config.default_file)
    quick = config.load_profile("quick")
    for key, seconds in default["phases"].items():
        assert quick["phases"][key] <= seconds
    assert quick["phases"] != default["phases"]


def test_unknown_profile_lists_the_available_ones():
    with pytest.raises(FileNotFoundError, match="quick"):
        config.load_profile("does-not-exist")


def test_config_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(config.config_dir_env, str(tmp_path))
    assert config.config_dir() == tmp_path


def test_merge_is_recursive_and_does_not_mutate_base():
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    override = {"a": {"y": 20}, "c": 4}
    merged = config.merge(base, override)
    assert merged == {"a": {"x": 1, "y": 20}, "b": 3, "c": 4}
    assert base == {"a": {"x": 1, "y": 2}, "b": 3}
