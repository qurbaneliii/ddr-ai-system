# Architecture

## Grounded multilingual query path

The chat path is `question -> deterministic language/intent guard -> Ollama structured query analysis when available -> English DDR retrieval representation -> deterministic SQL and/or hybrid report/plot retrieval -> verified fact bundle -> Ollama grounded verbalization -> unsupported-claim validation -> rendered answer plus citations`. Azerbaijani, English, and mixed questions share the same factual routes; an explicit UI language selection overrides automatic response-language detection.

Known structured intents use SQLAlchemy templates. Any future model-generated SQL must pass the existing single-statement, SELECT-only AST validator with table and column allowlists plus a clamped row limit before a read-only execution session. User text is never interpolated into SQL.

Narrative retrieval always retains lexical matching. Optional semantic retrieval reads a persistent section-level cache keyed by exact embedding model, dimension, content hash, and section identifier. The index is built by an explicit script, not on Streamlit reruns or startup. Reciprocal-rank hybrid scoring combines the two result paths while preserving PDF/page/section provenance.

Plot questions use stored deterministic digitization results. The model may explain supplied MIN/BASE/MAX/Virgin relationships, trends, candidate status, and uncertainty, but it cannot estimate image coordinates, assign an unknown pressure unit, or infer unresolved plot/wellbore identity mappings.

The system is a modular Python application called directly by Streamlit:

1. Safe ingestion validates hashes and archives, then routes supported assets.
2. Native PDF extraction deduplicates overlapping glyphs, detects sections, reconstructs table cells, and normalizes typed values.
3. Independent profile/time digitizers locate axes, segment series, remove legend evidence, calibrate per image, and create overlays.
4. SQLAlchemy persists source facts, provenance, normalized records, candidate anomalies, jobs, mappings, and query audits.
5. Analytics produces deterministic summaries and robust candidate-level trends.
6. Retrieval/chat routes structured, narrative, plot, and hybrid questions while returning citations and limitations.
7. Streamlit exposes review, filtering, mapping validation, and system-health workflows.

SQLite is the zero-configuration path. The schema is PostgreSQL-compatible and managed by Alembic.
