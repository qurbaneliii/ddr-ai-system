# Security

- ZIP entries are normalized and rejected for path traversal, absolute/drive paths, symbolic links, executables, collisions, excessive entry sizes, aggregate size, or suspicious compression ratios.
- Upload sizes and supported file types are bounded.
- File hashes provide idempotency and unchanged-file skipping.
- Report text is untrusted data and is never interpreted as application instructions.
- SQL is parsed as an AST, limited to a single read-only query, restricted to allowed tables, bounded by row limits, and executed without user string interpolation.
- Errors exposed to users are sanitized and secrets are not logged.
- Local Ollama is the primary LLM/embedding provider; lexical retrieval is the deterministic fallback. Remote Ollama is accepted only through HTTPS with an authentication proxy token. No proprietary API key is required.
