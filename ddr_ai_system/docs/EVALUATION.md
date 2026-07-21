# Evaluation

Generated evidence: 2026-07-21. Machine-readable results are under `data/processed/evaluations/`.

## Corpus and database

- Alembic revision: `0006`
- Source documents/reports/operations: 1,060 / 1,000 / 10,983
- Plots/points: 60 / 1,009
- Retrieval chunks: 18,895
- Classification methods: 10,983 `source_rule`
- Canonical main distribution: completion 647; drilling 5,206; formation evaluation 620; interruption 1,940; moving 127; plug/abandon 1,634; workover 809
- Candidate anomalies: 1,482 total = 45 data-quality + 1,246 rule + 191 ML
- Human reviews/domain-validated candidates: 0 / 0
- Stored assets in committed demo snapshot: 0 (new accepted uploads create records)
- SQLite integrity/quick check: `ok` / `ok`; foreign-key violations: 0; journal mode: `delete`

## OCR benchmark

No genuine scanned-origin DDR exists in either authorized task-input location. The committed 1,000 PDFs all contain native text. Tesseract is installed in Cloud/Docker packaging but the local Windows Tesseract executable was unavailable.

The recorded run is therefore explicitly **surrogate**, using three representative native pages rasterized to image-only PDFs and RapidOCR at 150 DPI. Ground truth came from native extraction, not human annotation.

| Metric | Actual | Predeclared target | Pass |
|---|---:|---:|---|
| Routing accuracy | 1.0000 | ≥ 0.90 | Yes |
| Page-method accuracy | 1.0000 | ≥ 0.90 | Yes |
| Token precision / recall / F1 | 0.8917 / 0.7930 / 0.8394 | F1 ≥ 0.75 | Yes |
| Word error rate | 0.2449 | ≤ 0.25 | Yes |
| Wellbore exact match | 0.0000 | ≥ 0.80 | No |
| Date exact match | 0.0000 | ≥ 0.80 | No |
| Section recall | 0.7833 | ≥ 0.75 | Yes |
| Operation-row recall | 0.1580 | ≥ 0.70 | No |
| Equipment-failure-row recall | 0.0000 on one supported page | ≥ 0.60 | No |
| Selected table-cell accuracy | 0.0957 | ≥ 0.70 | No |
| Numeric exact match | 0.0000 | ≥ 0.75 | No |
| Mean confidence | 0.9642 | descriptive | — |
| Mean latency | 34.07 s/page | descriptive | — |
| Failure rate | 0.0000 | ≤ 0.10 | Yes |

These misses are not hidden: code/table contracts pass deterministic tests, but real scanned structured extraction is not validated and the surrogate structured targets failed. The blank manifest is ready at `data/evaluation/ocr_manifest.csv` with source identity, page, expected sections/rows/cells/numerics, annotation source, and transcript path.

## Activity classifier

- Source rows: 10,983; deduplicated remark samples: 10,654
- Inputs: operation remark only; source target columns are never features
- Split: deterministic report-grouped holdout with zero report overlap
- Features: word TF-IDF (1–2 grams) + character `char_wb` TF-IDF (3–5 grams)
- Estimator: class-weighted LogisticRegression, random state 42
- Main train/test: 8,523 / 2,131; seven canonical classes
- Subactivity eligible/train/test: 10,592 / 8,472 / 2,120; minimum support 20; rare source labels remain source-only
- Artifact SHA-256: `83a165342a245392499f8da44ca588d4e8fcb8121764d291cc963cc8ce8cdcf5`

| Target | Accuracy | Macro F1 | Weighted F1 | Keyword-baseline macro F1 |
|---|---:|---:|---:|---:|
| Main activity | 0.7091 | 0.7064 | 0.7138 | 0.1069 |
| Subactivity | 0.5307 | 0.5100 | 0.5292 | 0.1423 |

The promoted model is a future fallback/shadow evaluator. It does not overwrite valid source labels, and metrics are not domain validation.

## Anomaly model

- Model: deterministic `IsolationForest`, 200 trees, random state 42
- Feature: duration within supported canonical main/subactivity group; small groups fall back only to supported main activity
- Candidate gate: model outlier and absolute robust z-score ≥ 3.5
- Eligible operations: 10,916
- Candidates: 191 (1.7497%); overlap with existing rule candidates: 17
- By main activity: completion 13; drilling 81; formation evaluation 14; interruption 36; moving 3; plug/abandon 30; workover 14
- Idempotent dry/apply/repeat generated the same 191 stable keys

Without reviewed labels, precision, recall, causality, and engineering significance are unknown. The model does not use `state=fail` as a target.

## Deterministic RAG/chat evaluation

The fixed 13-case set covers activity, equipment failures, drilling-fluid evidence, daily summaries, a multi-day plot trend, Azerbaijani, follow-up rewrite, missing well/date, current market-price refusal, plot facts, rule-vs-ML candidate wording, and validated-anomaly wording.

- Passed: 13/13
- Cases with evidence: 9
- Citation filename validity: 100%
- Mean/median/max latency: 0.749 / 0.045 / 8.818 seconds
- External model calls: 0

This verifies deterministic planning, handlers, lexical retrieval, and grounding contracts; it does not measure live OpenAI prose quality.

## VLM acceptance

Automated tests use no real OpenAI request. They verify one selected-image call, accepted qualitative visual wording, rejection of invented `500 PSI`/confirmed-anomaly claims, invalid citation/numeric/unit rejection, lexical fallback, and provider-error fallback. A public authorized VLM call remains externally blocked.

## Quality gates

- Pytest: 137 passed, 1 skipped. The skip explicitly requires a dedicated local PostgreSQL URL; CI configures and must execute it.
- Ruff: passed.
- Mypy: passed across 61 source files.
- Compileall: passed for source, entrypoint, and scripts.
- Model artifact SHA: verified.
- Compose configuration: passed.
- Docker runtime: unavailable locally because the Docker Desktop Linux engine pipe was absent.
- SQLite integrity/quick/FK/revision: `ok` / `ok` / 0 / `0006`.

Remote CI and final public-browser results must be recorded only after the branch is pushed/merged/redeployed.
