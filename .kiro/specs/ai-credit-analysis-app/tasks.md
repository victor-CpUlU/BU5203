# Implementation Plan: AI-Assisted Credit Analysis App

## Overview

The plan builds the Python (FastAPI) backend and vanilla-JS frontend from the design in incremental, test-backed steps. It starts with the scaffold, the rewritten `Instructions.md` and the versioned prompt files. Next come the pure core (CSV/values/anomalies/comparisons, Number_Verifier, Reference_Validator, passage normalisation), the intake, document and financial APIs (the first usable slice: create a Deal, upload PDFs, load the CSV, view dashboard data), the LLM runner, and Sections 2-6. PDF exports, the static frontend, the `start.bat` launcher and an end-to-end integration test follow. Every step wires into the app built so far, so no code is left orphaned.

Language: Python 3.11+ (backend, tests, launcher tools) and vanilla JavaScript ES modules (frontend), as specified in the design.

## Tasks

- [ ] 1. Project scaffold and settings
  - [ ] 1.1 Create project scaffold and test harness
    - Create `requirements.txt` with exact `==` pins (fastapi, uvicorn, pydantic, pydantic-settings, python-multipart, pandas, PyMuPDF, httpx, reportlab, pytest, hypothesis)
    - Create `.env.example` (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `SUPPORT_CHECK_ENABLED=false`, `PORT=8000`, optional `FINANCIAL_DB_PATH`) with no real key
    - Create `.gitignore` excluding `.env`, `.venv/`, `data/`
    - Create `config/analysis.toml` with upload/CSV limits, page_limit, llm_timeout_s, llm_max_retries, `[large_swing]`, `[stable_band]` and `[keywords] business/debt` lists
    - Create the `backend/app/` package tree (api, models, storage, documents, financial, llm, sections, verification, review, export, security, prompts) and `backend/tests/` (unit, property, golden, integration)
    - Add `pytest.ini` / `pyproject` test config so a single `pytest` from the project root runs everything; add `backend/tests/conftest.py` with a hypothesis profile (`max_examples=100`, `deadline=None`) and an autouse fixture that blocks non-loopback socket connections
    - _Requirements: 26.1, 26.3, 27.3, 27.7, 29.3, 29.10_

  - [ ] 1.2 Implement `backend/app/settings.py`
    - Load `.env` via pydantic-settings and `config/analysis.toml` via `tomllib`
    - `resolve_thresholds(raw)` (invalid when missing, non-numeric or ≤ 0) and `resolve_stable_bands(raw)` (invalid when missing, non-numeric or negative), each returning values plus the list of unit types defaulted
    - `llm_settings_problems()` returning names of missing/invalid settings, never values; fixed host `127.0.0.1`; Financial_Database path resolution (configured path relative to project folder, else `intel_quarterly_ratios.csv`)
    - _Requirements: 8.1, 10.8, 12.4, 12.9, 25.1, 25.8, 27.4, 27.5_

  - [ ]* 1.3 Write property test for threshold and Stable_Band fallback
    - **Property 22: Invalid thresholds and bands fall back to defaults**
    - **Validates: Requirements 10.8, 12.9**

  - [ ]* 1.4 Write unit tests for settings
    - Defaults per unit type, host fixed to 127.0.0.1, `llm_settings_problems` never returns the key value, CSV path resolution
    - _Requirements: 8.1, 12.4, 25.8, 27.5_

- [ ] 2. Instructions.md rewrite and versioned prompts
  - [ ] 2.1 Rewrite `Instructions.md`
    - Follow the C1 outline: Sections 1-6 pipeline (Section 6 produces Credit Memo PDF + Audit Trail PDF via PDF_Renderer), runtime constraints, local/no-auth statement, data conventions (three Evidence_ID formats with examples, vocabularies, ten Canonical_Metrics in order, five Anomaly_Flag triggers with thresholds, Stable_Band defaults, CSV-only financial data rule, zero is a real value with a flag), Section 6 verification in the Frontend with Support_Checker advisory only
    - Master System Prompt with rules (a)-(h); six runtime prompts S2A, S2B, S3, S4, S5, S6 each with Prompt ID, Version, fenced `text` block containing `{{INPUT_JSON}}`, and a JSON output schema table (field, type, required) matching `llm_schemas.py`
    - Remove all "Layer 2"-"Layer 7" references, credit-engine formulas, derived-figure rules, recommendation, blind-spot and sign-off content
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.9, 1.11_

  - [ ] 2.2 Create prompt files and `tools/sync_prompts.py`
    - `tools/sync_prompts.py` extracts the master and six prompt blocks from `Instructions.md` into `backend/app/prompts/{master_system,s2a_business,s2b_debt,s3_trend,s4_risks,s5_memo,s6_support}.md` using the `version: <id>` + `---` header format
    - Run it once to generate the seven prompt files
    - _Requirements: 1.8_

  - [ ] 2.3 Implement prompt loader `backend/app/llm/prompts.py`
    - `PromptFile` dataclass, `load_prompts(folder)` raising `PromptLoadError(prompt_id, reason)` for missing, unreadable or version-less files, `extract_instruction_prompts(md_text)`
    - _Requirements: 1.8, 1.10_

  - [ ]* 2.4 Write prompt and Instructions.md tests
    - `test_prompt_sync.py`: version and text equality (line endings normalised) between each prompt file and `Instructions.md`
    - Missing / no-version prompt file raises `PromptLoadError` naming the prompt
    - Smoke checks: six sections in order, no "Layer 2"-"Layer 7", rules (a)-(h) present, six prompt IDs with versions, no recommendation / blind-spot fields, S5 requires 7 sections
    - _Requirements: 1.1, 1.2, 1.3, 1.6, 1.8, 1.10_

