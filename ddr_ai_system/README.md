# DDR AI System

Local-first MVP for structuring, auditing, querying, and visually inspecting Daily Drilling Reports and the supplied pressure plots.

The application uses native layout-aware PDF parsing for digital reports, deterministic computer vision for plot evidence, SQLAlchemy/Alembic for normalized storage, safe read-only query controls, and Streamlit for the demonstration UI. A multilingual local Ollama model performs query analysis and grounded answer formulation; lexical retrieval remains an explicit offline fallback. No proprietary LLM API, billing account, or API key is required. Exact dataset results are generated locally in `docs/DATA_AUDIT.md` and `docs/EVALUATION.md`.

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
ollama pull qwen2.5:3b-instruct-q4_K_M
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

## Ollama modes

- Local: the app uses `http://127.0.0.1:11434` and needs no secret.
- Secure remote: configure an HTTPS Ollama-compatible reverse proxy and keep its bearer token in ignored `.env.local` or Streamlit Secrets.
- Lexical fallback: the app remains usable and labels every answer as deterministic/not LLM-generated when Ollama or the selected model is unavailable.

The selected language can be Auto, Azərbaycan dili, or English. Azerbaijani questions are rewritten into an English DDR retrieval representation before retrieval, while the original question and technical identifiers are preserved. Deterministic SQL/templates, extracted report sections, and stored plot points remain the factual sources; the LLM is never the source of exact values.

See `docs/OLLAMA.md` and copy `.env.example` to ignored `.env.local` for configuration. The optional persistent multilingual embedding index is built explicitly with `python scripts/build_embedding_index.py`; it is never rebuilt during Streamlit startup.

## Docker

```powershell
docker compose up -d ollama
docker compose exec ollama ollama pull qwen2.5:3b-instruct-q4_K_M
docker compose exec ollama ollama pull bge-m3:567m
docker compose up --build app
```

The default Compose service uses SQLite and mounts `./data`. Ollama has a persistent model volume and no host-published port. Models are pulled only through the deliberate one-time commands above. PostgreSQL is available through the optional `postgres` profile; set `DDR_DATABASE_URL` explicitly when using it.

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
