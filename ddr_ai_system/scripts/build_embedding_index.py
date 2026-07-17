from __future__ import annotations

from ddr_ai.config import get_settings
from ddr_ai.db.session import session_scope
from ddr_ai.nlp.providers import OllamaProvider
from ddr_ai.retrieval.semantic import build_embedding_cache


def main() -> None:
    settings = get_settings()
    provider = OllamaProvider(settings)
    health = provider.health_check(force=True)
    if not health.reachable:
        raise SystemExit(f"Ollama is unavailable: {health.reason}")
    if settings.ollama_embed_model not in health.available_models:
        raise SystemExit(
            f"Embedding model {settings.ollama_embed_model} is not installed. Pull it deliberately first."
        )
    with session_scope() as session:
        result = build_embedding_cache(
            session,
            provider,
            settings.cache_dir / "section_embeddings.sqlite",
            batch_size=settings.ollama_embedding_batch_size,
        )
    print(
        f"model={result.model} dimension={result.dimension} embedded={result.embedded} "
        f"unchanged={result.unchanged} cache={result.cache_path}"
    )


if __name__ == "__main__":
    main()