- [ ] 3. Data models, storage, redaction and audit trail
  - [ ] 3.1 Create core Pydantic models in `backend/app/models/`
    - `deal.py`, `document.py`, `evidence.py`, `financial.py`, `review.py`, `audit.py` per the design (Literals for UnitType, StatementLabel, VerificationStatus, Direction, AnomalyFlag; Deal, Document, PageText, DocEvidence, CsvEvidence, DatasetEntry, ComparisonRecord, FinancialDataset, ParsedCell, Period, LoadResult, DivergenceResult, LocateResult, VerifyResult, RefResult, SectionState, ExtractionField, S3ReviewItem, MemoStatement, Comment, SupportResult, AuditEntry, TaskResult); Decimals serialised as strings
    - _Requirements: 7.1, 8.7, 9.4, 9.8, 10.6, 12.1, 15.5, 22.2_

  - [ ] 3.2 Create LLM output schemas `backend/app/models/llm_schemas.py`
    - S2A/S2B (all field keys required), S3 (statements, comparison claims, divergences), S4 (≤ 5 risks, terms), S5 (7 sections), S6 assessments; all `extra="forbid"`; no recommendation, decision or blind-spot field
    - _Requirements: 1.3, 5.1, 6.1, 14.8, 17.2, 17.6, 18.2, 21.2, 25.3_

  - [ ] 3.3 Implement `backend/app/storage/repository.py`
    - `DealRepository` rooted at `data/` inside the project folder (overridable for tests), `deal_id = uuid4().hex[:12]`, per-Deal `threading.Lock`, atomic `write_json` (temp + `os.replace`), `read_json`, file paths per storage layout; run text through the Redactor before writes
    - _Requirements: 27.1, 27.9_

  - [ ] 3.4 Implement `backend/app/security/redact.py`
    - `redact(text, secrets)` masking every span covered by any 8-character window of a key; logging filter for all handlers
    - _Requirements: 27.8, 27.9_

  - [ ] 3.5 Implement append-only `backend/app/review/audit_trail.py`
    - `create(deal_id)`, `append(deal_id, entry)` with strictly increasing `seq`, temp-write + fsync + `os.replace`, local timestamps with UTC offset to the second; raises on write failure so callers can apply audit-first ordering
    - _Requirements: 22.1, 22.5, 22.8_

  - [ ]* 3.6 Write property test for redaction
    - **Property 54: Redaction removes every 8-character window of a key**
    - **Validates: Requirements 27.8, 27.9**

  - [ ]* 3.7 Write property test for the audit trail
    - **Property 50: Audit trail is append-only**
    - **Validates: Requirements 22.5**

  - [ ]* 3.8 Write schema tests for S2A, S2B, S3, S4, S5, S6
    - One valid sample passes; each required key removed in turn is rejected (parametrised); out-of-vocabulary values rejected
    - _Requirements: 29.9, 25.3_

  - [ ]* 3.9 Write unit tests for the repository
    - Atomic write leaves prior file intact on failure; all paths stay under the data folder
    - _Requirements: 27.1_

- [ ] 4. Checkpoint - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Financial core (CSV_Loader, values, anomalies, comparisons)
  - [ ] 5.1 Implement `backend/app/financial/values.py`
    - `parse_cell(text, metric_key)` for percent / multiple / days (DSO) / amount with Decimal value and decimal count; unparseable → null, "Not available in database", flag "unparseable value"
    - `format_value(value, unit_type, decimals)`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.8_

  - [ ]* 5.2 Write property test for cell round trip
    - **Property 19: Cell parse and format round trip**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.6, 9.7, 9.8**

  - [ ] 5.3 Implement `backend/app/financial/anomalies.py`
    - `FLAG_ORDER`, `flags_for_series(...)` for zero, negative (not REVENUE_GROWTH), large swing (later period only, amount relative rule incl. zero-then-non-zero), unit not stated (every amount value, one gap per metric); values never altered
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [ ]* 5.4 Write property test for anomaly flags
    - **Property 21: Anomaly flags match the trigger oracle**
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6**

  - [ ] 5.5 Implement `backend/app/financial/comparisons.py` and `trends.py`
    - `build_comparisons`, `raw_change`, `direction`, `change_display` (ROUND_HALF_UP, signed, pp / x / days / %; "Not computable"), unrounded change stored as string; adjacent non-null pairs only, QoQ
    - `sustained_label(metric_key, comparisons)`
    - _Requirements: 12.1, 12.2, 12.3, 12.5, 12.6, 12.7, 12.8, 14.2_

  - [ ]* 5.6 Write property test for comparison pairing
    - **Property 23: Comparison_Records are exactly the adjacent non-null pairs**
    - **Validates: Requirements 12.1, 12.5, 12.7**

  - [ ]* 5.7 Write property test for change computation
    - **Property 24: Change is recomputable and displayed correctly**
    - **Validates: Requirements 12.2, 12.6, 12.8**

  - [ ]* 5.8 Write property test for direction
    - **Property 25: Direction follows the Stable_Band**
    - **Validates: Requirements 12.3, 12.8**

  - [ ]* 5.9 Write property test for sustained labels
    - **Property 28: Sustained labels require two matching directions**
    - **Validates: Requirements 14.2**

  - [ ] 5.10 Implement `backend/app/financial/unavailable.py` and `divergence.py`
    - Fixed `UNAVAILABLE_METRICS` with panel assignment, `unavailable_payload()` returning `{"metric", "value": "Not available in database"}` items, missing-Canonical_Metric handling
    - Patterns P1-P5 and `divergence_assessability(metric_keys)` with exact-name matching and no substitution
    - _Requirements: 11.1, 11.3, 13.4, 14.3, 14.4_

  - [ ]* 5.11 Write property test for divergence assessability
    - **Property 29: Divergence assessability without substitution**
    - **Validates: Requirements 14.3, 14.4**

  - [ ] 5.12 Implement `backend/app/financial/csv_loader.py`
    - `LABEL_MAP`, `map_label`, `unrecognised_key`, `parse_period_header` (real-date check), `load_csv(path, borrower, confirm_whole_file, settings)`
    - `pd.read_csv(dtype=str, keep_default_na=False)`; structural checks; Borrower column filter or `needs_confirmation` + gap "Database has no borrower identifier"; duplicate metric/period checks; parse cells → anomaly flags → comparisons → divergence → CSV Evidence_Records; any abort returns error and writes nothing
    - _Requirements: 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12, 8.13, 9.5, 10.6, 11.3, 12.1_

  - [ ]* 5.13 Write property test for metric label mapping
    - **Property 14: Metric label mapping**
    - **Validates: Requirements 8.4, 8.10**

  - [ ]* 5.14 Write property test for period headers
    - **Property 15: Period header round trip**
    - **Validates: Requirements 8.5, 8.11**

  - [ ]* 5.15 Write property test for dataset structure
    - **Property 16: Loaded dataset structure**
    - **Validates: Requirements 8.3, 8.6, 8.7**

  - [ ]* 5.16 Write property test for the borrower filter
    - **Property 17: Borrower filter**
    - **Validates: Requirements 8.8**

  - [ ]* 5.17 Write property test for missing canonical rows
    - **Property 18: Missing canonical rows become Unavailable_Metrics**
    - **Validates: Requirements 11.3**

  - [ ]* 5.18 Write property test for unparseable cells
    - **Property 20: Unparseable cells degrade without aborting**
    - **Validates: Requirements 9.5**

  - [ ] 5.19 Implement `backend/app/financial/dashboard.py`
    - Build five panels with series (display + flags per period, null → no point), latest value and latest Comparison_Record per metric or "No comparison available", per-panel "Not available in database" list, data-table rows
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.7, 11.4_

  - [ ]* 5.20 Write property test for dashboard latest values
    - **Property 26: Dashboard latest values and unavailable lists**
    - **Validates: Requirements 13.3, 13.4**

  - [ ]* 5.21 Write CSV_Loader unit, anomaly and golden tests
    - Req 29.1 examples; Req 29.4 Intel anomalies plus at-threshold boundary; `tests/golden/test_intel_csv.py` per Req 29.2 (10 metrics, 4 periods in order, 40 display values, Evidence_IDs, 30 Comparison_Records, C8 anomaly set, five divergences not assessable, borrower-identifier gap)
    - _Requirements: 29.1, 29.2, 29.4_

