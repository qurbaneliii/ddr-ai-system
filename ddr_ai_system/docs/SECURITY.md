# Security

## Secrets and identity

- Secrets are accepted only from ignored `.env.local`, environment variables, or allowlisted Streamlit Secrets keys.
- Database URLs, API keys, passwords, internal paths, and raw exceptions are never rendered. Build diagnostics contain sanitized modes/versions and a validated short hexadecimal SHA only.
- Provider failures are reduced to authentication, rate, timeout, connection, HTTP-status, or empty-response categories.

## Upload and parsing boundaries

- Filenames are normalized; ZIP traversal, drive/absolute paths, links, executables, collisions, excessive count/size/ratio, and unsupported types are rejected.
- Accepted production source files must fit the persistent database asset limit. Oversized files are rejected before extraction.
- Stored bytes are checked against metadata size and SHA-256 on write and every load. PDF signatures and decoded image content are validated.
- OCR and visual images enforce pixel bounds; PIL decompression-bomb failures are rejected.
- Malformed/encrypted PDFs fail safely at the processing boundary. Public errors do not contain exception details.

## Model and LLM boundaries

- `joblib` loads only the fixed project-controlled activity artifact path. The artifact SHA-256 must match committed metadata and promotion must be true; a missing/invalid artifact falls back to rules.
- Uploaded models are never loaded.
- Report text and prior chat text are untrusted. Conversation history resolves references only and is never evidence.
- SQL is generated only by trusted handlers or validated as one bounded `SELECT` over allowlisted tables/columns.
- OpenAI never supplies SQL, counts, source citations, units, mappings, candidate status, or engineering conclusions.
- PDFs are not sent to a visual provider automatically. Only one explicitly selected stored pressure image may enter one bounded VLM request.
- Generated numbers, filenames, units, mappings, anomaly confirmations, thresholds, causes, and recommendations are validated; rejected text is replaced by deterministic evidence.

## Data and transaction boundaries

- SHA-256 content identity makes processing/repeated upload idempotent.
- PostgreSQL engines use `pool_pre_ping`; session errors roll back.
- Model candidates have stable unique keys. Reviews append history and do not rewrite prior decisions.
- The committed SQLite database uses `journal_mode=delete` and must pass integrity, quick, and foreign-key checks. WAL/SHM files are ignored and rejected by CI hygiene.
- Candidate anomalies and pressure bands are not domain-validated facts. The committed database intentionally contains zero fake reviews.

## Verification

CI scans tracked paths for environments, secrets, WAL/SHM artifacts, and generated databases; runs Ruff, mypy, tests, compileall, SQLite integrity/revision, PostgreSQL migration/seed/reconnect, deterministic evaluation contracts, and Compose validation. A green CI run does not substitute for production secret, restart, or live-browser verification.
