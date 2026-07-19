# User guide

Start the app with the commands in the README. The sidebar exposes eight focused workspaces:

- **Overview** shows corpus metrics and report coverage. A failed metric is isolated instead of crashing the page.
- **Report browser** shows stored text, sections, tables, operations, hashes, and page provenance.
- **Activities** filters normalized operational rows and durations.
- **Trends & anomalies** visualizes automated candidates and labels them as requiring domain review.
- **Pressure plots** displays tracked source/overlay images, measured points, bands, calibration, warnings, and unknown-unit boundaries.
- **Identity mappings** stores only reviewer-supported links between namespaces.
- **Upload & processing** validates and processes selected files in one submission. A SHA-256 duplicate is skipped. SQLite mode warns that new data is temporary. PostgreSQL preserves extracted records; the page separately states whether raw source bytes are metadata-only or stored through the explicitly enabled bounded backend.
- **Chat** answers only from processed DDR facts. It exposes answer type, route, source types, hit count, corpus/index status, citations, limitations, result rows/CSV, trusted read-only SQL, and an optional query-interpretation debug panel. Provider status distinguishes OpenAI-verbalized, deterministic structured, lexical corpus retrieval, and not-found results.

Useful open-ended examples include:

- “What drilling problems were reported across the corpus?”
- “Which reports mention cementing operations?”
- “What drilling-fluid properties are available?”
- “Bu DDR-lərdə əsas qazma fəaliyyətləri hansılardır?”
- “15/9-F-14 üçün tamamlanan və planlaşdırılan fəaliyyətlər nə idi?” followed by “Bunlardan ən sonuncusu hansı tarixdə olub?”

Chat uses at most four recent messages to resolve references; prior chat text is not factual evidence. Use **Clear chat** to remove the visible conversation. If both retrieval stages find nothing, the app says that the answer was not found in the processed corpus and suggests related corpus questions. It will not answer current prices, news, or general drilling facts from model knowledge.

Use Auto, Azerbaijani, or English for answers. If a fact, unit, or identity is absent, the safe answer is unresolved—not an inference. Treat every automated anomaly or pressure-band flag as a candidate until a qualified reviewer validates it.