- [ ] 6. Verification core (Number_Verifier, Reference_Validator)
  - [ ] 6.1 Implement `verification/text_rules.py` and figure extraction in `verification/numbers.py`
    - `count_sentences`, decision-vocabulary detector (approve, decline, recommend, credit decision; whole words, any case)
    - `extract_figures` with the exclusion masks and `normalise_figure`
    - _Requirements: 5.4, 6.5, 15.1, 15.2, 17.11, 18.8_

  - [ ]* 6.2 Write property test for figure extraction
    - **Property 31: Figure extraction skips excluded tokens**
    - **Validates: Requirements 15.1**

  - [ ]* 6.3 Write property test for figure normalisation
    - **Property 32: Figure normalisation equivalence**
    - **Validates: Requirements 15.2**

  - [ ] 6.4 Implement `verify_statement(stmt, ctx, mode)` in `verification/numbers.py`
    - Candidate set (cited CSV displays, claimed Comparison_Record changes ignoring sign, cited EV excerpt figures; S4/S5 add DI values and comparisons whose both CSV IDs are cited); structured claim matching with the four reasons; Unavailable_Metric claim check (names supplied in `VerifyContext`); deep-copied inputs; one mark per statement
    - _Requirements: 11.5, 14.8, 14.9, 15.3, 15.4, 15.5, 15.6, 15.7, 15.8, 17.9, 18.5, 18.12_

  - [ ]* 6.5 Write property test for verifier soundness
    - **Property 33: Verifier soundness for cited values**
    - **Validates: Requirements 15.3, 15.5, 15.6, 14.9, 17.9, 18.5, 18.12**

  - [ ]* 6.6 Write property test for comparison claim matching
    - **Property 34: Comparison claim matching**
    - **Validates: Requirements 15.4, 15.5, 14.8**

  - [ ]* 6.7 Write property test for Unavailable_Metric claims
    - **Property 35: Claims about Unavailable_Metrics fail**
    - **Validates: Requirements 11.5**

  - [ ]* 6.8 Write property test for verifier purity
    - **Property 36: Verification is pure and total**
    - **Validates: Requirements 15.7, 15.8**

  - [ ] 6.9 Implement `backend/app/verification/references.py`
    - `known_ids(deal)` (active EV ∪ CSV ∪ DI of this Deal), `validate_refs(cited, known)` with exact, case-sensitive membership and owner IDs in the result
    - _Requirements: 19.1, 19.2, 18.4_

  - [ ]* 6.10 Write property test for reference validation
    - **Property 44: Reference validation is exact membership**
    - **Validates: Requirements 19.1, 19.2, 18.4**

  - [ ]* 6.11 Write Number_Verifier and Reference_Validator unit tests
    - Req 29.5 three cases with text unchanged; Req 29.6 accepted IDs, absent ID rejected, other-Deal ID rejected
    - _Requirements: 29.5, 29.6_

