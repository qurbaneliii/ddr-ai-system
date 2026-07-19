# DDR AI System

Evidence-first Daily Drilling Report processing and analysis. The application reads digital and scanned PDFs, digitizes pressure plots, stores normalized facts and provenance in SQL, visualizes trends and candidate anomalies, and answers grounded questions in English or Azerbaijani.

The SQL database and deterministic analytics are the factual source of truth. A typed query plan selects a trusted structured handler or ranked multi-source corpus retrieval. OpenAI may analyze an unclear question and verbalize a bounded evidence pack when configured; it never supplies SQL, counts, citations, units, identity mappings, or engineering conclusions. Without an API key, the same workflows remain available through the explicit deterministic/lexical fallback.

Public demo: <https://ddr-intelligence-qurbaneliii.streamlit.app/>

## Quick start on Windows

Python 3.12 is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

The repository ships a validated standalone SQLite demo database at `data/processed/ddr_ai.db`. Raw source archives are intentionally excluded. To rebuild from authorized sources, use `scripts/bootstrap_inputs.py`, `scripts/process_all.py`, and `scripts/evaluate_pipeline.py`.

## Configuration

Local secrets belong only in ignored `.env.local`; deployment secrets belong in Streamlit Secrets. Never commit either file.

```dotenv
DDR_DATABASE_URL=postgresql+psycopg://user:password@host:5432/database
LLM_PROVIDER=openai
OPENAI_API_KEY=configure-manually
OPENAI_MODEL=gpt-5.6-luna
OPENAI_TIMEOUT_SECONDS=60
OPENAI_MAX_RETRIES=2
OPENAI_MAX_OUTPUT_TOKENS=1200
DDR_ASSET_STORAGE_BACKEND=metadata_only
DDR_ASSET_DATABASE_MAX_MB=2
```

- SQLite is the zero-configuration local/read-only demo. Upload-derived records are temporary because Streamlit runtime storage is ephemeral.
- PostgreSQL-compatible `DDR_DATABASE_URL` is the production persistence path. Extracted text, rows, hashes, retrieval chunks, and provenance persist across redeployments.
- Raw upload storage defaults to `metadata_only`: SHA-256, filename, media type, byte size, storage key, and truthful status persist, while source bytes may disappear after restart. `DDR_ASSET_STORAGE_BACKEND=database` explicitly enables a bounded demo store up to `DDR_ASSET_DATABASE_MAX_MB` (maximum 5 MB); production object storage remains preferable.
- `gpt-5.6-luna` is the cost-conscious default verified against the official OpenAI model catalog in July 2026. Keep `OPENAI_MODEL` configurable for account availability and future changes.
- `OPENAI_VLM_ENABLED=true` enables the bounded, selected-image description method. Deterministic CV facts remain authoritative.

Seed an empty production database deliberately and idempotently:

```powershell
$env:DDR_DATABASE_URL = "postgresql+psycopg://..."
.\.venv\Scripts\python.exe scripts\seed_production.py --confirm-empty-target --seed-version demo-2026-07
```

The command refuses a target that already contains documents and records the applied seed version. It never runs during app startup.

## Grounded chat scope

Chat answers only from the processed DDR corpus. It searches bounded chunks from report summaries, narrative sections, operations, extracted values, optional table rows, equipment failures, and deterministic plot facts. Word and character TF-IDF ranking is portable across SQLite and PostgreSQL, includes drilling-domain synonyms, and uses a second relaxed pass before returning “not found in corpus.”

Trusted handlers retain deterministic SQL for summaries, report lookups, activity aggregation, failures, plots, and verified mappings. Up to four recent conversational messages may resolve references such as “that report” or “bunlardan ən sonuncusu”; history is never evidence. Every generated citation must name a supplied evidence source, and generated numbers must already exist in the evidence pack.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m compileall -q src streamlit_app.py
```

For local OCR, install Tesseract and then use the normal app flow. Streamlit Community Cloud installs it from `packages.txt`. Digital PDFs continue through native `pdfplumber` extraction.

## Data contract

- `-999.99` and `-999.9` become `NULL` with the raw value and `source_sentinel` reason preserved.
- Pressure-time units remain unknown because the sources do not establish a unit.
- Numeric filename similarity never establishes identity across DDR wellbores, pressure profiles, pressure-time images, or displayed series.
- Automated anomalies and plot band classifications are review candidates, not validated drilling incidents.
- Processing is content-addressed by SHA-256 and unchanged files are skipped.

See [Architecture](docs/ARCHITECTURE.md), [Deployment](docs/DEPLOYMENT.md), [Security](docs/SECURITY.md), [Evaluation](docs/EVALUATION.md), [User guide](docs/USER_GUIDE.md), and the [task-compliance matrix](docs/TASK_COMPLIANCE.md).
