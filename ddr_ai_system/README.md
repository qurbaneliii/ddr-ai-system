# DDR Intelligence AI System

Evidence-first Daily Drilling Report processing, analytics, and grounded chat. The application page-routes native, scanned, and hybrid PDFs; extracts text, sections, tables, operations, equipment failures, and numeric fields with provenance; digitizes pressure plots; stores facts in SQL; evaluates operational activity and anomaly candidates; and answers corpus-bound questions in English or Azerbaijani.

Public application: <https://ddr-intelligence-qurbaneliii.streamlit.app/>

The public URL is only considered current when its **Build & runtime** panel matches GitHub `main`, schema `0006`, and the configured database/provider modes. Code or CI success alone is not live-deployment proof.

## What is implemented

- Page-aware PDF routing inspects every page and chooses native extraction or OCR per page. Mixed files use one `HYBRID_PDF` parse and preserve each page's extraction method and confidence.
- OCR has immutable token/bounding-box evidence and focused reconstruction for Operations, Equipment Failure Information, header fields, and selected numeric tables.
- A canonical activity taxonomy preserves raw labels and consolidates known spacing, underscore, slash, concatenation, and OCR variants.
- Classification precedence is explicit: valid source label → deterministic rule/alias normalization → SHA-verified TF-IDF/LogisticRegression fallback → low-confidence `unknown`. Existing source labels are never overwritten by ML.
- Rule/data-quality candidates and IsolationForest duration candidates are separate. Append-only human review records `confirmed`, `rejected`, or `needs_more_evidence`.
- Daily summaries and parameter trends remain deterministic, cited, unit-compatible, date-aware, and data-quality aware.
- Chat uses trusted structured handlers or bounded word/character TF-IDF retrieval over SQL-backed evidence. Current prices, news, absent wells/dates, unsupported units, mappings, and engineering conclusions are refused.
- A selected stored pressure plot can be sent once to a configured OpenAI visual model. Numeric, citation, unit, and candidate-status validation can reject its output and return deterministic facts.
- PostgreSQL is the durable deployment path. Accepted files at or below the configured database asset limit retain source bytes; larger files are rejected before processing.
- The sidebar exposes package/parser versions, Alembic revision, short build SHA, database/seed/model modes, and LLM/VLM state without revealing secrets or internal paths.

## Current evidence and boundary

Local verification on 2026-07-21 passed 137 tests with one explicit skip because a dedicated local PostgreSQL URL was not configured. Ruff, mypy across 61 source modules, compileall, SQLite integrity/quick/foreign-key checks, artifact-hash verification, and Compose configuration passed. Docker runtime was unavailable because the Docker Desktop Linux engine was not running.

The committed corpus contains 1,060 source documents, 1,000 reports, 10,983 operations, 60 plots, 1,009 plot points, 18,895 retrieval chunks, 1,291 original rule/data-quality/plot candidates, and 191 additional ML candidates. It contains zero genuine scanned PDFs and zero human anomaly reviews.

Final status remains **Partially complete** until genuine scanned DDRs are benchmarked, production PostgreSQL upload/restart behavior is verified, an authorized VLM call is verified in the public app, and the deployed SHA matches `main`.

## Quick start on Windows

Python 3.12 is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,ocr]"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

Install Tesseract for the default document OCR backend. Streamlit Community Cloud installs it from `packages.txt`; Docker installs it in the image. The optional RapidOCR dependency is used by the clearly labelled local surrogate benchmark, not as evidence of genuine scanned-DDR validation.

## Configuration

Local secrets belong only in ignored `.env.local`; deployment secrets belong in Streamlit Secrets. Never commit either file or paste credentials into issue/PR/chat text.

```dotenv
DDR_DATABASE_URL=postgresql+psycopg://user:password@host:5432/database
DDR_ASSET_STORAGE_BACKEND=database
DDR_ASSET_DATABASE_MAX_MB=2
DDR_BUILD_SHA=<deployed-main-sha>
LLM_PROVIDER=openai
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.6-luna
OPENAI_VLM_ENABLED=false
OPENAI_VLM_MODEL=gpt-5.6-luna
```

- SQLite is a validated local/public demo snapshot. Uploads made to its ephemeral runtime can disappear on restart even if bytes are stored inside that runtime database.
- PostgreSQL-compatible `DDR_DATABASE_URL` is required for durable deployment records.
- `DDR_ASSET_STORAGE_BACKEND=database` stores accepted source bytes only up to `DDR_ASSET_DATABASE_MAX_MB` (1–5 MB). The uploader rejects a larger non-ZIP file before processing; extracted ZIP entries are subject to the same processing limit.
- `OPENAI_VLM_ENABLED=true` allows only the explicitly selected stored plot image to enter the visual flow. PDFs are never sent automatically.
- If OpenAI is absent or fails, the UI truthfully reports lexical/deterministic fallback.

Seed an empty production database deliberately and idempotently:

```powershell
$env:DDR_DATABASE_URL = "postgresql+psycopg://..."
.\.venv\Scripts\python.exe scripts\seed_production.py --confirm-empty-target --seed-version committed-ddr-v0006
```

The command refuses a non-empty target, records the seed version, repairs PostgreSQL sequences, and is never run automatically by app startup.

## Evaluation commands

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_activity_classifier.py
.\.venv\Scripts\python.exe scripts\generate_ml_anomalies.py --dry-run
.\.venv\Scripts\python.exe scripts\evaluate_chat.py
.\.venv\Scripts\python.exe scripts\evaluate_ocr.py --mode surrogate --backend rapidocr --sample-count 3 --dpi 150
```

The OCR surrogate is not a real scan benchmark. Populate `data/evaluation/ocr_manifest.csv` with authorized human annotations and use `--mode real --input-root ... --annotation-root ...` only when genuine scans are supplied.

## Quality gates

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts="" -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m compileall -q src streamlit_app.py scripts
docker compose config --quiet
```

See [Architecture](docs/ARCHITECTURE.md), [Evaluation](docs/EVALUATION.md), [Deployment](docs/DEPLOYMENT.md), [Security](docs/SECURITY.md), [User guide](docs/USER_GUIDE.md), and [Task compliance](docs/TASK_COMPLIANCE.md).