- [ ] 7. Document core (normalisation, Passage_Locator, Document_Processor)
  - [ ] 7.1 Implement `backend/app/documents/normalise.py`
    - `normalise(s)` steps (a)-(e) in order; `normalise_with_map(chars)` returning normalised string and source index map
    - _Requirements: 7.5_

  - [ ]* 7.2 Write property test for normalisation
    - **Property 11: Normalisation is canonical and idempotent**
    - **Validates: Requirements 7.5**

  - [ ] 7.3 Implement `documents/passage_locator.py` and `documents/render.py`
    - `locate(pdf_path, page_no, excerpt, page_count)` with reference validation issues, `rawdict` char stream of that page only, normalised find, per-line union rects, `review_flag` on Not located
    - `render_page_png(pdf_path, page_no, rects)` at 150 dpi with in-memory highlight annotations, never saving the file
    - _Requirements: 7.2, 7.3, 7.4, 7.9, 20.2_

  - [ ]* 7.4 Write property test for passage location
    - **Property 12: A transformed substring of the page is located**
    - **Validates: Requirements 7.2, 7.3, 7.4**

  - [ ]* 7.5 Write property test for invalid references
    - **Property 13: Invalid references are never located**
    - **Validates: Requirements 7.9**

  - [ ] 7.6 Implement `backend/app/documents/processor.py`
    - `extract_pages(pdf_path, doc_id, doc_name)` (every page, `no_text_layer` flags), `page_tag`, `select_pages` (skips failed / excluded Documents), `order_key`, `batch_pages`, `render_batch`
    - _Requirements: 3.5, 3.8, 4.1, 4.2, 4.3, 4.4, 4.6_

  - [ ]* 7.7 Write property test for stored pages
    - **Property 2: Stored pages mirror the PDF**
    - **Validates: Requirements 4.1, 3.5**

  - [ ]* 7.8 Write property test for Page_Tags
    - **Property 3: Every page sent to the LLM carries its Page_Tag**
    - **Validates: Requirements 4.2**

  - [ ]* 7.9 Write property test for keyword selection
    - **Property 4: Keyword selection is case-insensitive and complete**
    - **Validates: Requirements 4.3**

  - [ ]* 7.10 Write property test for batching
    - **Property 5: Batching is an ordered partition**
    - **Validates: Requirements 4.4**

  - [ ]* 7.11 Write Passage_Locator unit tests on a generated PDF
    - Located with match position; hyphenated line break and typographic quotes/dashes located; absent / other-page excerpt Not located and flagged
    - _Requirements: 29.7_

- [ ] 8. Checkpoint - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. App factory and first vertical slice (intake, documents, financial APIs)
  - [ ] 9.1 Implement `backend/app/main.py` and system router
    - App factory: load prompts at startup (abort naming the prompt on `PromptLoadError`, no LLM client constructed), auto-include every `router` in `app/api/*` modules via `pkgutil`, mount `frontend/` at `/`, error handler returning `{error_code, message, fields?, details?}` through the Redactor, request IDs, no stack traces
    - `api/system.py`: `GET /api/health`, `GET /api/status` (provider configured, missing setting names, support check enabled)
    - _Requirements: 1.10, 25.8, 26.3, 27.4, 27.5, 27.8_

  - [ ] 9.2 Implement deal intake validation and `api/deals.py`
    - Add `DealIntakeRequest` validation to `models/deal.py` (trim, C3 rules, collect all failing fields, collateral → "None provided")
    - `POST/GET /api/deals`, `GET /api/deals/{id}`; store `DI-*` fields; create `audit_trail.json` on Deal creation
    - _Requirements: 2.2, 2.4, 2.5, 2.6, 2.7, 22.1_

  - [ ]* 9.3 Write property test for intake validation
    - **Property 1: Intake validation is exact and lossless**
    - **Validates: Requirements 2.2, 2.4, 2.5, 2.6, 2.7**

  - [ ] 9.4 Implement document upload in `api/documents.py`
    - Multipart upload with streamed size limit (exact limit accepted), PyMuPDF open / encrypted / 0-page rejection, temp cleanup, never-reused `doc_id`, display name ≤ 255, metadata validation, page extraction via processor, no-text-layer warnings, `extraction_excluded`, `failed` marking on later open failure; `GET` list with page counts
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.6, 3.8, 4.1, 4.6_

  - [ ] 9.5 Implement `api/financial.py` (CSV load and dashboard data)
    - `POST .../financial/upload` (`.csv` extension, ≤ 5 MB, per-Deal `financial/source.csv`), `POST .../financial/load` with `needs_confirmation` flow and decline, atomic write of dataset + CSV evidence, `GET .../financial` (dataset, flags summary, gaps, comparisons, defaults applied), `GET .../dashboard` (404 message when no dataset)
    - _Requirements: 8.1, 8.2, 8.9, 8.12, 8.14, 10.8, 10.9, 13.8_

  - [ ]* 9.6 Write API tests for intake, documents and financial endpoints
    - TestClient with `tmp_path` data folder: field errors listed, no Deal on failure; invalid / oversize PDF rejected without consuming a doc_id; CSV confirm/decline; dashboard 404 without dataset
    - _Requirements: 2.4, 2.6, 3.3, 3.4, 8.9, 8.14, 13.8_

- [ ] 10. LLM_Client and runner
  - [ ] 10.1 Implement `backend/app/llm/client.py` and providers
    - `LLMClient` protocol, `LLMTransportError`, `make_client(settings)`; `providers/openai.py`, `gemini.py`, `anthropic.py` using httpx, temperature 0, 120 s timeout, JSON response modes; only these modules import httpx
    - _Requirements: 25.1, 25.2, 27.2, 27.3_

  - [ ] 10.2 Implement `backend/app/llm/runner.py` and test fake
    - `TaskSpec` (prompt_id, output model, section_rules, `retry_transport` True only for S2A/S2B, `soft_unknown_refs` True only for S5), `run_llm_task`: `.env` check → canonical-JSON user message → call → audit `llm_output` entry with sha256 input hash → fence-strip + parse → schema → section rules → Reference_Validator → retry with "VALIDATION ERRORS FROM PREVIOUS ATTEMPT" (max 3 attempts); transport errors stop Sections 3-6 immediately and count against the budget in Section 2; S5 soft-accepts remaining unknown refs; redacted errors
    - Create `backend/tests/fakes.py` with `FakeLLMClient` (scripted responses, recorded calls)
    - _Requirements: 19.3, 22.4, 25.3, 25.4, 25.5, 25.6, 25.7, 25.8, 25.9, 25.10, 27.8_

  - [ ]* 10.3 Write property test for input hashing
    - **Property 49: Input hash determinism**
    - **Validates: Requirements 22.4**

  - [ ]* 10.4 Write property test for bounded retry
    - **Property 53: Bounded retry with errors fed back**
    - **Validates: Requirements 25.4, 25.5, 19.3**

  - [ ]* 10.5 Write runner unit tests
    - Invalid-then-valid accepted after 1 retry with errors in the retry; always invalid → exactly 3 calls and errors returned; Section 3 transport error → 1 call, stop; Section 2 transport error counted in budget; missing `.env` settings → 0 calls
    - _Requirements: 29.11, 25.8, 25.9, 25.10_

