from __future__ import annotations

import tomllib
from pathlib import Path

import grantbot
from grantbot.app import app


def test_version_is_aligned_across_package_metadata_and_api() -> None:
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    expected = metadata["project"]["version"]
    assert grantbot.__version__ == expected
    assert app.version == expected
    assert expected == "26.0.0"
