# Progress

## Completed implementation checkpoints

1. `d5b7559` — page-aware native/OCR/hybrid document processing, OCR token/table contracts, unified parser.
2. `d8b7be3` — Alembic `0006`, canonical taxonomy/backfill, evaluated activity classifier and controlled artifact.
3. `3ea50a5` — IsolationForest duration candidates, stable provenance, append-only review service/UI.
4. `2598f9a` — selected stored-plot context, grounded VLM call, claim rejection, deterministic fallback.
5. `ce03063` — bounded persistent database assets, integrity validation, reconnect test, build/runtime identity.
6. `7f10183` — fixed OCR/chat evaluations, trend contract/UI, anomaly chat boundary, final acceptance coverage and CI updates.

## Verified local state

- Database: 1,060 sources; 1,000 reports; 10,983 operations; 60 plots; 1,009 points; 18,895 chunks.
- Taxonomy: seven canonical main activities; all 10,983 existing rows retain source/raw labels and `source_rule` provenance.
- Activity model: main macro F1 0.7064; subactivity macro F1 0.5100; controlled artifact SHA verified.
- Anomalies: original 1,291 candidates preserved plus 191 ML duration candidates; 1,482 remain unreviewed and not domain-validated.
- Chat evaluation: 13/13 deterministic cases passed with valid citation filenames and no external model calls.
- OCR: routing/token/section surrogate targets passed; identity/operation/failure/table/numeric targets failed. No genuine scan claim is made.
- Tests: 137 passed; one explicit local PostgreSQL skip.
- Ruff, mypy across 61 modules, compileall, model SHA, SQLite integrity/quick/FK/revision, `git diff --check`, and Compose configuration passed.
- Docker runtime was unavailable because Docker Desktop's Linux engine pipe was absent.

## Remaining release work

- Commit final documentation, push the feature branch, pass current GitHub Actions including PostgreSQL, merge without bypassing protection, and push `main`.
- Wait for Streamlit redeployment and verify the visible build SHA/schema/provider/database state plus public pages/questions.
- Production persistence remains blocked without authorized `DDR_DATABASE_URL` and secure Streamlit configuration.
- Public VLM acceptance remains blocked without an authorized API key/VLM enablement.
- Genuine scanned-DDR benchmark remains blocked without real scans and annotations.

Final status: **Partially complete** until those external/live gates pass.
