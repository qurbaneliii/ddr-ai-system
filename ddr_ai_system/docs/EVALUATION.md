# Evaluation

Generated: 2026-07-17T06:12:29.799192+00:00

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

## Equipment-failure / operational-activity reconciliation

Verified against all cited source PDFs on 2026-07-18:

- Reports containing the section heading: 148 across 9 wellbores.
- Reports containing populated failure rows: 145.
- Populated failure records: 242.
- Exact same-report Operations interval matches: 240.
- Ambiguous or overlap matches: 0.
- Unmatched failures: 1.
- Failures with no valid Operations interval: 1.
- Empty section reports: 3.
- Source citation pages: 133 on page 1 and 15 on page 2.
- Source-PDF citation verification failures: 0 across 148 opened PDFs.

The source data records `00:00` for every failure start and `0` downtime for every populated row. Those values are preserved rather than corrected or inferred. The `Equipment Repaired` column also contains `00:00` throughout this corpus; it is retained as a raw value and is not treated as a validated failure-end timestamp.
