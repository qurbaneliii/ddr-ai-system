from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW = PROJECT_ROOT / "data" / "raw"


@pytest.fixture(scope="session")
def raw_dir() -> Path:
    if not RAW.exists():
        pytest.skip("Raw corpus not bootstrapped")
    return RAW


def find_raw(raw_dir: Path, folder: str, name: str) -> Path:
    path = next((raw_dir / folder).rglob(name), None)
    if not path:
        pytest.skip(f"Representative raw fixture unavailable: {name}")
    return path

