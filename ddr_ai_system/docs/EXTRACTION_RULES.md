# Extraction Rules

- Use native PDF characters and vector tables first; OCR only when native text signals are insufficient.
- Deduplicate overlapping glyphs by coordinates/font/size before text and table extraction.
- Reconstruct wrapped text only within the same detected cell.
- Parse operational dates from Period start/end and validated filenames, never report creation time.
- Normalize decimal commas only in numeric context and preserve raw strings.
- Convert `-999.99` and `-999.9` to NULL with `source_sentinel`.
- Treat optional section absence as valid.
- Interpret an end time earlier than its start as crossing midnight; preserve equal clocks as temporally ambiguous.
- Treat an Equipment Failure Information heading without a populated, signature-matched table row as an empty section, not a failure record.
- Match failures to Operations within the same report only. Prefer a unique containing interval, preserve multiple overlaps as ambiguous, and never choose a nearest row unless an explicit tolerance is configured.
- Preserve the source `Equipment Repaired` value without treating it as a failure end time when its semantics are not established.
- Calibrate each plot independently; do not use a global transform.
- Exclude legend markers dynamically from pressure-time point counts.
- Keep numeric plot values unavailable when tick calibration is not evidenced.
