# User guide

Start the app as described in the README. Open **Build & runtime** in the sidebar first: it identifies the build SHA, parser/schema, database/seed/models, and LLM/VLM state. It never shows connection strings or keys.

## Workspaces

- **Overview** shows corpus counts, report coverage, and truthful persistence mode.
- **Report browser** shows source summaries, sections, optional tables, operations, hashes, and page provenance.
- **Activities** shows canonical main/subactivity, duration/state/remark, classification method, confidence, and model version. Existing committed rows should show `source_rule`.
- **Trends & anomalies** contains a cross-day parameter trend and the candidate-review workspace. Parameter trends require one known compatible unit, collapse duplicate dates, and expose exclusions. Candidate filters distinguish detector (`rule`, `data_quality`, `ml`), severity, review status, category, well, and activity.
- **Pressure plots** shows source/overlay images, CV points, calibration, warnings, band candidates, and unknown-unit boundaries.
- **Identity mappings** stores only reviewer-supported namespace links. Matching numbers do not establish identity.
- **Upload & processing** validates and immediately processes PDFs/images/safe ZIPs. SHA duplicates skip re-extraction but refresh their persistent asset record. In PostgreSQL/database-asset mode, files above the persistent limit are rejected before processing.
- **Chat** renders answer type, provider/model, route, evidence source types, citations, limitations, result rows/CSV, trusted SQL, and optional query diagnostics.

## Reviewing an anomaly

1. Open **Trends & anomalies**.
2. Filter detector/status/category as needed.
3. Choose a candidate ID.
4. Expand **Record a domain review**.
5. Select `confirmed`, `rejected`, or `needs_more_evidence`; enter a non-empty reviewer and optional note.
6. Save. The new review appends to history; earlier reviews remain.

An automated candidate is not an incident or recommendation. “Confirmed” means a named reviewer recorded that decision; the committed demo intentionally has no reviews.

## Selected-plot chat

1. Open **Chat**.
2. Choose `No plot selected`, a stored pressure profile, or a pressure-time plot.
3. Review the source/overlay preview, identifier, point count, unit status, warnings, and VLM availability.
4. Ask, for example:
   - `Bu seçilmiş pressure profile qrafikini mənbələrlə izah et.`
   - `Describe the selected pressure-time plot without assuming its pressure unit.`

When VLM is disabled or fails, deterministic plot facts still answer. Unknown pressure units remain unknown. Visual wording must not claim a well mapping, cause, confirmed anomaly, threshold, or recommendation.

## Corpus chat examples

- `15/9-F-14 üçün son DDR-də tamamlanan və planlaşdırılan fəaliyyətləri mənbələrlə izah et.`
- `Qazma zamanı baş verən avadanlıq nasazlıqlarını report və page istinadları ilə göstər.`
- `Which reports mention lost circulation?`
- `Show unusual operation-duration candidates and distinguish rule from ML evidence.`
- `What is the current market price of oil?` — this must return the explicit corpus-boundary refusal.

Chat uses at most four recent messages to resolve follow-ups; prior assistant text is not evidence. Use **Clear chat** to remove conversation state.

## Persistence check

If the sidebar says `temporary SQLite demo`, new uploads can disappear after restart. Durable acceptance requires `persistent PostgreSQL`, a stored asset record with bytes, unique uploaded evidence retrievable before and after restart, and a build SHA matching `main`.