- [ ] 11. Section 2 extraction (2A, 2B, 2C)
  - [ ] 11.1 Implement `backend/app/sections/s2_rules.py`
    - `validate_2a_item` / `validate_2b_item` (required elements, batch tag set, excerpt 1-500, 2A ≤ 300 chars and ≤ 2 sentences, ≤ 5 items per field, 2B figures verbatim in excerpt), rejection reasons / "Invalid output", `merge_batches` ordered by `order_key`, 2B conflict grouping by `(item_key, as_of)`, "Not available" fields
    - _Requirements: 4.5, 5.2, 5.3, 5.4, 5.5, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ]* 11.2 Write property test for merge ordering
    - **Property 6: Merged batch results are ordered**
    - **Validates: Requirements 4.5**

  - [ ]* 11.3 Write property test for 2A item validation
    - **Property 7: Section 2A item validation**
    - **Validates: Requirements 5.2, 5.3, 5.4, 5.5**

  - [ ]* 11.4 Write property test for 2B verbatim figures
    - **Property 8: Section 2B figures appear verbatim in the excerpt**
    - **Validates: Requirements 6.2, 6.5, 6.6**

  - [ ]* 11.5 Write property test for conflicts
    - **Property 9: Conflicting debt items are never resolved**
    - **Validates: Requirements 6.4**

  - [ ] 11.6 Implement Evidence_ID assignment in `backend/app/sections/evidence_ids.py`
    - `format_ev_id`, monotonic `next_ev_seq`, fixed field order then item order, archive superseded scope records to `evidence_archive.json`, run Passage_Locator before storing each DocEvidence, skip "Not available" fields
    - _Requirements: 7.1, 7.2, 7.4, 7.6, 7.8, 7.9_

  - [ ]* 11.7 Write property test for Evidence_IDs
    - **Property 10: Evidence_IDs are well-formed and never reused**
    - **Validates: Requirements 7.1, 7.6**

  - [ ] 11.8 Implement `sections/s2_extraction.py`, section state helper and `api/section2.py`
    - `storage/section_state.py`: set completed / failed with redacted errors, mark later sections `stale`, reset S3 approval on S3 re-run
    - Extraction service: select pages per scope (no LLM call and message when none / no Documents), batch, run `run_llm_task` per batch, validate, merge, assign IDs, all-or-nothing store of `s2a.json` / `s2b.json`; failure keeps earlier outputs
    - `POST .../section2/run {scopes?}`, `GET .../section2`
    - _Requirements: 3.8, 4.7, 5.1, 5.6, 5.7, 6.1, 6.3, 6.7, 7.7, 25.10_

  - [ ]* 11.9 Write Section 2 service tests with FakeLLMClient
    - No pages → no call; invalid output rejected items recorded; failure after retries leaves stored outputs unchanged; re-run never reuses EV numbers
    - _Requirements: 4.7, 5.6, 5.7, 6.7, 7.6_

- [ ] 12. Checkpoint - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. Section 3 trend analysis and approval gate
  - [ ] 13.1 Implement `backend/app/sections/s3_rules.py`
    - `build_s3_input(deal)` (intake, active S2 items, dataset, comparisons, sustained labels, unavailable payload, divergence assessability, panels)
    - `s3_rules(output, ctx)`: panel and metric coverage, Sourced/ASSUMPTION citation rules, divergence entries match assessability with exact "not assessable" text, repayment dimension coverage, sustained wording only where supplied
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 14.10, 14.12_

  - [ ]* 13.2 Write property test for Section 3 label rules
    - **Property 30: Section 3 label and citation rules**
    - **Validates: Requirements 14.5, 14.12**

  - [ ] 13.3 Implement `sections/s3_trend.py` and `api/section3.py`
    - Preconditions (dataset loaded, S2A and S2B completed; 409 naming missing input, no LLM call); run task; assign `S3-n` IDs; Number_Verifier on every statement before storing; `number_check` audit entry; Pending statuses; store divergence gaps for Section 5; `POST .../section3/run`, `GET .../section3`
    - _Requirements: 13.5, 13.9, 14.1, 14.11, 15.8, 22.3_

  - [ ] 13.4 Implement `review/validation.py`, `review/section3_gate.py` and `api/section3_review.py`
    - Validation helpers: analyst name 1-100, S3 edit 1-5,000, comment 1-2,000, memo correction 1-2,000 (trimmed)
    - `approval_blockers`, `apply_s3_action` (approve / flag / comment / edit with re-verify and Pending; revocation when approved); audit-first ordering with panel, text before/after, name, timestamp
    - `POST .../section3/statements/{sid}/action`, `POST .../section3/approve` (409 with blocker list)
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.8, 22.6, 22.7, 22.8_

  - [ ]* 13.5 Write state-machine property test for Section 3 review
    - **Property 37: Section 3 review state machine**
    - **Validates: Requirements 16.2, 16.3, 16.8, 22.6**

  - [ ]* 13.6 Write property test for approval blockers
    - **Property 38: Approval blockers**
    - **Validates: Requirements 16.5, 16.6**

  - [ ]* 13.7 Write property test for name and text length validation
    - **Property 39: Name and text length validation**
    - **Validates: Requirements 16.4, 20.12, 20.13, 22.7**

  - [ ]* 13.8 Write Section 3 gate unit tests
    - Approval refused while an unflagged "Number mismatch" statement exists; audit write failure leaves change unapplied
    - _Requirements: 29.12, 22.8_

