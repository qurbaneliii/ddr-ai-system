# DDR AI System

Local-first MVP for structuring, auditing, querying, and visually inspecting Daily Drilling Reports and the supplied pressure plots.

The application uses native layout-aware PDF parsing for digital reports, deterministic computer vision for plot evidence, SQLAlchemy/Alembic for normalized storage, safe read-only query controls, and Streamlit for the demonstration UI. It starts without external API keys. Exact dataset results are generated locally in `docs/DATA_AUDIT.md` and `docs/EVALUATION.md`.

## Quick start (Windows PowerShell)

```powershell
python -m venv .venv --system-site-packages
.\.venv\Scripts\python.exe -m pip install -e ".[dev,ocr]"
.\.venv\Scripts\python.exe scripts\bootstrap_inputs.py --source-dir "D:\Technical_task_AI_engineer"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe scripts\audit_inputs.py
.\.venv\Scripts\python.exe scripts\process_all.py
.\.venv\Scripts\python.exe scripts\backfill_section_tables.py
.\.venv\Scripts\python.exe scripts\generate_analytics.py
.\.venv\Scripts\python.exe scripts\evaluate_pipeline.py
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

Open `http://localhost:8501`. The original source assets are copied byte-for-byte into the ignored `data/raw/source_archives/` directory and verified by SHA-256 before safe extraction.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m alembic upgrade head
```

## Docker

```powershell
docker compose up --build
```

The default Compose service uses SQLite and mounts `./data`. PostgreSQL is available through the optional `postgres` profile; set `DDR_DATABASE_URL` explicitly when using it.

## Data and confidence contract

- Raw sources remain unchanged and are content-addressed by SHA-256.
- Optional section tables retain raw cells plus normalized numeric/sentinel cells and page/table coordinates.
- Deterministic values, inferred values, candidate anomalies, and human validation states are separate.
- `-999.99` and `-999.9` are stored as `NULL` with their raw form and `source_sentinel` reason.
- The suspicious 1980 report is retained, flagged, and excluded from default trends.
- Pressure-time units remain unknown unless verified from source metadata.
- DDR wellbores, profile identifiers, and pressure-time identifiers are not mapped by numeric index.
- Plot points without successful local OCR calibration retain pixel evidence and are never presented as exact numeric measurements.

See `docs/USER_GUIDE.md`, `docs/ARCHITECTURE.md`, and `docs/SECURITY.md` for operating details.
Verified browser screenshots are retained in `docs/evidence/`.
