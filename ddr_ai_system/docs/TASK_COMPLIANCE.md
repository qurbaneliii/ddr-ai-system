# Original task compliance matrix

| Requirement | Implementation | Verification evidence | Status |
|---|---|---|---|
| Automatic DDR reading | Content-addressed upload and batch processor | Native and OCR route tests; 1,000 stored reports | Complete |
| Sections, tables, text, numeric values | Native parser, section/table normalization, raw plus normalized values | Parser tests and committed database | Complete |
| Digital PDF plus scanned OCR | `pdfplumber` native route; PyMuPDF plus Tesseract backend | Digital fixture and generated image-only PDF tests | Complete |
| Pressure profile/time processing | Deterministic OpenCV digitizers and portable source/overlay assets | 60 plots, 1,009 points, plot tests and UI | Complete |
| Structured SQL storage | SQLAlchemy models and Alembic head `0005` | Integrity, FK, migration, and count tests | Complete |
| Events, summaries, trends, candidates | Normalizers, daily summaries, robust trend facts and candidate rules | Analytics tests and Streamlit pages | Complete |
| Retrieval chatbot | Typed query plans, trusted handlers, seven-source chunks, two-stage TF-IDF retrieval, evidence packs and follow-ups | Deterministic English/Azerbaijani fixtures plus 18,895-chunk corpus reproduction | Complete for processed-corpus questions; corpus-only boundary applies |
| Optional grounded LLM | OpenAI Responses provider with safe fallback and claim validation | Mocked failure/success/image tests plus live English and Azerbaijani `gpt-5.6-luna` responses | Complete and live-verified |
| Plot explanation | Stored point/band/trend facts plus optional selected-image method | Plot acceptance questions and deterministic citations | Complete |
| One-action upload | Single form submission with size/type/ZIP/hash checks | Streamlit component and processor tests | Complete |
| Central persistent uploads | Explicit PostgreSQL URL, versioned non-overwriting seed, retrieval chunks, reconnect test | SQLite seed tests; dedicated CI PostgreSQL full-seed/idempotency/sequence/upload/reconnect test | Implemented and CI-verifiable; live persistence needs production credential |
| Uploaded source-byte persistence | Metadata/status for every new upload; optional bounded database bytes | Bounded, oversized, and idempotent asset tests | Extracted records persist in PostgreSQL; raw bytes require explicit backend/object storage |
| Truthful local fallback | Validated content-addressed SQLite snapshot and temporary-upload warning | Snapshot tests and UI smoke tests | Complete |
| Streamlit deployment | Eight-page app, safe metrics, portable images | Public metrics, report browser, both plot image/overlay tabs, upload warning, and chat verified on 2026-07-19 | Complete |
| Safety and hygiene | Secret boundaries, sanitized errors, SQL/ZIP limits, ignore rules | CI hygiene and negative tests | Complete |

“Complete” for retrieval means questions answerable from the processed corpus, not all oil-industry knowledge. Current prices, news, absent wells/dates, unknown units, unresolved mappings, and unsupported engineering conclusions remain explicit negative outcomes. Final live production-persistence compliance remains blocked until an authorized PostgreSQL `DDR_DATABASE_URL` is configured, seeded exactly once, and upload/restart-tested; the live app must continue to report its actual mode.