- [ ] 14. Section 4 risks and mitigants
  - [ ] 14.1 Implement `backend/app/sections/s4_rules.py`
    - `build_s4_input` (approved S3 with corrected text, S2 items, dataset with flags, comparisons, unavailable payload, intake); `s4_rules` (count, fewer-than-3 limitation, consecutive ranks, sort-key order, mitigants/terms, numeric-term ASSUMPTION + calibration sentence, decision vocabulary)
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.10, 17.11_

  - [ ]* 14.2 Write property test for Section 4 structure
    - **Property 40: Section 4 structural rules**
    - **Validates: Requirements 17.2, 17.3, 17.4, 17.7**

  - [ ]* 14.3 Write property test for decision vocabulary
    - **Property 41: No decision vocabulary**
    - **Validates: Requirements 17.11, 18.8**

  - [ ] 14.4 Implement `sections/s4_risks.py` and `api/section4.py`
    - 409 "Section 3 approval is required" with no LLM call while unapproved; run task; Number_Verifier (`mode="S4"`) per risk evidence; store `s4.json`; `POST .../section4/run`, `GET .../section4`
    - _Requirements: 16.7, 17.1, 17.9, 17.10_

  - [ ]* 14.5 Write Section 4 tests
    - Run rejected while unapproved with zero LLM calls; >5 risks or wrong order triggers retry then stop
    - _Requirements: 29.12, 16.7, 17.10_

- [ ] 15. Section 5 credit memo
  - [ ] 15.1 Implement `backend/app/sections/s5_rules.py`
    - `MEMO_OUTLINE` (7 sections, 22 subsection keys); `build_s5_input` with de-duplicated information-gap list (CSV gaps, divergence gaps, Unavailable_Metrics referenced in S3/S4, every Anomaly_Flag with its CSV ID); `s5_rules` (exact outline, placeholder statement, Sourced cites ≥ 1 ID, pro-forma DSCR NOT VERIFIED statement, gap coverage, "Not available in database" usage, decision vocabulary)
    - _Requirements: 11.1, 11.2, 18.1, 18.2, 18.3, 18.4, 18.6, 18.7, 18.8, 18.11_

  - [ ]* 15.2 Write property test for unavailable metrics in LLM inputs
    - **Property 27: Unavailable metrics carry no numbers into LLM inputs**
    - **Validates: Requirements 11.1, 11.2**

  - [ ]* 15.3 Write property test for the memo outline
    - **Property 42: Memo outline is exact**
    - **Validates: Requirements 18.2**

  - [ ]* 15.4 Write property test for Information Gaps coverage
    - **Property 43: Information Gaps covers every gap and flag**
    - **Validates: Requirements 18.6**

  - [ ] 15.5 Implement memo initialisation in `backend/app/review/memo_review.py`
    - `initialise(memo, deal)`: `M1..Mn` IDs, Pending, Reference_Validator flags ("Reference does not exist", "No supporting reference"), Number_Verifier marks, Req 20.8 pre-approval; `status_counts`; `flag_statement(sid, note)` helper
    - _Requirements: 18.9, 18.12, 19.4, 19.5, 19.6, 20.8, 25.6, 25.7_

  - [ ]* 15.6 Write property test for memo initialisation
    - **Property 45: Memo initialisation**
    - **Validates: Requirements 18.9, 19.4, 19.5, 19.6, 20.8, 25.7**

  - [ ] 15.7 Implement `sections/s5_memo.py` and `api/section5.py`
    - 409 "Section 4 must be completed first"; run task with soft unknown refs; store `s5.json` and `review.json`; `POST .../section5/run`, `GET .../memo` (statements, statuses, counts)
    - _Requirements: 18.1, 18.9, 18.10, 25.6_

  - [ ]* 15.8 Write Section 5 service tests
    - Final attempt with unknown refs stores memo and flags only those statements; Section 5 rejected without Section 4
    - _Requirements: 18.10, 19.4, 25.6_

- [ ] 16. Section 6 review, source verification and support check
  - [ ] 16.1 Implement source panel in `review/source.py` and `api/evidence.py`
    - `GET .../evidence/{evidence_id}/source?statement_id=`: EV → document/page checks (flag "Source document unavailable"), Passage_Locator, 150 dpi PNG with highlights, first-activation "Source passage not located" flag via `opened` tracking; CSV → file, label, header, display value, flags or "None"; DI → field and value
    - _Requirements: 20.2, 20.3, 20.5, 20.11_

  - [ ] 16.2 Implement memo review actions in `review/memo_review.py` and `api/review.py`
    - approve, flag (note ≤ 500), correct (1-2,000; text replaced, Pending); analyst name validation; audit-first entries with text before/after, cited IDs, evidence snapshot per ID, status before/after, correction, name, timestamp
    - `POST .../memo/statements/{sid}/action`
    - _Requirements: 20.6, 20.7, 20.12, 20.13, 22.2, 22.5, 22.7, 22.8_

  - [ ]* 16.3 Write state-machine property test for memo review
    - **Property 46: Memo review state machine**
    - **Validates: Requirements 20.7, 22.2**

  - [ ]* 16.4 Write property test for status counts and the PDF gate
    - **Property 47: Status counts and PDF gate**
    - **Validates: Requirements 20.10, 24.2, 23.1**

  - [ ] 16.5 Implement `sections/s6_support.py` and `api/support.py`
    - Only when `SUPPORT_CHECK_ENABLED` (404 otherwise, no LLM call); payload = statements citing ≥ 1 active EV with text + excerpts only; store results with `text_hash`; failure → `unavailable`; never changes statuses, notes, text or IDs
    - _Requirements: 21.1, 21.2, 21.3, 21.4, 21.5, 21.6_

  - [ ]* 16.6 Write property test for support check isolation
    - **Property 48: Support check scope and isolation**
    - **Validates: Requirements 21.1, 21.4**

  - [ ]* 16.7 Write source endpoint tests
    - Document source returns page image within 5 s; missing page flags statement; CSV source returns "None" when unflagged
    - _Requirements: 20.2, 20.3, 20.5, 20.11_

