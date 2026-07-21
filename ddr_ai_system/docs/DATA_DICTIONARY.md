# Data dictionary

- `source_documents`: content SHA-256, portable/source path, media type, native/scanned/hybrid/plot route, byte/page counts, parser version, processing status, sanitized error, metadata, warnings, and timestamps.
- `stored_assets`: one bounded asset record per source document; SHA-256, filename, MIME, byte size, backend/key/status, optional persistent bytes, and timestamps. Stored bytes must match source metadata.
- `processing_jobs`: processing type/status/version, duration, warning/error codes, sanitized messages, and timestamps.
- `pages`: page dimensions, native/deduplicated character counts, extracted text, table count, extraction method (`native_pdf` or `ocr`), confidence, and optional overlay.
- `reports`: source identity, wellbore/filename identity, reporting period, spud/status/report number, completed/planned summaries, identity/date checks, confidence, data-quality status, and trend exclusion.
- `report_sections`: typed section, raw heading, page, text, row count, bounding box, and confidence.
- `operations`: raw and canonical main/subactivity, source clocks and resolved datetimes, duration/depth/state/remark, temporal ambiguity, raw/normalized values, bounding box/confidence, plus classification method/confidence/model/evidence.
- `equipment_failures`: populated failure-table rows with source/report/section/page/table provenance, clocks/datetimes, depths, equipment/system, downtime, repair/remark, temporal status, raw/normalized values, bounding box/confidence, and review status.
- `failure_operation_matches`: same-report temporal relationship, rule/status/confidence, evidence IDs, optional time delta, and validation state.
- `extracted_values`: raw/normalized text or number, raw/normalized unit, missing reason, section/page/bbox provenance, confidence, source origin, and validation.
- `section_table_rows`: optional-section headers/raw cells/normalized cells, source/report/section/page/table/row/bbox provenance, confidence, and validation.
- `plots`: plot identity/type, dimensions/bbox, axes/units/unit status, deterministic calibration, confidence, overlay path, and warnings.
- `plot_points`: pixel and calibrated coordinates, series/date, reference values, band classification, candidate flag, confidence, and source bbox.
- `anomalies`: source record, category, rule/model, detector type, model version, stable candidate key, evidence/score/severity/confidence/threshold, validation status, domain-validation flag, and candidate-level explanation.
- `anomaly_reviews`: append-only anomaly decision, reviewer, optional note, and timestamp. Multiple records preserve history.
- `model_runs`: model type/version, artifact and training fingerprints, parameters, actual metrics, creation time, and active flag.
- `retrieval_chunks`: deterministic chunk key/type/source IDs, well/date/page/section, bounded searchable text, metadata, content hash, and timestamps. Only human-confirmed anomalies enter validated-anomaly chunks.
- `identity_mappings`: source/target namespaces and identifiers, mapping status/source/evidence/confidence, validation state, reviewer, notes, and timestamp.
- `seed_versions`: production seed version, source fingerprint, and application timestamp.
- `query_audit`: question hash, route, generated trusted SQL when applicable, status/row count/duration, and sanitized error code; raw question text is not stored.

## Invariants

- Raw activity labels and source values are preserved.
- `-999.99`/`-999.9` normalize to null with `source_sentinel` reason.
- Unknown units remain unknown and are not mixed in trends.
- Rule/data-quality/ML detector types remain distinguishable.
- `domain_validated=false` is the default; no reviewer identity is fabricated.
- Candidate keys, source hashes, asset keys, chunk keys, and seed versions enforce idempotency at their respective boundaries.
