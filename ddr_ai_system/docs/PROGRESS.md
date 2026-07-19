# Progress

## Final local status

- Rebuilt and promoted a standalone Alembic `0004` SQLite demo database using a clean full-corpus parse. Integrity and quick checks return `ok`, foreign-key violations are zero, and journal mode is `delete`.
- Unified the resolved database URL across migrations, engines, sessions, UI, analytics, chat, and ingestion. Added validated content-addressed runtime snapshots and URL-keyed engine disposal.
- Retained PostgreSQL support and added a versioned, idempotent, non-overwriting seed command for durable extracted records.
- Added scanned-PDF OCR through PyMuPDF/Tesseract with page-level method, confidence, provenance, and safe missing-runtime behavior.
- Replaced the active Ollama/semantic path with deterministic lexical retrieval and optional OpenAI Responses verbalization, safe provider errors, selected-image support, and unsupported-claim rejection.
- Refactored Streamlit into eight focused pages with one-action upload processing, bounded chat, truthful persistence/provider labels, portable source/overlay images, and isolated metric errors.
- Removed the tracked root virtual environment and added CI hygiene, SQLite verification, and PostgreSQL migration coverage on Python 3.12.

## Verified corpus

- 1,060 source documents: 1,000 reports and 60 plots.
- 10,983 operation rows and 1,291 candidate anomalies.
- 300 pressure-profile points and 709 pressure-time points.
- 244 populated equipment-failure records: 242 exact temporal matches, 1 unmatched, and 1 without a valid Operations interval.
- All 30 pressure-time images retain `unit_status=unknown`; no cross-namespace identity is inferred.

## Acceptance evidence

- Fresh editable install succeeded on Python 3.12.
- Full local suite, Ruff, mypy, compileall, database integrity/FK/count checks, and repository hygiene passed. Exact final counts are recorded in the delivery report after the last verification run.
- Local Streamlit health returned HTTP 200. Browser checks rendered Overview metrics, Report browser, Activities, candidate Trends, both pressure image/overlay tabs, one-action upload UI, lexical provider state, English plot citations/SQL/CSV, and an Azerbaijani grounded summary without app exceptions.
- `docker compose config --quiet` passed. Docker runtime execution was not available because the local Docker Desktop Linux engine pipe was absent.

## External deployment gate

The public deployment can operate as a validated SQLite demo without credentials. Durable production uploads and a real OpenAI response require manually authorized Streamlit Secrets (`DDR_DATABASE_URL` and optionally `OPENAI_API_KEY`). These secrets were not available locally and were neither read nor fabricated. Public deployment and GitHub CI are re-verified after the final push.