- [ ] 17. PDF exports
  - [ ] 17.1 Implement `export/citations.py` and `export/filenames.py`
    - Citation formats for document, CSV and intake evidence in cited order; `sanitise_borrower` and both file names with local date
    - _Requirements: 23.3, 23.6, 24.4_

  - [ ]* 17.2 Write property test for citations
    - **Property 51: Citation formatting**
    - **Validates: Requirements 23.3**

  - [ ]* 17.3 Write property test for file names
    - **Property 52: Export file names are safe**
    - **Validates: Requirements 23.6, 24.4**

  - [ ] 17.4 Implement `export/memo_pdf.py` and memo export in `api/exports.py`
    - ReportLab Platypus; header on every page; first-page borrower, analyst name, review date; sections 1-7 with statements in ID order, FLAGGED prefix + note, ASSUMPTION / NOT VERIFIED labels, citations + `(M<n>)`; no support-check text, no decision field; temp file + `os.replace`, cleanup on failure
    - `POST .../exports/memo {analyst_name}`: 409 with pending count, 400 missing name
    - _Requirements: 21.7, 23.1, 23.2, 23.3, 23.4, 23.5, 23.7, 23.8, 23.9_

  - [ ] 17.5 Implement `export/audit_pdf.py` and audit export in `api/exports.py`
    - Summary block (intake + DI refs, documents, CSV file name, generated at, counts), PENDING notice and markers, Section 3 review section, per-statement evidence entries / "No supporting reference"
    - `POST .../exports/audit-trail` (409 without memo), `GET .../audit-trail`
    - _Requirements: 24.1, 24.2, 24.3, 24.4, 24.5, 24.6, 24.7_

  - [ ]* 17.6 Write PDF and review-gate tests
    - Extract text with PyMuPDF: header on every page, 7 titles in order, citations, FLAGGED, no support-check text, PENDING notice; renderer exception leaves no file
    - Req 29.8: editing an Approved statement resets to Pending; export rejected with pending count; succeeds once none Pending
    - _Requirements: 29.8, 23.2, 23.5, 23.9, 24.6_

- [ ] 18. Checkpoint - Ensure all tests pass, ask the user if questions arise.

- [ ] 19. Static frontend (vanilla JS)
  - [ ] 19.1 Vendor Chart.js (one-time setup step)
    - Download the Chart.js 4.x UMD build once into `frontend/vendor/chart.umd.min.js` at a pinned version (e.g. 4.4.x); record the version and SHA-256 in `frontend/vendor/chart.VERSION`; the app never fetches it from a CDN at runtime
    - _Requirements: 13.1, 26.7_

  - [ ] 19.2 Create the frontend shell
    - `index.html` (persistent non-dismissible notice, deal selector, labelled analyst name field, step navigation 1-6, `aria-live="polite"` status region, main region), `css/app.css` (contrast-safe palette tokens, 3 px `:focus-visible`), `js/app.js` (hash router importing screen modules), `js/api.js` (fetch wrapper rendering `{message, fields}`), `js/state.js`, `js/a11y.js` (announce, field error association, focus first invalid)
    - _Requirements: 26.3, 26.7, 27.6, 28.1, 28.2, 28.4, 28.6, 28.7_

  - [ ] 19.3 Implement `js/screens/intake.js`
    - Eight labelled fields with required markers, client-side required check keeping values, server error display per field, existing Deals list
    - _Requirements: 2.1, 2.3, 2.4, 2.7, 28.1, 28.7_

  - [ ] 19.4 Implement `js/screens/documents.js`
    - Upload form (file, type select, period text ≤ 50, audited radio) blocking incomplete submissions; document table with warnings and failed status; CSV panel (replace upload, load with whole-file confirmation dialog, defaults-applied notice, flagged-value summary)
    - _Requirements: 3.1, 3.5, 3.6, 3.7, 4.6, 8.9, 8.14, 10.8, 10.9_

  - [ ] 19.5 Implement `js/screens/section2.js`
    - Run button with live-region progress; Business then Debt & Financing groups in fixed order showing Evidence_ID / "None", statement, doc name, page, location status, issue text labels, rejected items and Conflicting candidates
    - _Requirements: 4.7, 5.7, 6.7, 7.7, 28.3, 28.6_

  - [ ] 19.6 Implement `js/charts.js` and `js/screens/dashboard.js`
    - Line charts per unit type (`spanGaps: false`), inline point-label plugin for display value + flag text, y-axis unit title; latest value and comparison text; "Not available in database" lists; keyboard-reachable data tables with captions; commentary with label, IDs, verifier mark, status and approve/flag/comment/edit controls; divergence list; Approve financial analysis with blocker list
    - _Requirements: 10.7, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9, 15.5, 16.1, 16.4, 16.6, 28.3, 28.5_

  - [ ] 19.7 Implement `js/screens/risks.js` and `js/screens/memo.js`
    - Disclaimer always above the 4-column risk table (including 0 rows), verifier marks, limitations; read-only memo outline with statement IDs, labels and statuses
    - _Requirements: 17.8, 17.9, 18.9_

  - [ ] 19.8 Implement `js/screens/review.js` (Section 6 and downloads)
    - Accuracy notice; filter tabs with counts; statement list with Evidence_ID buttons, approve / flag (note ≤ 500) / correct; source panel beside the statement (page image with alt text, CSV / intake details); support-check results labelled "AI preliminary check; analyst verification required" or "Not checked", hidden when disabled; Credit Memo and Audit Trail PDF downloads with disabled reason when Pending > 0
    - _Requirements: 20.1, 20.4, 20.6, 20.9, 20.10, 20.12, 21.3, 21.6, 23.1, 28.2, 28.3_

  - [ ]* 19.9 Write frontend static tests
    - Assert contrast ratios of CSS colour tokens (4.5:1 text, 3:1 non-text); assert no `http(s)://` external asset references in `frontend/`; required notice text present in `index.html`
    - _Requirements: 26.7, 27.6, 28.4_

