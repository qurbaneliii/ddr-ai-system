# Deployment

## Streamlit Community Cloud

1. Set the app entrypoint to `ddr_ai_system/streamlit_app.py`.
2. In **Advanced settings**, select Python 3.12. Streamlit Community Cloud chooses Python in the deployment UI; `runtime.txt` is not used for this app.
3. `requirements.txt` installs Python dependencies and `packages.txt` installs Tesseract.
4. Add only authorized values to Streamlit Secrets. Do not commit `.streamlit/secrets.toml`.

For a durable deployment, configure `DDR_DATABASE_URL` with a PostgreSQL-compatible URL and run `scripts/seed_production.py` once against the empty database. If that secret is absent, the public app remains a truthful SQLite demo: browsing and chat work, but newly uploaded records are temporary.

Extracted page text, normalized rows, provenance, mappings, hashes, and processing jobs persist in PostgreSQL. Raw uploaded bytes do not persist unless a separate object-storage integration is configured.

## Docker

```powershell
docker compose up --build app
docker compose --profile postgres up --build
```

The default app uses SQLite. The optional profile starts PostgreSQL; supply `DDR_DATABASE_URL` to the app deliberately. Compose contains no model server and exposes no provider secret.
