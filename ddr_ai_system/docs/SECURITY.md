# Security

- Secrets are read only from ignored `.env.local`, environment variables, or supported Streamlit Secrets. They are never displayed, logged, committed, or embedded in client code.
- Provider exceptions are classified into sanitized authentication, rate-limit, timeout, connection, and HTTP-status messages. Provider health uses configuration and last-request state, not a paid probe.
- ZIP uploads reject traversal, absolute/drive paths, links, executables, collisions, oversized entries/archives, and suspicious compression ratios. File count, type, question length, request rate, history, and session question limits are bounded.
- SHA-256 makes ingestion idempotent. Uploads use one submit action and duplicate content is skipped.
- Report text is untrusted data. SQL is AST-validated, single-statement and `SELECT`-only, with allowlisted tables/columns and bounded results.
- Exact numeric facts, citations, units, mappings, and candidate status come from deterministic storage. Generated answers introducing unsupported numbers, units, mappings, or incident claims are rejected.
- The committed database is standalone, uses `journal_mode=delete`, and must pass integrity and foreign-key checks. WAL/SHM files, virtual environments, logs, and secret files are ignored and rejected by CI hygiene checks.
- SQLite demo uploads do not persist across redeployment. PostgreSQL persists extracted records; raw-file durability requires separately authorized object storage.
