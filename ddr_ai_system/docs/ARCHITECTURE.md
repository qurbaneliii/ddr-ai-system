# Architecture

The system is a modular Python application called directly by Streamlit:

1. Safe ingestion validates hashes and archives, then routes supported assets.
2. Native PDF extraction deduplicates overlapping glyphs, detects sections, reconstructs table cells, and normalizes typed values.
3. Independent profile/time digitizers locate axes, segment series, remove legend evidence, calibrate per image, and create overlays.
4. SQLAlchemy persists source facts, provenance, normalized records, candidate anomalies, jobs, mappings, and query audits.
5. Analytics produces deterministic summaries and robust candidate-level trends.
6. Retrieval/chat routes structured, narrative, plot, and hybrid questions while returning citations and limitations.
7. Streamlit exposes review, filtering, mapping validation, and system-health workflows.

SQLite is the zero-configuration path. The schema is PostgreSQL-compatible and managed by Alembic.

