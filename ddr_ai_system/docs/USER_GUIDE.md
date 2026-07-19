# User guide

Start the app with the commands in the README. The sidebar exposes eight focused workspaces:

- **Overview** shows corpus metrics and report coverage. A failed metric is isolated instead of crashing the page.
- **Report browser** shows stored text, sections, tables, operations, hashes, and page provenance.
- **Activities** filters normalized operational rows and durations.
- **Trends & anomalies** visualizes automated candidates and labels them as requiring domain review.
- **Pressure plots** displays tracked source/overlay images, measured points, bands, calibration, warnings, and unknown-unit boundaries.
- **Identity mappings** stores only reviewer-supported links between namespaces.
- **Upload & processing** validates and processes selected files in one submission. A SHA-256 duplicate is skipped. SQLite mode warns that new data is temporary; PostgreSQL mode persists extracted records.
- **Chat** answers from stored facts, exposes result rows/CSV, citations, limitations, and generated read-only SQL. Provider status distinguishes optional OpenAI verbalization from lexical fallback.

Use Auto, Azerbaijani, or English for answers. If a fact, unit, or identity is absent, the safe answer is unresolved—not an inference. Treat every automated anomaly or pressure-band flag as a candidate until a qualified reviewer validates it.
