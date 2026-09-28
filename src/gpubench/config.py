"""Load the default configuration and the named profiles.

Configuration lives in ``config/`` at the repository root (DevSpec
section 3). A profile is a YAML file under ``config/profiles/`` whose
mappings are merged over ``default.yaml`` so that a profile only has
to state what differs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

config_dir_env = "GPUBENCH_CONFIG_DIR"
default_file = "default.yaml"
profiles_dir = "profiles"
profile_suffix = ".yaml"


def config_dir() -> Path:
    """Return the configuration directory.

    ``GPUBENCH_CONFIG_DIR`` overrides the default so the runtime image
    can place the files outside the source tree.
    """
    override = os.environ.get(config_dir_env)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "config"


def load_yaml(path: Path) -> dict[str, Any]:
    """Read one YAML file that must hold a mapping at the top level.

    Raises:
        ValueError: If the document is not a mapping.
    """
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return data


def merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return ``base`` updated by ``override``, merging nested mappings."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def list_profiles() -> list[str]:
    """Return the available profile names in sorted order."""
    directory = config_dir() / profiles_dir
    return sorted(path.stem for path in directory.glob(f"*{profile_suffix}"))


def load_profile(name: str) -> dict[str, Any]:
    """Return ``default.yaml`` merged with the named profile.

    Args:
        name: Profile file name without the ``.yaml`` suffix.

    Raises:
        FileNotFoundError: If no profile of that name exists.
    """
    base = load_yaml(config_dir() / default_file)
    path = config_dir() / profiles_dir / f"{name}{profile_suffix}"
    if not path.is_file():
        available = ", ".join(list_profiles())
        raise FileNotFoundError(
            f"unknown profile {name!r}; available: {available}"
        )
    return merge(base, load_yaml(path))
