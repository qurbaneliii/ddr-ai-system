# User Guide

## Chatbot provider and language

Open **Chatbot** and select **Auto**, **Azərbaycan dili**, or **English**. The status panel shows one truthful active provider label: **Ollama Local LLM**, **Ollama Remote**, or **Lexical fallback**. It also shows the model, connection state, query route, English retrieval representation, evidence, read-only SQL, confidence, limitations, and any fallback reason.

The model is called only after submitting a new question. Ordinary Streamlit reruns, page navigation, and viewing earlier messages do not generate another answer. Chat messages remain in the current Streamlit session. In fallback mode, answers and evidence tables remain functional and are explicitly marked deterministic/not LLM-generated.

For equipment failure analysis, ask:

> Hansı quyularda avadanlıq nasazlığı baş verib və nasazlıq zamanı hansı əməliyyat aparılırdı? Tarixləri və mənbələri də göstər.

The result includes the wellbore, report date, raw failure time, failed equipment/system, downtime, temporally matched main/sub activity and interval, match status/confidence, source PDF, failure page, and Operations page. Ambiguous or unmatched rows retain an unresolved activity instead of an invented one.

See `OLLAMA.md` for native, Compose, remote, and Streamlit Community Cloud behavior.

Run the bootstrap, migration, audit, processing, and evaluation commands in the README. Then start Streamlit. The sidebar reports the active database and parser version. An empty database is supported and displays exact ingestion instructions.

Review candidate anomalies by opening their evidence records and overlays. Do not treat them as confirmed operational anomalies until a qualified reviewer marks them validated. Create identity mappings only when an authoritative manifest or reviewed evidence exists; record the source and validator.
