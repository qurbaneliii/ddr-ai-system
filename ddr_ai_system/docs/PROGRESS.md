# Progress

## Final local status

- Promoted the validated SQLite corpus to Alembic `0005` and idempotently backfilled 18,895 unique bounded retrieval chunks. Integrity and quick checks return `ok`, foreign-key violations are zero, and journal mode is `delete`.
- Unified the resolved database URL across migrations, engines, sessions, UI, analytics, chat, and ingestion. Added validated content-addressed runtime snapshots and URL-keyed engine disposal.
- Retained PostgreSQL support and extended verification with full committed-corpus seeding, seed idempotency, non-empty-target refusal, sequence checks, post-seed upload insertion, engine disposal/reconnect, and retrieval after reconnect in an isolated CI PostgreSQL database.
- Added scanned-PDF OCR through PyMuPDF/Tesseract with page-level method, confidence, provenance, and safe missing-runtime behavior.
- Replaced section-only fallback with typed deterministic query plans, an intent-handler registry, bilingual drilling synonyms, seven-source word/character TF-IDF retrieval, a relaxed second pass, bounded evidence packs, optional OpenAI structured analysis/verbalization, and citation/numeric claim rejection.
- Added bounded four-message follow-up resolution, debug-visible standalone rewrites, clear chat, corpus diagnostics, open-ended examples, and truthful not-found responses.
- Added truthful upload-asset metadata plus an explicit bounded database byte store for small demo files; object storage remains the recommended production raw-file path.
- Refactored Streamlit into eight focused pages with one-action upload processing, bounded chat, truthful persistence/provider labels, portable source/overlay images, and isolated metric errors.
- Removed the tracked root virtual environment and added CI hygiene, SQLite verification, and PostgreSQL migration coverage on Python 3.12.

## Verified corpus

- 1,060 source documents: 1,000 reports and 60 plots.
- 10,983 operation rows and 1,291 candidate anomalies.
- 300 pressure-profile points and 709 pressure-time points.
- 244 populated equipment-failure records: 242 exact temporal matches, 1 unmatched, and 1 without a valid Operations interval.
- 18,895 retrieval chunks across summaries, sections, operation groups, extracted values, optional table rows, equipment failures, and deterministic plot facts.
- All 30 pressure-time images retain `unit_status=unknown`; no cross-namespace identity is inferred.

## Acceptance evidence

- Fresh editable install succeeded on Python 3.12.
- Final local verification: 93 passed and 1 PostgreSQL-service test skipped; Ruff, mypy (53 source files), compileall, editable installation, database integrity/FK/count checks, and `git diff --check` passed.
- Local Streamlit health returned HTTP 200. Browser checks rendered Overview metrics, Report browser, Activities, candidate Trends, both pressure image/overlay tabs, one-action upload UI, lexical provider state, English plot citations/SQL/CSV, and an Azerbaijani grounded summary without app exceptions.
- `docker compose config --quiet` passed. Docker runtime execution was not available because the local Docker Desktop Linux engine pipe was absent.

## Public deployment and external gate

- GitHub Actions run `29671232570` passed with 85 tests passed and 9 explicitly corpus-dependent tests skipped. It exercised full PostgreSQL seed/reconnect and retrieval-chunk persistence; local and CI skips are intentionally reported separately.
- The public deployment was verified on 2026-07-19 with the expected 1,060 sources, 1,000 reports, 10,983 operations, and 1,009 plot points. Report browsing, portable pressure source/overlay images, upload safeguards, and temporary-persistence labeling rendered without the former database exception.
- The authorized production OpenAI configuration returned grounded English and Azerbaijani `gpt-5.6-luna` answers with deterministic citations and limitations. No key value was inspected or exposed.
- Durable production uploads remain an external deployment gate: the public sidebar reports `temporary SQLite demo`, so an authorized PostgreSQL `DDR_DATABASE_URL` must still be configured, seeded, and restart-tested. Raw uploaded bytes also require separate object storage if their persistence is desired.
