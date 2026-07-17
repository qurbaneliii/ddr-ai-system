# Extraction Rules

- Use native PDF characters and vector tables first; OCR only when native text signals are insufficient.
- Deduplicate overlapping glyphs by coordinates/font/size before text and table extraction.
- Reconstruct wrapped text only within the same detected cell.
- Parse operational dates from Period start/end and validated filenames, never report creation time.
- Normalize decimal commas only in numeric context and preserve raw strings.
- Convert `-999.99` and `-999.9` to NULL with `source_sentinel`.
- Treat optional section absence as valid.
- Interpret an end time not later than its start as crossing midnight.
- Calibrate each plot independently; do not use a global transform.
- Exclude legend markers dynamically from pressure-time point counts.
- Keep numeric plot values unavailable when tick calibration is not evidenced.

