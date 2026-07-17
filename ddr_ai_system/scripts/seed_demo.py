from __future__ import annotations

from ddr_ai.config import get_settings
from ddr_ai.db.session import create_schema
from ddr_ai.services.processor import process_paths


def main() -> None:
    settings = get_settings()
    create_schema()
    candidates = []
    for pattern, folder in [
        ("15_9_19_A_1980_01_01.pdf", "ddr_pdfs"),
        ("15_9_F_14_2008_06_14.pdf", "ddr_pdfs"),
        ("Well_04_pressure_profile.png", "pressure_profiles"),
        ("pressure_time_plot_01.png", "pressure_time_plots"),
    ]:
        match = next((settings.raw_dir / folder).rglob(pattern), None)
        if match:
            candidates.append(match)
    if not candidates:
        raise SystemExit("No raw fixtures found. Run scripts/bootstrap_inputs.py first.")
    for result in process_paths(candidates):
        print(result)


if __name__ == "__main__":
    main()

