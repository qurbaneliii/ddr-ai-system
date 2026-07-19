# Evaluation

Generated: 2026-07-19T00:43:45.753079+00:00

## Processing outcome

- Statuses: {'complete': 1060}
- Routes: {'digital_pdf': 1000, 'pressure_profile': 30, 'pressure_time': 30}
- Recorded processing duration: 3821.274 seconds
- Failed files: 0

## DDR extraction

- Reports stored: 1000
- Operation rows stored: 10983
- Operation rows marked fail: 480 across 145 PDFs
- Reports with Equipment Failure Information: 148
- Reports with populated equipment failures: 146
- Populated equipment-failure records: 244
- Failure/activity temporal matches: {'exact': 242, 'missing_operation_time': 1, 'unmatched': 1}
- Reports excluded from default trends by automated data-quality rules: 45
- Optional-section table rows stored: 52204
- Optional rows by section: {'bit_record': 344, 'casing_liner_tubing': 865, 'core_information': 15, 'drilling_fluid': 40276, 'equipment_failure_information': 1183, 'gas_reading_information': 1003, 'lithology_information': 797, 'log_information': 269, 'perforation_information': 336, 'pore_pressure': 5286, 'stratigraphic_information': 280, 'survey_station': 1547, 'welltest_information': 3}
- Independent source-text sentinel occurrences: 4025
- Optional-section sentinel cells normalized with raw-value preservation: 3511
- Normalized database sentinel records across overlapping extraction surfaces: 5374

## Pressure profiles

- Images processed: 30
- Measured markers stored: 300
- Per-image axes calibrated: 30/30
- Band classifications: {'above_virgin': 1, 'below_min': 7, 'between_base_max': 150, 'between_min_base': 142}
- Visual anomaly candidates: 8

## Pressure-time plots

- Images processed: 30
- Data points stored after legend exclusion: 709
- Points by displayed series: {'Well_01': 187, 'Well_02': 163, 'Well_03': 177, 'Well_04': 182}
- Per-image axes calibrated: 30/30
- Legend markers excluded: 120
- Images with explicitly unknown pressure unit: 30

## Interpretation boundary

These are extraction and candidate-level analytics measurements, not drilling-engineering validation. SoR is unresolved, pressure-time units remain unknown, automated anomalies are not domain-validated, and no cross-namespace mapping is inferred by matching indices.

The database sentinel-record count can exceed the independent source-text occurrence count because the same source page can be represented in both document-level key/value fields and normalized section tables. It is a record count, not a unique-source-occurrence count.

## Open-ended retrieval evaluation

- Retrieval projection: 18,895 unique chunks from 1,060 source documents.
- Source coverage: 1,000 report summaries, 5,065 narrative sections, 2,594 bounded operation groups, 2,000 extracted-value groups, 7,932 optional-table groups, 244 equipment failures, and 60 deterministic plot-fact chunks.
- Full-corpus cold word-index build observed locally: 5.277 seconds; subsequent questions in the same process were approximately 0.18–0.19 seconds. Character n-grams build lazily only for a relaxed second pass.
- Reproduced pre-fix questions searched only `report_section`; all five broad questions returned a raw top section even when other structured evidence existed. The final full-corpus reproduction returned 10 evidence hits for each broad question and multi-source English evidence; Azerbaijani detection and wellbore follow-up rewriting were correct.
- Deterministic fixtures cover bilingual drilling problems, cementing, circulation losses, stuck pipe, drilling-fluid properties, completed/planned activities, follow-up resolution, absent wells/dates, current oil-price refusal, citation allowlisting, numeric rejection, and structured query-analysis token limits.

The retrieval evaluation measures whether stored DDR evidence is found and correctly bounded. It does not establish engineering completeness beyond the processed corpus.

## Equipment-failure reconciliation

- Reports containing the section heading: 148.
- Reports containing populated rows: 146.
- Populated records: 244.
- Exact same-report temporal matches: 242.
- Unmatched records: 1.
- Records without a valid Operations interval: 1.

The earlier 242/240 hypothesis omitted two distinct source rows on page 2 of `15_9_F_12_2007_06_18.pdf` (`deck cranes` and `cementing unit`). A clean full-corpus reparse retained both records with their different depth/remark evidence and exact same-report drilling matches. The implementation preserves the source-backed 244/242 result rather than deleting valid rows to match the stale hypothesis.
