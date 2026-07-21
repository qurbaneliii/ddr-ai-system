# Task compliance

Status is evidence-scoped. “Implemented” is not used as a synonym for live-verified.

| Requirement | Implementation and evidence | Status |
|---|---|---|
| Native DDR processing | All-page routing, native text/tables, sections, operations, failures, fields, provenance; 1,000 committed reports | Complete for committed native corpus |
| Scanned DDR processing | Tesseract token/bbox contract, preprocessing, focused table reconstruction, safe missing-runtime behavior, evaluator/manifest | Partially complete — blocker: no genuine scanned DDR benchmark; three-page surrogate missed identity and structured-row targets |
| Hybrid PDFs | Per-page native/OCR decisions, unified merge, injected-OCR hybrid integration and persistence tests | Complete in code/local tests; genuine hybrid field benchmark unavailable |
| Canonical activity taxonomy | Seven main classes, explicit subactivity vocabulary/aliases, raw preservation, idempotent backfill, affected-chunk rebuild | Complete |
| Real NLP activity model | Word+character TF-IDF, class-weighted LogisticRegression, report-grouped split, source/rule/ML precedence, SHA-verified artifact | Complete locally: main macro F1 0.7064 and sub macro F1 0.5100, both above baselines |
| Rule and ML anomaly candidates | Original 1,291 candidates preserved; 191 IsolationForest duration candidates added with stable keys/model provenance | Complete at candidate level; no precision/recall claim without reviews |
| Human/domain validation | Append-only reviews, three decisions, filters, history, reconnect test | Complete in code/local tests; zero real reviews and live restart verification pending |
| Daily summaries | Stored report/operation/failure facts, completed/planned source text, citations and limitations | Complete |
| Cross-day parameter trends | Known-compatible units only, invalid/date/quality exclusion, duplicate-date median, Theil-Sen/Spearman, UI chart | Complete locally; descriptive only |
| Grounded English/Azerbaijani RAG | Typed planning, handlers, two-stage retrieval, follow-up rewrite, citation/numeric/unit checks, explicit corpus refusal | Complete locally: fixed deterministic set 13/13 |
| Current-price/news refusal | Order-independent market-price boundary plus not-found corpus response | Complete locally |
| Selected pressure-plot VLM | Selector/preview, secure stored-image context, deterministic facts, one image call, claim rejection, provider-error fallback | Implemented and mocked locally — blocker: authorized public VLM credential/live call unavailable |
| One-action Streamlit uploads | Size/name/ZIP/hash validation and automatic `process_file()` dispatch | Complete locally |
| Central PostgreSQL | One resolved URL, Alembic `0006`, explicit seed, non-empty refusal, sequence repair, reconnect integration test | Implemented — blocker: authorized production `DDR_DATABASE_URL` and live seed/upload/restart proof unavailable |
| Restart-persistent asset bytes | Default bounded database backend, pre-processing oversize rejection, hash/size/MIME validation, reconnect load | Complete locally/CI path; live proof shares PostgreSQL blocker |
| Activity/anomaly visualization | Classification method/confidence/model columns; rule/ML/status/category filters; review form/history | Complete locally; final public rendering pending redeploy |
| Build/deployment identity | Sidebar package/parser/schema/SHA/database/seed/model/provider/VLM state; safe SHA resolution | Complete in code; public SHA parity pending redeploy |
| Public Streamlit application | Existing public URL serves the prior demo | Partially complete — blocker: final `main` SHA, PostgreSQL mode, VLM state, and restart behavior not yet live-verified |
| Security and CI | Controlled model path/hash, SQL/ZIP limits, selected-image only, safe errors, hygiene scan, PostgreSQL CI service | Complete locally; final remote CI run pending push |

## Exact remaining external gates

1. **Genuine scans:** provide at least three authorized scanned-origin DDRs and human annotations for at least ten representative pages through the secure input channel; run `evaluate_ocr.py --mode real`.
2. **Production PostgreSQL:** configure `DDR_DATABASE_URL`, `DDR_ASSET_STORAGE_BACKEND=database`, asset limit, and build SHA in Streamlit Secrets; seed only an empty target; upload/search/restart/search one small DDR.
3. **Public VLM:** configure an authorized OpenAI key and `OPENAI_VLM_ENABLED=true` in Streamlit Secrets; select each plot type and verify accepted/fallback behavior without exposing the key.
4. **Deployment parity:** redeploy merged `main` and confirm the visible SHA, schema `0006`, database mode, and provider/model match the release.

Until those gates pass, final assignment status is **Partially complete**.
