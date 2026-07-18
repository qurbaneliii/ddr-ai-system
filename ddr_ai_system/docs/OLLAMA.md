# Ollama runtime and deployment modes

The chatbot uses Ollama first and automatically returns a clearly labeled deterministic/lexical answer when Ollama or the selected model is unavailable. It does not use a proprietary LLM API or require an API key.

## Selected local models

- Chat: `qwen2.5:3b-instruct-q4_K_M` (about 1.9 GB, multilingual instruction model)
- Embeddings: `bge-m3:567m` (about 1.2 GB, multilingual, 1,024 dimensions)
- Context: `4096` by default to fit an 8 GB RAM development machine

These are defaults, not machine-specific constants. Override them through environment variables, ignored `.env.local`, or Streamlit Secrets. Do not use an unversioned model alias in an evaluated deployment without recording the resolved tag/digest.

## Native Windows workflow

Install Ollama from the official Windows installer. The installer is per-user and supports an alternate install directory:

```powershell
OllamaSetup.exe /DIR="D:\Programs\Ollama"
```

If the system drive is constrained, set the user-level `OLLAMA_MODELS` directory to a drive with enough space before pulling models, then restart Ollama so it sees the setting.

Pull each model once, deliberately:

```powershell
ollama pull qwen2.5:3b-instruct-q4_K_M
ollama pull bge-m3:567m
ollama list
python -m streamlit run streamlit_app.py
```

The embedding cache is also a deliberate operation and is not created on app startup:

```powershell
python scripts/build_embedding_index.py
```

Set `OLLAMA_ENABLE_SEMANTIC_RETRIEVAL=true` only after that command succeeds. The cache records the exact embedding model and vector dimension and is rebuilt if the model changes. Lexical retrieval remains active in all modes.

## Docker Compose workflow

Docker Compose does not publish Ollama's port to the host. The raw service is reachable only as `http://ollama:11434` from the application network.

```powershell
docker compose up -d ollama
docker compose exec ollama ollama pull qwen2.5:3b-instruct-q4_K_M
docker compose exec ollama ollama pull bge-m3:567m
docker compose up -d app
docker compose ps
```

No model is pulled automatically during container startup, and no model binary belongs in Git.

## Secure remote Ollama

Remote mode is for a separately administered Ollama-compatible server behind an authenticated HTTPS reverse proxy. Set `OLLAMA_BASE_URL` to the proxy URL and store `OLLAMA_REMOTE_AUTH_TOKEN` only in `.env.local` or Streamlit Secrets. The application rejects non-HTTPS remote URLs and remote URLs without a token. Never expose raw unauthenticated Ollama directly to the public internet.

For Streamlit Community Cloud, `localhost` refers to the Cloud container, not a developer laptop. Therefore the public app will truthfully use lexical fallback unless a secure remote endpoint is configured and reachable. Running a large Ollama model inside Streamlit Community Cloud is not part of this architecture.

Example `.streamlit/secrets.toml` entries (placeholder only):

```toml
LLM_PROVIDER = "ollama"
OLLAMA_BASE_URL = "https://ollama-proxy.example.com"
OLLAMA_CHAT_MODEL = "qwen2.5:3b-instruct-q4_K_M"
OLLAMA_EMBED_MODEL = "bge-m3:567m"
OLLAMA_REMOTE_AUTH_TOKEN = "replace-in-streamlit-secrets"
```
