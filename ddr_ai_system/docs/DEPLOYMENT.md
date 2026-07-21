# Deployment

## Streamlit Community Cloud

1. Repository: `qurbaneliii/ddr-ai-system`; branch: `main`; entrypoint: `ddr_ai_system/streamlit_app.py`.
2. Select Python 3.12 in Advanced settings. `requirements.txt` installs Python packages and `packages.txt` installs Tesseract.
3. Configure secrets only in Streamlit Secrets. Never commit `.streamlit/secrets.toml`, expose a database URL in the UI, or paste a credential into chat/PR text.
4. Configure a persistent PostgreSQL database before claiming durable uploads.

Required production values:

```toml
DDR_DATABASE_URL = "postgresql+psycopg://..."
DDR_ASSET_STORAGE_BACKEND = "database"
DDR_ASSET_DATABASE_MAX_MB = 2
DDR_BUILD_SHA = "<full-main-commit-sha>"
LLM_PROVIDER = "openai"
OPENAI_API_KEY = "" # set only through the Streamlit secret editor
OPENAI_MODEL = "gpt-5.6-luna"
OPENAI_VLM_ENABLED = true
OPENAI_VLM_MODEL = "gpt-5.6-luna"
```

The OpenAI values are optional for deterministic/lexical operation. PostgreSQL and the database asset backend are required for live upload/restart compliance. If PostgreSQL is absent, the UI must say `temporary SQLite demo`.

## Production database procedure

Use a secure operator environment; do not print the resolved URL.

1. Verify a connection with a secret-safe success/failure check.
2. Run `python -m alembic upgrade head` and confirm revision `0006`.
3. Query only whether `source_documents` is empty.
4. If and only if empty, run:

   ```powershell
   .\.venv\Scripts\python.exe scripts\seed_production.py `
     --confirm-empty-target `
     --seed-version committed-ddr-v0006
   ```

5. Verify 1,060 source documents, 1,000 reports, 10,983 operations, 60 plots, 1,009 points, 18,895 chunks, and seed version `committed-ddr-v0006`.
6. Rerun the seed and require `already_applied`; never overwrite a non-empty target.
7. Deploy current `main` with `DDR_BUILD_SHA` set to that commit.
8. Upload one valid DDR below the configured asset limit. Verify report/sections/operations/chunks and a `stored_assets.storage_status='stored'` row with non-null bytes.
9. Query a unique uploaded evidence marker.
10. Restart/redeploy, verify the visible SHA/mode again, query the marker again, and load/hash-check the stored bytes.

Only after step 10 may live persistence be called complete.

## Asset policy

- The default backend is the bounded SQL `database` backend.
- A non-ZIP upload larger than `DDR_ASSET_DATABASE_MAX_MB` is rejected before processing. Extracted ZIP members meet the same processing policy.
- Stored content is verified by size and SHA-256; PDFs require a PDF signature and images must decode within pixel limits.
- The 1–5 MB limit is suitable for the take-home demo. General large-file production use should add an explicitly authorized object store rather than silently retaining metadata only.

## Build and provider parity

The public sidebar **Build & runtime** panel must show:

- build SHA equal to GitHub `main`;
- parser `0.3.0`;
- schema `0006`;
- `persistent PostgreSQL` for the final production acceptance;
- active seed/model versions;
- truthful LLM mode/model and VLM state.

If the SHA is old, the deployment is incomplete even when the URL returns HTTP 200.

## Docker

```powershell
docker compose config --quiet
docker compose up --build app
docker compose --profile postgres up --build
```

`docker compose config --quiet` validates configuration only. Run `docker info` before claiming runtime verification. The final local run could not reach Docker Desktop's Linux engine; no local container/PostgreSQL runtime claim is made.

## Rollback

- Application rollback: redeploy a known good `main` commit without changing database credentials.
- Database migration downgrade should be used only after backup and explicit review; migration `0006` is compatible with SQLite and PostgreSQL.
- Never reseed or delete a non-empty production database as a rollback mechanism.
