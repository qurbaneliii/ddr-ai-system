from __future__ import annotations

import runpy
from pathlib import Path


def _run(script: str) -> None:
    runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / script), run_name="__main__")


def audit() -> None:
    _run("audit_inputs.py")


def process() -> None:
    _run("process_all.py")


def seed_demo() -> None:
    _run("seed_demo.py")