- [ ] 20. Single-click launcher
  - [ ] 20.1 Implement launcher helpers in `tools/`
    - `check_python.py` (exit non-zero below 3.11), `port_free.py <port>`, `wait_for_health.py <port> <timeout>` polling `/api/health`
    - _Requirements: 26.2, 26.4, 26.6, 26.10_

  - [ ] 20.2 Implement `start.bat`
    - Steps per C20: Python check, `.env` creation from `.env.example` and stop, venv create + pinned install with `.install_ok` marker keyed to the `requirements.txt` hash (recreate on failure next launch), port check, start uvicorn on 127.0.0.1, health wait 30 s, open browser; every failure shows a message and pauses
    - _Requirements: 26.1, 26.2, 26.4, 26.5, 26.6, 26.8, 26.9, 26.10, 27.5_

  - [ ]* 20.3 Write tests for launcher helpers
    - Exit codes for port in use / free and health wait timeout using local sockets
    - _Requirements: 26.6, 26.10_

- [ ] 21. End-to-end integration
  - [ ] 21.1 Write the full-pipeline integration test
    - `tests/integration/test_pipeline.py`: TestClient + FakeLLMClient with scripted outputs on a generated Intel-like PDF and `intel_quarterly_ratios.csv`: create Deal → upload → load CSV → Section 2 → dashboard → Section 3 → review and approve → Section 4 → Section 5 → open document / CSV / DI sources (image within 5 s) → review all statements → both PDFs
    - Assert every written file is under the temporary data folder, no API key substring in any stored file or response, and no outbound network call (runs with no API key in the environment)
    - _Requirements: 27.1, 27.3, 27.8, 27.9, 29.10, 20.2, 23.2, 24.1_

- [ ] 22. Final checkpoint - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; the integration test (21.1) is kept required because it validates the whole slice.
- Downloading Chart.js (19.1) is a one-time setup step; after that the app makes no external requests for frontend assets.
- Each property test task maps to exactly one design Correctness Property (1-54) and runs at least 100 hypothesis examples.
- Manual checks remain for UI layout, keyboard order, screen-reader output and the `start.bat` flow on Windows; full WCAG conformance requires assistive-technology testing and expert review.
- The prototype has no authentication; access control must be added before any shared or networked deployment.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "2.2", "3.1", "3.4"] },
    { "id": 2, "tasks": ["1.3", "1.4", "2.3", "3.2", "3.3", "3.6", "5.1", "6.1", "7.1"] },
    { "id": 3, "tasks": ["2.4", "3.5", "3.8", "5.2", "5.3", "6.2", "6.3", "6.9", "7.2", "7.3"] },
    { "id": 4, "tasks": ["3.7", "3.9", "5.4", "5.5", "6.4", "6.10", "7.4", "7.5", "7.6"] },
    { "id": 5, "tasks": ["5.6", "5.7", "5.8", "5.9", "5.10", "6.5", "6.6", "6.7", "6.8", "6.11", "7.7", "7.8", "7.9", "7.10", "7.11"] },
    { "id": 6, "tasks": ["5.11", "5.12"] },
    { "id": 7, "tasks": ["5.13", "5.14", "5.15", "5.16", "5.17", "5.18", "5.19"] },
    { "id": 8, "tasks": ["5.20", "5.21", "9.1", "10.1"] },
    { "id": 9, "tasks": ["9.2", "10.2"] },
    { "id": 10, "tasks": ["9.3", "9.4", "10.3", "10.4", "10.5", "11.1"] },
    { "id": 11, "tasks": ["9.5", "11.2", "11.3", "11.4", "11.5", "11.6"] },
    { "id": 12, "tasks": ["9.6", "11.7", "11.8"] },
    { "id": 13, "tasks": ["11.9", "13.1"] },
    { "id": 14, "tasks": ["13.2", "13.3"] },
    { "id": 15, "tasks": ["13.4"] },
    { "id": 16, "tasks": ["13.5", "13.6", "13.7", "13.8", "14.1"] },
    { "id": 17, "tasks": ["14.2", "14.3", "14.4"] },
    { "id": 18, "tasks": ["14.5", "15.1"] },
    { "id": 19, "tasks": ["15.2", "15.3", "15.4", "15.5"] },
    { "id": 20, "tasks": ["15.6", "15.7"] },
    { "id": 21, "tasks": ["15.8", "16.1", "16.5", "17.1"] },
    { "id": 22, "tasks": ["16.2", "16.6", "17.2", "17.3"] },
    { "id": 23, "tasks": ["16.3", "16.4", "16.7", "17.4"] },
    { "id": 24, "tasks": ["17.5"] },
    { "id": 25, "tasks": ["17.6", "19.1", "19.2", "20.1"] },
    { "id": 26, "tasks": ["19.3", "19.4", "19.5", "19.6", "19.7", "19.8", "20.2", "20.3"] },
    { "id": 27, "tasks": ["19.9"] },
    { "id": 28, "tasks": ["21.1"] }
  ]
}
```
