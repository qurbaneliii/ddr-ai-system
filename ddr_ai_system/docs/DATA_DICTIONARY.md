# Data Dictionary

- `source_documents`: immutable source identity, SHA-256, routing, parser version, status, and warnings.
- `processing_jobs`: resumable job history, duration, warnings, and sanitized failures.
- `pages`: page dimensions, text, character-deduplication counts, method, and confidence.
- `reports`: wellbore/period identity, summaries, date validation, confidence, and default-trend exclusion.
- `report_sections`: meaningful report/section chunks with page provenance.
- `operations`: normalized activities, durations, depths, states, remarks, and row provenance.
- `extracted_values`: raw and normalized values, missing reasons, units, provenance, origin, and validation.
- `section_table_rows`: optional-section table rows with raw cells, normalized numeric/sentinel cells, page/table coordinates, confidence, and review status.
- `plots` / `plot_points`: per-image calibration, overlays, pixel/numeric values, band classification, confidence, and units.
- `identity_mappings`: namespace-to-namespace mapping status, evidence, confidence, validator, and notes.
- `anomalies`: candidate category/rule/evidence/score/severity/configuration and human/domain validation state.
- `query_audit`: privacy-preserving question hash, route, SQL, outcome, and duration.
