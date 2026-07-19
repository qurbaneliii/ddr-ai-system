# Deployment

## Streamlit Community Cloud

1. Set the app entrypoint to `ddr_ai_system/streamlit_app.py`.
2. In **Advanced settings**, select Python 3.12. Streamlit Community Cloud chooses Python in the deployment UI; `runtime.txt` is not used for this app.
3. `requirements.txt` installs Python dependencies and `packages.txt` installs Tesseract.
4. Add only authorized values to Streamlit Secrets. Do not commit `.streamlit/secrets.toml`.

For a durable deployment, configure `DDR_DATABASE_URL` with a PostgreSQL-compatible URL and run `scripts/seed_production.py` once against the empty database. The seed includes retrieval chunks, verifies the source snapshot, refuses a non-empty target, records its version, and repairs PostgreSQL sequences. If that secret is absent, the public app remains a truthful SQLite demo: browsing and chat work, but newly uploaded records are temporary.

Extracted page text, normalized rows, provenance, mappings, hashes, processing jobs, and retrieval chunks persist in PostgreSQL. Raw uploaded bytes default to metadata-only status and can be unavailable after restart. For a small demo, `DDR_ASSET_STORAGE_BACKEND=database` stores only files at or below `DDR_ASSET_DATABASE_MAX_MB` (maximum 5 MB); larger files remain metadata-only. Use production object storage for general raw-file persistence.

After configuring the authorized production URL:

1. Run Alembic migrations and confirm the target contains no documents.
2. Run the versioned seed exactly once and verify source/report/operation/retrieval-chunk counts.
3. Redeploy, upload one small DDR, and confirm the resulting report and chunks are searchable.
4. Restart/redeploy and repeat the search. Only then describe live upload persistence as verified.

CI performs this lifecycle against a dedicated PostgreSQL service database, including the full committed seed, a repeated no-op seed, non-empty-target refusal, sequence-generated IDs, upload insertion, engine disposal/reconnect, and retrieval after reconnect. CI evidence does not replace the separate live Streamlit secret/restart check.

## Docker

```powershell
docker compose up --build app
docker compose --profile postgres up --build
```

The default app uses SQLite. The optional profile starts PostgreSQL; supply `DDR_DATABASE_URL` to the app deliberately. Compose contains no model server and exposes no provider secret.
