# Requirements Document

## Introduction

The AI-Assisted Credit Analysis App is a local, single-user prototype (BU5203) that helps a credit analyst assess whether a borrower can support a specific loan request. The analyst enters the deal and uploads borrower documents (annual reports, 10-K, 10-Q, audited financial statements, other files). The application processes two sources separately:

- **Documents** are read by an LLM, which extracts qualitative business information and debt / financing information. Every extracted item receives an Evidence ID and its supporting passage is located on the cited PDF page with PyMuPDF.
- **The financial database** (a CSV of pre-calculated quarterly ratios, e.g. `intel_quarterly_ratios.csv`) is loaded by Python + Pandas. The backend never calculates credit ratios and the LLM never extracts or calculates financial figures.

The pipeline follows the updated Project Details (Sections 1-6): Deal Intake (1) -> Extraction (2) -> Financial Trend Dashboard + AI Analysis with an analyst approval gate (3) -> Risks + Mitigants (4) -> Credit Memo with Evidence (5) -> Analyst Review + Source Verification, producing a final Credit Memo PDF and a separate Audit Trail PDF (6).

The project also includes a rewrite of `Instructions.md`, the file the runtime LLM and the coding agent read, so that it matches the updated Project Details and supersedes the earlier "Layer 2-7" design (credit-engine formulas, AI recommendation, blind spots, sign-off decision).

Test borrower: Intel Corporation (Technology / Semiconductors). Nothing is hard-coded to Intel.

The prototype runs locally with no authentication. This must be addressed before any shared or networked deployment.

## Glossary

- **Credit_Analysis_App**: The complete prototype, consisting of the Backend and the Frontend.
- **Backend**: The Python (FastAPI) server that stores data, processes documents and the CSV, calls the LLM, verifies outputs and renders PDFs.
- **Frontend**: The browser user interface, served as static files by the Backend.
- **Analyst**: The credit analyst using the Credit_Analysis_App.
- **Deal**: One loan request for one borrower, with its intake fields, documents, Financial_Dataset and all section outputs.
- **Deal_Intake_Field**: An analyst-entered deal attribute (borrower name, facility type, requested amount and currency, purpose, tenor, repayment structure, collateral / security), each identified by a `DI-<FIELD>` reference.
- **Document**: An uploaded PDF file with a doc_id (D1, D2, ... in upload order), display name, document type, period covered and audited flag.
- **Page_Tag**: The marker `[[DOC <doc_id> | <doc_name> | PAGE <n>]]` placed before each page's text sent to the LLM, where n is the 1-based physical PDF page.
- **Document_Processor**: The Backend component that extracts per-page text from Documents with PyMuPDF and selects relevant pages for extraction.
- **Extraction_Service**: The Backend component that runs the Section 2 LLM extraction prompts for business information and for debt / financing information.
- **Evidence_ID**: A unique identifier assigned by the Backend to an evidence item. Document evidence uses `EV-###`; financial database evidence uses `CSV-<METRIC_KEY>-<PERIOD>` (e.g. `CSV-DSCR-Q2-2026`); deal intake uses `DI-<FIELD>`.
- **Evidence_Record**: The stored JSON record for one Evidence_ID. For Documents: doc_id, doc_name, page, section, supporting text excerpt, extracted statement, location status. For the CSV: file name, metric label as written in the CSV, column header, cell display value, parsed value, unit type, flags.
- **Evidence_Store**: The per-Deal JSON file holding all Evidence_Records.
- **Passage_Locator**: The Backend component that uses PyMuPDF to search a referenced PDF page for a supporting text excerpt and returns the match location or "not located".
- **Financial_Database**: The CSV file of pre-calculated financial metrics, rows = metrics and columns = periods.
- **CSV_Loader**: The Backend component that loads the Financial_Database with Pandas and builds the Financial_Dataset.
- **Financial_Dataset**: The structured dataset produced by the CSV_Loader: periods ordered oldest to newest, one entry per canonical metric per period, each with display value, parsed value, unit type, Evidence_ID and flags.
- **Canonical_Metric**: One of the ten recognised CSV metrics, in fixed order: REVENUE_GROWTH, EBITDA_MARGIN, DEBT_EBITDA, INTEREST_COVERAGE, CURRENT_RATIO, DSCR, OPERATING_CASH_FLOW, OCF_MARGIN, WORKING_CAPITAL, DSO.
- **Unavailable_Metric**: A metric referenced by the Project Details but absent from the Financial_Database (e.g. Revenue, EBITDA, Total Debt, Net Debt, Cash, Short-term Debt, Capital Expenditure, Free Cash Flow, Interest Expense, Quick Ratio, Debt / Equity, Net Profit Margin).
- **Value_Formatter**: The Backend function that renders a parsed Financial_Dataset value back into a display string.
- **Anomaly_Flag**: A Backend-generated marker on a Financial_Dataset value that requires Analyst review (zero value, negative value, large swing, unit not stated, unparseable value).
- **Comparison_Record**: A Backend-computed period-over-period comparison for one metric (from period, to period, change in the metric's native unit, direction "up" / "down" / "~"). Used to supply facts to the LLM and to verify LLM claims; not a credit ratio.
- **Stable_Band**: A configurable tolerance within which a change is labelled "~".
- **Dashboard**: The Frontend screen showing charts for profitability, leverage, liquidity, cash flow and debt servicing, each beside its AI commentary.
- **Trend_Analyst**: The Section 3 LLM task that analyses trends, divergences, business context and repayment capacity from the Financial_Dataset and Section 2 outputs.
- **Number_Verifier**: The Backend component that checks every figure and comparison claimed by an LLM output against the Financial_Dataset and Comparison_Records.
- **Risk_Analyst**: The Section 4 LLM task that produces the ranked risk, mitigant and proposed term table.
- **Memo_Generator**: The Section 5 LLM task that writes the 7-section credit memo using existing Evidence_IDs.
- **Reference_Validator**: The Backend component that checks every Evidence_ID cited in an LLM output exists in the Evidence_Store or Financial_Dataset of that Deal.
- **Memo_Statement**: One statement in the credit memo, with a statement ID, text, cited Evidence_IDs and label.
- **Verification_Status**: The review state of a reviewable item: Pending, Approved or Flagged.
- **Audit_Trail**: The per-Deal JSON record of every reviewed item: statement, source references, original supporting text or financial data, Verification_Status, Analyst corrections, analyst name and timestamps, including the Section 3 review.
- **Support_Checker**: The optional Section 6 LLM task that gives a preliminary assessment of whether a cited excerpt supports a Memo_Statement, for the Analyst's information only.
- **PDF_Renderer**: The Backend component that produces the final Credit Memo PDF and the Audit Trail PDF.
- **LLM_Client**: The provider-agnostic Backend wrapper that calls the configured LLM provider (e.g. OpenAI, Gemini, Anthropic) selected in `.env`.
- **Launcher**: The `start.bat` file that sets up and starts the Credit_Analysis_App with a double-click.
- **Instructions_File**: `Instructions.md`, the single source of truth for the coding agent and the runtime prompts.
- **Statement_Label**: One of Sourced, ASSUMPTION, NOT VERIFIED.

## Requirements

### Requirement 1: Rewrite the Instructions File

**User Story:** As the project owner, I want Instructions.md to match the updated Project Details, so that the coding agent and the runtime LLM follow the current pipeline and do not hallucinate.

#### Acceptance Criteria

1. THE Instructions_File SHALL describe the pipeline as exactly six numbered sections, in this order: Section 1 Deal Intake, Section 2 Extraction, Section 3 Financial Trend Dashboard + AI Analysis with an Analyst approval gate, Section 4 Risks + Mitigants, Section 5 Credit Memo with Evidence, and Section 6 Analyst Review + Source Verification. Section 6 SHALL be stated to produce a final Credit Memo PDF and a separate Audit_Trail PDF through the PDF_Renderer, and the file SHALL contain zero references to the superseded "Layer 2" to "Layer 7" numbering.
2. THE Instructions_File SHALL contain one Master System Prompt with a separate rule for each of the following: (a) the closed source boundary, meaning uploaded Documents, Deal_Intake_Fields, the Financial_Dataset and earlier section outputs only; (b) no invented facts, figures or Evidence_IDs; (c) no LLM arithmetic, ratio calculation or financial figure extraction; (d) every factual statement cites at least one existing Evidence_ID; (e) every Memo_Statement carries exactly one Statement_Label (Sourced, ASSUMPTION or NOT VERIFIED), with the condition for each label defined; (f) any Unavailable_Metric is reported as "Not available in database" and never estimated; (g) no automatic credit decision, approval recommendation or sign-off; (h) output is a single JSON object matching the prompt's schema, with no text outside the JSON.
3. THE Instructions_File SHALL contain exactly one runtime prompt for each of: Section 2A business extraction, Section 2B debt and financing extraction, Section 3 trend analysis, Section 4 risks and mitigants, Section 5 credit memo, and Section 6 support check (Support_Checker). Each prompt SHALL carry a version identifier and a fixed JSON output schema that lists every output field with its type and whether it is required. The Section 5 prompt SHALL require exactly 7 memo sections and SHALL contain no recommendation field and no blind-spots field.
4. THE Instructions_File SHALL state that historical financial figures and credit metrics come only from the Financial_Database, loaded by the CSV_Loader with Pandas, and that neither the Backend nor the LLM calculates credit ratios. It SHALL state that only the ten Canonical_Metrics are used, that each Unavailable_Metric is shown as "Not available in database", and that a zero value in the Financial_Database is used as a real value and carries an Anomaly_Flag.
5. THE Instructions_File SHALL define: the three Evidence_ID formats (`EV-###`, `CSV-<METRIC_KEY>-<PERIOD>`, `DI-<FIELD>`), each with one example; the fixed vocabularies for Statement_Label, Verification_Status (Pending, Approved, Flagged) and Comparison_Record direction ("up", "down", "~"); the ten Canonical_Metrics in their fixed order; the trigger condition for each of the five Anomaly_Flag types, including the numeric large-swing thresholds; and the Stable_Band defaults per unit type.
6. THE Instructions_File SHALL contain no formula, prompt instruction or output schema field for any of the superseded items: credit-engine formulas, derived-figure rules, the AI indicative recommendation, the potential blind spots section and the AI-driven sign-off decision.
7. THE Instructions_File SHALL state that the prototype runs locally for a single user with no authentication, and that authentication must be added before any shared or networked deployment.
8. THE Backend SHALL load each of the six runtime prompts from a separate file whose version identifier equals that prompt's version in the Instructions_File and whose text is identical, character for character apart from line-ending differences, to the corresponding prompt text in the Instructions_File.
9. THE Instructions_File SHALL state the runtime constraints: Python-only Backend (FastAPI); Frontend served as static files by the Backend; LLM provider chosen in `.env` and called only through the provider-agnostic LLM_Client; and start-up through the Launcher with a single double-click.
10. IF any of the six runtime prompt files is missing, unreadable or has no version identifier when the Backend starts, THEN THE Backend SHALL stop start-up and report an error naming the affected prompt, and SHALL NOT make any LLM_Client call.
11. THE Instructions_File SHALL state that Section 6 verification happens in the Frontend: each Memo_Statement's cited Evidence_IDs open their Evidence_Record (the passage location from the Passage_Locator for Documents, or the cell display value for the Financial_Database), and that Support_Checker output is advisory only and never changes a Verification_Status.

### Requirement 2: Deal Intake

**User Story:** As an Analyst, I want to enter the loan request details, so that the analysis assesses whether the borrower can support this specific loan.

#### Acceptance Criteria

1. THE Frontend SHALL provide labelled input fields for borrower / company name, facility type, requested amount, currency, purpose, tenor, repayment structure and collateral / security, and SHALL mark every field except collateral / security as required.
2. WHEN the Analyst submits the intake form with all required fields completed and all values passing criteria 4 and 7, THE Backend SHALL create a Deal and store each Deal_Intake_Field, with leading and trailing whitespace removed and otherwise exactly as entered, under its reference: `DI-BORROWER`, `DI-FACILITY_TYPE`, `DI-AMOUNT` (requested amount together with currency), `DI-PURPOSE`, `DI-TENOR`, `DI-REPAYMENT` and `DI-COLLATERAL`.
3. IF the Analyst submits the intake form with one or more required fields empty or containing only whitespace, THEN THE Frontend SHALL display an indication next to each such field identifying it as required, keep the form unsubmitted, and retain the values already entered in all other fields.
4. IF the Analyst submits a requested amount that is non-numeric, less than 0.01, greater than 999,999,999,999.99 or has more than 2 decimal places, THEN THE Backend SHALL reject the submission without creating a Deal and return an error message identifying the requested amount field, and THE Frontend SHALL display that message and retain all entered values.
5. WHEN the Analyst submits the intake form with the collateral / security field empty or containing only whitespace, THE Backend SHALL store the value "None provided" for `DI-COLLATERAL`.
6. IF the Backend receives an intake submission in which any required Deal_Intake_Field is missing, empty or contains only whitespace, THEN THE Backend SHALL reject the submission without creating a Deal and return an error message identifying each missing field.
7. IF the Analyst submits a currency that is not exactly 3 letters, a borrower / company name longer than 200 characters, a facility type or tenor longer than 100 characters, or a purpose, repayment structure or collateral / security value longer than 2,000 characters, THEN THE Backend SHALL reject the submission without creating a Deal and return an error message identifying each field that failed, and THE Frontend SHALL display that message and retain all entered values.

### Requirement 3: Document Upload

**User Story:** As an Analyst, I want to upload the borrower's filings, so that the AI can extract business and financing information from them.

#### Acceptance Criteria

1. WHEN the Analyst selects a file to upload to a Deal, THE Frontend SHALL capture the document type (exactly one of Annual Report, 10-K, 10-Q, Audited Financial Statements, Other), the period covered (free text of 1 to 50 characters, e.g. "FY2025" or "Q2 2026") and the audited flag (Yes or No) before the upload can be submitted.
2. WHEN a valid PDF is uploaded, THE Backend SHALL store the file locally under that Deal, assign the next doc_id in upload order (D1, D2, ...; a doc_id is never reused within a Deal), record a display name defaulting to the original file name (maximum 255 characters) and save the document type, period covered and audited flag with the Document.
3. IF an uploaded file is not a valid PDF (PyMuPDF cannot open it, it is password-protected, or it contains 0 pages), THEN THE Backend SHALL reject the file without storing it or assigning a doc_id, leaving the Deal's existing Documents unchanged, and return a message stating that only readable PDF files are accepted.
4. IF an uploaded file exceeds the configured size limit (default 50 MB; a file exactly at the limit is accepted), THEN THE Backend SHALL reject the file without storing it or assigning a doc_id, leaving the Deal's existing Documents unchanged, and return a message stating the limit in MB.
5. IF a PDF page yields no extractable text (0 non-whitespace characters returned by PyMuPDF), THEN THE Document_Processor SHALL record that page as "no text layer", keep the Document stored and report the affected 1-based physical page numbers to the Analyst in the upload result.
6. WHEN a Document is stored, THE Frontend SHALL list it in the Deal's document list with its doc_id, display name, document type, period covered, audited flag and total page count.
7. IF the Analyst submits an upload with the document type, period covered or audited flag missing, or with a period covered longer than 50 characters, THEN THE Frontend SHALL block the submission, mark each missing or invalid field and send no file to the Backend.
8. IF every page of a Document is recorded as "no text layer", THEN THE Document_Processor SHALL exclude that Document from Section 2 extraction and inform the Analyst that the Document has no extractable text.

### Requirement 4: Document Processing for Extraction

**User Story:** As an Analyst, I want the documents prepared with exact page markers, so that every extracted item can be traced to the physical PDF page.

#### Acceptance Criteria

1. WHEN a Document is stored, THE Document_Processor SHALL use PyMuPDF to extract and store the text of every page of that Document together with its doc_id and its 1-based physical page number, such that the number of stored pages equals the physical page count of the PDF, and SHALL store any page that yields no extractable text with empty text marked "no text layer" and report the affected doc_id and page numbers to the Analyst as a warning.
2. THE Document_Processor SHALL prefix the text of each page sent to the LLM with that page's Page_Tag on its own line, where doc_id, doc_name and n equal the stored values for that page, and SHALL NOT send any page text to the LLM without its Page_Tag.
3. WHEN preparing an extraction request for the business scope or for the debt and financing scope, THE Document_Processor SHALL select, from all Documents of the Deal not marked as failed, every page whose text contains at least one keyword from that scope's configurable keyword list using case-insensitive matching, and SHALL include a page that matches both scopes in the requests of both scopes.
4. IF the number of selected pages for one scope exceeds the configured page limit (default 30 pages, configurable from 1 to 200), THEN THE Document_Processor SHALL split the selected pages into consecutive requests of at most the page limit each, ordered by doc_id number ascending (D1, D2, ..., D10) and then by page number ascending, with each selected page appearing in exactly one request and no page's text divided across requests.
5. WHEN all split requests for one scope have returned results, THE Document_Processor SHALL merge the results into a single result for that scope ordered by doc_id number ascending and then by page number ascending.
6. IF PyMuPDF cannot open a Document (corrupted file, password-protected file or non-PDF content), THEN THE Document_Processor SHALL mark that Document as failed, exclude it from all extraction requests, display an error message to the Analyst indicating the doc_id and the reason, and retain all other Documents and their stored page text unchanged.
7. IF no page of the Deal's non-failed Documents matches the keyword list of a scope, THEN THE Document_Processor SHALL send no extraction request for that scope and display a message to the Analyst indicating that no relevant pages were found for that scope.

### Requirement 5: Extract Business Information (Section 2A)

**User Story:** As an Analyst, I want the AI to extract qualitative business information from the documents, so that I understand who the borrower is.

#### Acceptance Criteria

1. WHEN the Analyst starts extraction for a Deal that has at least one Document, THE Extraction_Service SHALL send the business-scope pages selected by the Document_Processor to the LLM_Client and request these nine business fields in this fixed order: business description, industry and business model, key revenue drivers, main products / services, geographic exposure, main customers, main suppliers, capital intensity and major investment plans, management and ownership; and SHALL store the results in the same order.
2. THE Extraction_Service SHALL require each extracted item to contain a non-empty statement, the doc_id of a Document of the same Deal, a page number that matches a Page_Tag included in the same LLM request, a section heading, and a verbatim supporting text excerpt of 1 to 500 characters.
3. IF the LLM returns no item for a business field, or every returned item for that field is rejected under criterion 5, THEN THE Extraction_Service SHALL record that field with a null statement and the issue "Not available".
4. THE Extraction_Service SHALL limit each extracted statement to one fact of at most 2 sentences and at most 300 characters, and SHALL accept at most 5 extracted items per business field.
5. IF an extracted item is missing a required element from criterion 2, cites a doc_id and page pair that matches no Page_Tag in the same LLM request, or exceeds the limits in criterion 2 or 4, THEN THE Extraction_Service SHALL reject that item, keep it out of the Evidence_Store, and record the rejection reason against the business field so the Frontend shows it to the Analyst.
6. IF the LLM_Client returns an error, gives no response within the configured timeout (default 120 seconds), or returns output that does not match the Section 2A JSON output schema, THEN THE Extraction_Service SHALL retry that request; IF the retries also fail, THEN THE Extraction_Service SHALL stop Section 2A extraction for the Deal, THE Frontend SHALL show an error message saying Section 2A extraction failed, and THE Backend SHALL keep the Deal's stored Documents and any earlier stored Section 2A results unchanged.
7. IF the Analyst starts extraction for a Deal with no Documents, or with no page matching the business-scope keyword list, THEN THE Extraction_Service SHALL not call the LLM_Client, and THE Frontend SHALL show a message that no business-scope pages are available for extraction.

### Requirement 6: Extract Debt and Financing Information (Section 2B)

**User Story:** As an Analyst, I want the AI to extract the borrower's existing debt and financing arrangements, so that I can judge existing obligations against the new request.

#### Acceptance Criteria

1. WHEN the Analyst starts extraction for a Deal, THE Extraction_Service SHALL send the Section 2B prompt with the pages selected by the Document_Processor's debt and financing keyword list, and SHALL request these fields in this fixed order: existing debt obligations, debt maturity profile, interest obligations, secured versus unsecured debt, existing financing arrangements, financial covenants, upcoming maturities and refinancing requirements, where each field may hold zero or more items.
2. THE Extraction_Service SHALL require each debt and financing item to contain the statement, the doc_id and page taken from a Page_Tag included in that request, the section heading, and a verbatim supporting text excerpt of at most 500 characters, with any amount, interest rate or date quoted exactly as printed in the excerpt, including its currency, unit and scale wording (e.g. "in millions").
3. IF no information is found for a debt and financing field, or no Document page matches the debt and financing keyword list, THEN THE Extraction_Service SHALL record each affected field with a null statement and the issue "Not available".
4. IF two or more Documents state different amounts, interest rates or dates for the same debt item as of the same period, THEN THE Extraction_Service SHALL record the item with the issue "Conflicting", list every candidate with its statement, doc_id, page and supporting text excerpt, and select none of the candidates as the preferred value.
5. THE Extraction_Service SHALL limit each debt and financing statement to one fact of at most 2 sentences, and SHALL reject any statement containing a figure that does not appear verbatim in that item's supporting text excerpt, including sums, averages, currency conversions or ratios computed by the LLM.
6. IF a returned debt and financing item is missing a required element, cites a doc_id and page not present in the request's Page_Tags, or breaks criterion 5, THEN THE Extraction_Service SHALL discard that item without assigning an Evidence_ID, and SHALL record the issue "Invalid output" against the field so the Analyst can see the discarded item.
7. IF the LLM_Client call for Section 2B fails, exceeds the configured timeout (default 120 seconds), or returns output that is not valid JSON matching the Section 2B schema after the configured number of retries (default 2), THEN THE Extraction_Service SHALL mark Section 2B extraction as failed, show the Analyst an error message indicating that debt and financing extraction failed and can be re-run, and keep the Deal_Intake_Fields, Documents and Section 2A results unchanged.

### Requirement 7: Evidence IDs and Passage Verification (Section 2C)

**User Story:** As an Analyst, I want every extracted item tied to a located passage, so that I can trust or challenge each citation.

#### Acceptance Criteria

1. WHEN an extracted item with a non-null statement passes schema validation, THE Backend SHALL assign the item an Evidence_ID consisting of `EV-` followed by a sequence number zero-padded to at least 3 digits (EV-001, EV-002, ...), numbered in extraction order (business information fields first, then debt and financing fields, each in their fixed field order, then by item order within a field), and store the Evidence_Record in the Deal's Evidence_Store.
2. WHEN an Evidence_Record is created for a Document, THE Passage_Locator SHALL search only the page of the original uploaded PDF identified by the record's doc_id and 1-based physical page number for the supporting text excerpt, before the Evidence_Record is stored.
3. WHEN the Passage_Locator finds the normalised supporting text excerpt as one contiguous match within the normalised text of the referenced page, THE Backend SHALL store the location status "Located" and the match position as the page number plus the bounding rectangle(s) of the matched text on that page.
4. IF the Passage_Locator finds no contiguous match for the normalised supporting text excerpt on the referenced page, THEN THE Backend SHALL store the location status "Not located", add the issue "Not located" to the Evidence_Record, keep the Evidence_ID and extracted statement unchanged, and flag the Evidence_Record for Analyst review.
5. THE Passage_Locator SHALL apply the same normalisation to the excerpt and the page text before comparing, in this order: (a) remove a hyphen at the end of a line and join the text either side of the line break; (b) replace every run of whitespace characters, including line breaks, with a single space and trim leading and trailing spaces; (c) convert all letters to lower case; (d) replace typographic single and double quotes with straight quotes; (e) replace en dashes and em dashes with a hyphen; any other character difference SHALL count as a non-match.
6. THE Backend SHALL ensure that no two Evidence_Records in a Deal's Evidence_Store share the same Evidence_ID, and SHALL not reassign an `EV-###` number already used within that Deal, including when extraction is run again for that Deal.
7. WHEN extraction completes, THE Frontend SHALL display every extracted item in two groups (business information, then debt and financing) in the fixed field order, showing for each item its Evidence_ID (or "None" for "Not available" fields), statement, document name, page number, location status and issues ("Not available", "Conflicting", "Not located"), with each flagged Evidence_Record marked by a text label rather than by colour alone.
8. IF an extracted item has a null statement with the issue "Not available", THEN THE Backend SHALL record the field without assigning an Evidence_ID and without invoking the Passage_Locator.
9. IF an Evidence_Record's doc_id does not match an uploaded Document of the Deal, or its page number is less than 1 or greater than that Document's page count, or its supporting text excerpt is empty after normalisation, THEN THE Backend SHALL store the location status "Not located", add an issue indicating the invalid reference or empty excerpt, and flag the Evidence_Record for Analyst review.

### Requirement 8: Load the Financial Database (Section 2D)

**User Story:** As an Analyst, I want historical metrics loaded directly from the financial database, so that no figure is extracted or calculated by the AI.

#### Acceptance Criteria

1. THE Backend SHALL read the Financial_Database path from configuration, resolve a relative path against the project folder, and use `intel_quarterly_ratios.csv` in the project folder when no path is configured.
2. WHERE the Analyst uploads a replacement CSV for a Deal, THE CSV_Loader SHALL use the uploaded CSV instead of the configured Financial_Database for that Deal only, and other Deals SHALL continue to use their own Financial_Database.
3. WHEN the Section 2 processing of a Deal starts, THE CSV_Loader SHALL load that Deal's Financial_Database with Pandas, treating the first column (header "Metric") as the metric label and every other column as a period, and build the Financial_Dataset with one entry per metric row per period column (40 entries for the 10 rows x 4 period columns of `intel_quarterly_ratios.csv`).
4. THE CSV_Loader SHALL map each metric label to a Canonical_Metric after trimming surrounding whitespace and ignoring letter case, using exactly these labels: "Revenue Growth" -> REVENUE_GROWTH, "EBITDA Margin" -> EBITDA_MARGIN, "Debt/EBITDA" -> DEBT_EBITDA, "Interest Coverage" -> INTEREST_COVERAGE, "Current Ratio" -> CURRENT_RATIO, "Debt-Service Coverage Ratio (DSCR)" -> DSCR, "Operating Cash Flow" -> OPERATING_CASH_FLOW, "Operating Cash Flow Margin" -> OCF_MARGIN, "Working Capital" -> WORKING_CAPITAL, "Days Sales Outstanding (DSO)" -> DSO (e.g. "Operating Cash Flow " maps to OPERATING_CASH_FLOW).
5. THE CSV_Loader SHALL parse each period column header of the form "Q<n> <year> (<Mon> <day> <year>)", where n is 1 to 4, year is four digits and Mon is a three-letter English month abbreviation, into a period label "Q<n>-<year>" and a period end date (e.g. "Q2 2026 (Jun 27 2026)" becomes "Q2-2026" with end date 27 June 2026).
6. THE CSV_Loader SHALL order periods in the Financial_Dataset by period end date, oldest first, regardless of the column order in the CSV (for `intel_quarterly_ratios.csv`: Q3-2025, Q4-2025, Q1-2026, Q2-2026).
7. THE CSV_Loader SHALL assign each Financial_Dataset value the Evidence_ID `CSV-<METRIC_KEY>-<PERIOD>`, where METRIC_KEY is the Canonical_Metric name and PERIOD is the period label (e.g. `CSV-DSCR-Q2-2026`), and SHALL store one Evidence_Record per value in the Evidence_Store containing the file name, the metric label as written, the original column header and the cell display value.
8. WHERE the Financial_Database contains a borrower identifier column (header "Borrower", ignoring letter case), THE CSV_Loader SHALL select only the rows whose borrower value equals the Deal's `DI-BORROWER` value after trimming surrounding whitespace and ignoring letter case, and SHALL stop loading and report "No rows match the borrower" to the Analyst when zero rows match.
9. IF the Financial_Database contains no borrower identifier column, THEN THE CSV_Loader SHALL ask the Analyst to confirm that the whole file belongs to the Deal's borrower, build the Financial_Dataset only after the Analyst confirms, record "Database has no borrower identifier" as an information gap, and stop loading without building a Financial_Dataset when the Analyst declines.
10. IF a metric label matches no Canonical_Metric, THEN THE CSV_Loader SHALL retain the row as an additional metric with the flag "Unrecognised metric", using as METRIC_KEY the trimmed label in upper case with every run of non-alphanumeric characters replaced by a single underscore, and SHALL keep the row out of the ten Canonical_Metric entries.
11. IF a period column header cannot be parsed per criterion 5, THEN THE CSV_Loader SHALL stop loading, report the unparseable header text to the Analyst, store no partial Financial_Dataset or Evidence_Records for that load, and leave any previously built Financial_Dataset of the Deal unchanged.
12. IF the Financial_Database file does not exist, cannot be read by Pandas, has no data rows, has no first column headed "Metric", or has no period column, THEN THE CSV_Loader SHALL stop loading, report the specific reason and the file name to the Analyst, and leave any previously built Financial_Dataset of the Deal unchanged.
13. IF two metric rows map to the same Canonical_Metric, or two period columns parse to the same period label, THEN THE CSV_Loader SHALL stop loading, report the duplicated metric label or period header text to the Analyst, and leave any previously built Financial_Dataset of the Deal unchanged.
14. IF an uploaded replacement file does not have the `.csv` extension or exceeds 5 MB, THEN THE Backend SHALL reject the upload with an error message indicating the reason and keep the Deal's current Financial_Database and Financial_Dataset unchanged.

### Requirement 9: Parse and Format Financial Database Values

**User Story:** As an Analyst, I want CSV values parsed faithfully, so that figures shown and checked match the database exactly.

#### Acceptance Criteria

1. WHEN the CSV_Loader reads a cell whose text, after trimming leading and trailing whitespace, consists of an optional leading "-", one or more digits, an optional "." followed by one or more digits, and the suffix "%", THE CSV_Loader SHALL store unit type "percent" and a parsed value equal to the written number in percentage points without rescaling (e.g. "25.40%" parses to 25.40 and "-4.11%" parses to -4.11).
2. WHEN the CSV_Loader reads a cell whose trimmed text consists of an optional leading "-", one or more digits, an optional "." followed by one or more digits, and the lowercase suffix "x", THE CSV_Loader SHALL store unit type "multiple" and a parsed value equal to the written number (e.g. "5.6x" parses to 5.6 and "-11.88x" parses to -11.88).
3. WHEN the CSV_Loader reads a cell whose trimmed text consists of an optional leading "-", one or more digits and an optional "." followed by one or more digits, with no suffix, THE CSV_Loader SHALL store a parsed value equal to the written number, with unit type "days" for the DSO Canonical_Metric and unit type "amount" for every other Canonical_Metric (e.g. "22.8" for DSO parses to 22.8 days and "7006" for OPERATING_CASH_FLOW parses to 7006 amount).
4. THE Financial_Dataset SHALL keep each parsed cell's display value character-for-character identical to the CSV cell text after trimming leading and trailing whitespace, including the sign, every trailing zero and the suffix (e.g. "25.40%", "4.11x", "5.6x" and "0.00%" are stored unchanged).
5. IF a cell's trimmed text is empty or does not match the formats in criteria 1-3 (e.g. "N/A", "-", "7,006", "5.6 x", "$7006"), THEN THE CSV_Loader SHALL store a null parsed value, the display value "Not available in database" and an Anomaly_Flag "unparseable value" for that cell, and SHALL continue loading every remaining cell of the Financial_Database without aborting.
6. THE Value_Formatter SHALL render a parsed value as a string with no spaces and no thousands separators, containing a leading "-" for negative values, exactly the number of digits after the decimal point that the original display value had (zero digits means no "." is written), and the suffix "%" for unit type "percent", "x" for unit type "multiple", or no suffix for unit types "days" and "amount".
7. FOR ALL cells that parse under criteria 1-3, parsing with the CSV_Loader and then formatting with the Value_Formatter SHALL produce a string identical to the stored display value (e.g. "5.6x" gives "5.6x", "4.11x" gives "4.11x", "25.40%" gives "25.40%"), and parsing that formatted string again SHALL produce the same parsed value, unit type and number of decimal digits (round-trip property).
8. THE CSV_Loader SHALL record, for each value parsed under criteria 1-3, the number of digits written after the decimal point in the display value (e.g. 0 for "7006", 1 for "5.6x", 2 for "25.40%"), so that values of the same metric written with different decimal places each keep their own precision.

### Requirement 10: Flag Unusual Database Values

**User Story:** As an Analyst, I want unusual values highlighted, so that I review them before relying on the analysis.

#### Acceptance Criteria

1. THE CSV_Loader SHALL store each parsed value in the Financial_Dataset exactly as parsed from the CSV, including a parsed value of exactly zero, and SHALL NOT replace, exclude or set to null any value because an Anomaly_Flag is attached to it.
2. WHEN a parsed value is exactly zero (e.g. "0.00%", "0.00x", "0"), THE CSV_Loader SHALL attach the Anomaly_Flag "zero value" to that value; a null parsed value SHALL NOT receive this flag.
3. WHEN a parsed value is less than zero for any metric other than REVENUE_GROWTH, THE CSV_Loader SHALL attach the Anomaly_Flag "negative value" to that value; a null parsed value SHALL NOT receive this flag.
4. WHEN both parsed values of two adjacent periods (in oldest-to-newest order) of the same metric are non-null and the absolute change from the earlier to the later period is strictly greater than the configured large-swing threshold for the metric's unit type, THE CSV_Loader SHALL attach the Anomaly_Flag "large swing" to the later period's value only, using the configurable defaults: "percent" 10.0 percentage points, "multiple" 2.0x, "days" 5.0 days, and "amount" 50% of the absolute earlier value (where an earlier value of zero followed by a non-zero later value counts as a large swing); the oldest period SHALL never receive this flag (e.g. with the defaults, DSCR Q4-2025, 1.45x to 11.34x, is flagged).
5. WHEN a metric's values have unit type "amount", THE CSV_Loader SHALL attach the Anomaly_Flag "unit not stated" to every value of that metric and record exactly one information gap per metric naming the metric label as written in the CSV.
6. THE CSV_Loader SHALL store every Anomaly_Flag in both the Financial_Dataset entry and the Evidence_Record of the flagged value, keeping all flags when one value has more than one, in the fixed order: unparseable value, zero value, negative value, large swing, unit not stated.
7. WHEN the Dashboard or the financial review screen displays a flagged value, THE Frontend SHALL show, next to that value, its Evidence_ID and the text of every Anomaly_Flag attached to it, so that each flag is identifiable without relying on colour alone.
8. IF a configured large-swing threshold is missing, non-numeric, or less than or equal to zero, THEN THE CSV_Loader SHALL apply the default threshold for that unit type from criterion 4 and report to the Analyst each unit type for which the default was applied.
9. WHEN the Financial_Dataset is built, THE Frontend SHALL display on the financial review screen the total number of flagged values and a list of each flagged value with its metric label, period label, display value and flag text.

### Requirement 11: Unavailable Metrics

**User Story:** As an Analyst, I want metrics missing from the database clearly marked, so that conclusions never depend on data that was not supplied.

#### Acceptance Criteria

1. WHEN the Backend builds the Dashboard data or the input for the Trend_Analyst, Risk_Analyst or Memo_Generator, THE Backend SHALL supply the exact text "Not available in database" for every Unavailable_Metric included, with no numeric value, no estimated or derived value, no Evidence_ID and no Comparison_Record for that metric.
2. WHEN the Backend builds the Memo_Generator input, THE Backend SHALL include an information-gap list that names, exactly once each, every Unavailable_Metric referenced by the Dashboard or by the divergence patterns analysed by the Trend_Analyst.
3. WHEN the CSV_Loader loads a Financial_Database that contains no row for a Canonical_Metric, THE CSV_Loader SHALL treat that Canonical_Metric as an Unavailable_Metric for all periods, create no Financial_Dataset entries or Evidence_IDs for it, and continue loading the remaining Canonical_Metrics.
4. WHEN the Frontend displays a Dashboard chart that covers an Unavailable_Metric, THE Frontend SHALL show the text "Not available in database" for that metric and plot no data points for it.
5. IF a Trend_Analyst, Risk_Analyst or Memo_Generator output states a numeric value or a direction of change for an Unavailable_Metric, THEN THE Number_Verifier SHALL mark that claim as failed verification, the same way it marks a figure that does not match the Financial_Dataset.

### Requirement 12: Comparison Records

**User Story:** As an Analyst, I want period-over-period changes computed by code, so that the AI quotes comparisons instead of calculating them.

#### Acceptance Criteria

1. WHEN the CSV_Loader completes building the Financial_Dataset, THE Backend SHALL create, for each Canonical_Metric, one Comparison_Record for each pair of adjacent periods in Financial_Dataset order (oldest to newest) where both parsed values are non-null, so that a metric with N periods and no null values has exactly N-1 Comparison_Records, each holding the from period, to period, change, direction and the Evidence_IDs of both source values.
2. THE Backend SHALL compute each change from the two parsed values as written in the Financial_Dataset, including values of exactly zero, as a signed value in the metric's native unit: (to - from) in percentage points for "percent", (to - from) in "x" for "multiple", (to - from) in days for "days", and (to - from) / |from| x 100 in relative percent for "amount", displayed with an explicit sign and rounded to 1 decimal place for percentage points, days and relative percent and to 2 decimal places for "x".
3. THE Backend SHALL set each Comparison_Record's direction by comparing the unrounded change with the Stable_Band of the metric's unit type: "~" when -Stable_Band <= change <= +Stable_Band, "up" when change > +Stable_Band, and "down" when change < -Stable_Band.
4. WHEN the Backend starts, THE Backend SHALL load one Stable_Band value per unit type from configuration, with defaults of 1.0 percentage point for "percent", 0.10x for "multiple", 5.0% relative for "amount" and 3 days for "days".
5. THE Backend SHALL mark every Comparison_Record as a quarter-on-quarter comparison whose from period immediately precedes its to period in Financial_Dataset order, and SHALL create no year-on-year, multi-period or cross-gap comparisons.
6. THE Backend SHALL build every Comparison_Record from two periods of one Canonical_Metric only and SHALL derive no value other than change and direction, such that for every Comparison_Record, recomputing the change from the two cited Financial_Dataset parsed values with the formula in criterion 2 gives the stored unrounded change (invariant property).
7. IF either parsed value in a pair of adjacent periods is null, THEN THE Backend SHALL create no Comparison_Record for that pair and SHALL NOT pair the periods on either side of the null value.
8. IF a metric has unit type "amount" and the from period's parsed value is zero, THEN THE Backend SHALL create the Comparison_Record with a null change, the change display "Not computable", and a direction of "up" if to > 0, "down" if to < 0 and "~" if to = 0.
9. IF a configured Stable_Band value is missing, non-numeric or negative, THEN THE Backend SHALL use the default Stable_Band for that unit type and continue starting.

### Requirement 13: Financial Trend Dashboard (Section 3, Steps 1-2 and 4)

**User Story:** As an Analyst, I want charts of the borrower's metrics with AI commentary beside them, so that I can see the latest position and historical changes at a glance.

#### Acceptance Criteria

1. WHEN the Analyst opens the Dashboard for a Deal that has a Financial_Dataset, THE Dashboard SHALL display five chart panels, each titled with its panel name, in this order: profitability (REVENUE_GROWTH, EBITDA_MARGIN), leverage (DEBT_EBITDA), liquidity (CURRENT_RATIO, WORKING_CAPITAL), cash flow (OPERATING_CASH_FLOW, OCF_MARGIN, DSO) and debt servicing (DSCR, INTEREST_COVERAGE), rendered with the chart library loaded from local files.
2. THE Dashboard SHALL plot each Canonical_Metric as a separate named series positioned by its parsed value across every period of the Financial_Dataset from oldest (left) to newest (right), with the period axis labelled with the CSV period labels, each data point labelled with its display value exactly as stored in the Financial_Dataset plus any Anomaly_Flag text, and each value axis labelled with its unit type, so that metrics with different unit types never share one value axis.
3. THE Dashboard SHALL show beside each charted metric the display value for the newest period and, from the Comparison_Record with the newest to-period, the from period, to period, change and direction ("up", "down" or "~") exactly as supplied by the Backend, or the text "No comparison available" where the metric has no Comparison_Record, with the Frontend deriving no values of its own.
4. THE Dashboard SHALL list in each panel, under the heading "Not available in database", the Unavailable_Metrics assigned to that panel (profitability: Revenue, EBITDA, Net Profit Margin; leverage: Total Debt, Net Debt, Debt / Equity; liquidity: Cash, Short-term Debt, Quick Ratio; cash flow: Capital Expenditure, Free Cash Flow; debt servicing: Interest Expense), together with any of the panel's Canonical_Metrics whose parsed value is null in every period, and SHALL plot no series for those metrics.
5. WHEN a Section 3 analysis is received for the Deal, THE Dashboard SHALL display beside each panel's chart that panel's Trend_Analyst commentary statements, each with its Statement_Label, its cited Evidence_IDs and its Number_Verifier mark ("Numbers verified" or "Number mismatch").
6. THE Dashboard SHALL provide for each panel a data table, reachable by keyboard Tab navigation and exposed to screen readers, listing for every period from oldest to newest the period label and each charted metric's display value and Anomaly_Flag text.
7. IF a Canonical_Metric has a null parsed value for a period, THEN THE Dashboard SHALL plot no point and draw no connecting line for that period, and SHALL show "Not available in database" for that period in the data label, the newest-period value of criterion 3 and the data table.
8. IF the Analyst opens the Dashboard for a Deal that has no Financial_Dataset, THEN THE Dashboard SHALL display no chart panels and a message stating that the Financial_Database CSV must be loaded first.
9. WHILE no Section 3 analysis exists for the Deal, THE Dashboard SHALL display in each panel's commentary area a message stating that the Section 3 analysis has not been run, and SHALL still display the charts, values and data tables.

### Requirement 14: AI Financial Trend Analysis (Section 3, Step 3)

**User Story:** As an Analyst, I want the AI to interpret trends, divergences and repayment capacity, so that I get credit-relevant insight rather than a list of ratios.

#### Acceptance Criteria

1. WHEN the Analyst runs the Section 3 analysis, THE Backend SHALL send the Trend_Analyst the Deal_Intake_Fields, the Section 2 business and debt and financing items with their Evidence_IDs, the Financial_Dataset with its display values, Evidence_IDs and Anomaly_Flags, the Comparison_Records, the list of Unavailable_Metrics and the per-pattern divergence assessability results defined in criterion 3.
2. THE Trend_Analyst SHALL produce commentary for each of the five Dashboard panels (profitability, leverage, liquidity, cash flow, debt servicing) covering every Canonical_Metric charted in that panel, stating for each metric: (a) the direction of each of its Comparison_Records, with "up" described as an increase, "down" as a decrease and "~" as stable; (b) the latest-period display value alongside the display values of all earlier periods; and (c) "sustained improvement" or "sustained deterioration" only when the two or more most recent Comparison_Records of that metric share the same non-"~" direction, where "down" counts as improvement for DEBT_EBITDA and DSO and "up" counts as improvement for all other Canonical_Metrics.
3. THE Backend SHALL determine, for each of the five divergence patterns in the Project Details (Revenue up with EBITDA down; Revenue up with Operating Cash Flow down; Debt up with EBITDA down; Debt up with DSCR down; Cash down with Short-term Debt up), whether every metric named in the pattern is a Canonical_Metric present in the Financial_Dataset, marking a pattern "assessable" only when all named metrics are present and without substituting a different Canonical_Metric for a named metric, and supply the "assessable" or "not assessable" result for each pattern to the Trend_Analyst.
4. IF a divergence pattern is marked "not assessable", THEN THE Trend_Analyst SHALL report that pattern as "Not assessable: data not available in database", name the Unavailable_Metrics the pattern requires, and make no statement on whether that divergence occurred, and THE Backend SHALL pass that pattern, with the Unavailable_Metrics it requires, to the Memo_Generator as a recorded information gap.
5. THE Trend_Analyst SHALL assign each commentary statement exactly one Statement_Label: Sourced for an observed trend, citing the `CSV-<METRIC_KEY>-<PERIOD>` Evidence_ID of every period the statement references; or ASSUMPTION for a possible explanation drawn from Section 2 items, citing at least one `EV-###` Evidence_ID of the Section 2 item relied on.
6. IF no supplied Section 2 item explains a trend stated in the commentary, THEN THE Trend_Analyst SHALL add the statement "Driver not explained in the documents provided" with the label NOT VERIFIED for that trend and offer no explanation drawn from outside the supplied inputs.
7. THE Trend_Analyst SHALL assess repayment capacity under each of the five dimensions (profitability, cash generation, leverage, liquidity, debt servicing), giving for each dimension at least one statement on evidence that supports and at least one statement on evidence that weakens repayment capacity, or, where no such evidence exists in the inputs, a statement with the label NOT VERIFIED indicating that no supporting or no weakening evidence was identified, without ranking risks, scoring the borrower or giving a lending recommendation.
8. THE Trend_Analyst SHALL attach to each commentary statement one structured comparison claim (metric, from period, to period, direction, quoted change) for every period-over-period comparison stated in the statement's text, with the direction and quoted change copied unchanged from the Comparison_Record for the same metric and periods.
9. THE Trend_Analyst SHALL quote figures only as Financial_Dataset display values or Comparison_Record changes, exactly as supplied, without calculating, rounding, converting, averaging or extracting any figure, including any change between non-consecutive periods.
10. WHEN a commentary statement cites a Financial_Dataset value that carries an Anomaly_Flag, THE Trend_Analyst SHALL treat the value as reported, including zero values, and name the Anomaly_Flag in that statement.
11. IF the Analyst runs the Section 3 analysis before the Financial_Dataset is loaded or before the Section 2 extraction has completed, THEN THE Backend SHALL not call the Trend_Analyst, SHALL display a message naming the missing input, and SHALL leave any existing Section 3 output unchanged.
12. WHEN the Trend_Analyst describes a relationship or divergence between two or more Canonical_Metrics in the Financial_Dataset (e.g. REVENUE_GROWTH vs OCF_MARGIN, DEBT_EBITDA vs DSCR), THE Trend_Analyst SHALL base the statement only on those metrics' Comparison_Record directions and Financial_Dataset display values, label the statement Sourced citing the `CSV-<METRIC_KEY>-<PERIOD>` Evidence_ID of every period referenced, and SHALL NOT present any Canonical_Metric as a proxy for an Unavailable_Metric.

### Requirement 15: Number Verification (Section 3, Step 5)

**User Story:** As an Analyst, I want the backend to check every figure and comparison the AI makes, so that numerical hallucinations are caught before I approve.

#### Acceptance Criteria

1. THE Number_Verifier SHALL treat as a figure every numeric token in a Section 3 statement's text (an optional sign, digits with optional thousands separators, an optional decimal part, and any unit immediately following: "%", "percent", "x", "times", "pp", "percentage point", "percentage points", "days"), excluding: (a) digits inside a period label (Q1 to Q4 followed by a year, e.g. "Q2-2026" or "Q2 2026", or "FY" followed by a year) and digits inside a calendar date; (b) a standalone unsigned four-digit integer from 1900 to 2100 with no decimal part, no thousands separator and no unit; (c) digits inside an Evidence_ID, a statement ID, or the word "Section" followed by a number; (d) an unsigned integer from 1 to 20 immediately followed by "quarter", "quarters", "period" or "periods".
2. THE Number_Verifier SHALL normalise each figure and each comparison value before comparing them by removing thousands separators and any leading "+", converting a Unicode minus sign to "-", removing trailing zeros after the decimal point (and the decimal point if nothing follows it), and mapping "percent" to "%", "times" to "x" and "percentage point(s)" to "pp"; a figure SHALL match a value only when the normalised number and the unit are both identical ("25.4%" matches "25.40%", but "25%" does not match "25.40%" and "4.11" does not match "4.11x"), and for entries with unit type "days" a figure with the unit "days" or with no unit SHALL count as the same unit.
3. WHEN a Section 3 output is received, THE Number_Verifier SHALL check each figure in each statement against: (a) the display values of the Financial_Dataset entries whose Evidence_IDs the statement cites, matched including sign; (b) the change values of the Comparison_Records referenced by the statement's structured comparison claims, matched ignoring sign, using the unit "pp" for "percent" metrics, "%" for "amount" metrics, "x" for "multiple" metrics and "days" for "days" metrics; and (c) the supporting text excerpts of the `EV-###` Evidence_Records the statement cites, where the figure must appear verbatim after normalisation.
4. WHEN a Section 3 output is received, THE Number_Verifier SHALL treat a structured comparison claim as matching only when a Comparison_Record exists for the same metric with an identical from period and to period, the claimed direction equals that record's direction ("up", "down" or "~"), and the quoted change matches the record's change under criterion 2, ignoring sign.
5. IF any figure or structured comparison claim in a statement does not match, THEN THE Number_Verifier SHALL mark the statement "Number mismatch" and list each unmatched figure or claim with one reason ("no matching cited value", "no Comparison_Record for this metric and these periods", "direction differs" or "change differs"), and THE Frontend SHALL display the mark and the list beside the statement in the financial review screen.
6. WHEN every figure and every structured comparison claim in a statement matches, including a statement that contains no figures and no claims, THE Number_Verifier SHALL mark the statement "Numbers verified".
7. THE Number_Verifier SHALL leave each statement's text, cited Evidence_IDs and structured comparison claims unchanged, and SHALL leave Financial_Dataset values and Comparison_Records unmodified.
8. WHEN a Section 3 output is received, THE Number_Verifier SHALL give every statement exactly one mark, either "Numbers verified" or "Number mismatch", before the Frontend displays the Section 3 output to the Analyst.

### Requirement 16: Analyst Approval of the Financial Analysis (Section 3 Gate)

**User Story:** As an Analyst, I want to review, correct and approve the financial analysis, so that only validated analysis flows into risk identification.

#### Acceptance Criteria

1. THE Frontend SHALL show four controls on each Section 3 statement (approve, flag, comment and edit) and, beside the controls, the statement's Verification_Status (initially Pending) and its Number_Verifier mark ("Numbers verified" or "Number mismatch"), where a comment SHALL be 1 to 2,000 characters long.
2. WHEN the Analyst approves, flags or comments on a Section 3 statement, THE Backend SHALL record in the Audit_Trail the action, any comment text, the analyst name and the timestamp, and SHALL set the statement's Verification_Status to Approved for an approve action and to Flagged for a flag action.
3. WHEN the Analyst saves an edit to a Section 3 statement, THE Backend SHALL store the original text, the corrected text, the analyst name and the timestamp in the Audit_Trail, re-run the Number_Verifier on the corrected text, reset the statement's Verification_Status to Pending, and send the new Number_Verifier mark to the Frontend for display on that statement.
4. IF the edited text of a Section 3 statement is empty, contains only whitespace or is longer than 5,000 characters, THEN THE Backend SHALL reject the edit and keep the previous statement text, Verification_Status and Number_Verifier mark, and THE Frontend SHALL show an error message saying why the edit was rejected.
5. WHEN the Analyst approves the financial analysis and none of the conditions in criterion 6 apply, THE Backend SHALL set the financial analysis to approved and record the approval, the analyst name and the timestamp in the Audit_Trail.
6. IF the Analyst tries to approve the financial analysis while the analyst name is empty or longer than 100 characters, at least one Section 3 statement has the Verification_Status Pending, or at least one Section 3 statement is marked "Number mismatch" and its Verification_Status is not Flagged, THEN THE Backend SHALL reject the approval and keep the financial analysis unapproved, and THE Frontend SHALL list each blocking statement with its reason.
7. WHILE the financial analysis is unapproved, THE Backend SHALL reject requests to run the Section 4 analysis without calling the LLM_Client, with an error message stating that Section 3 approval is required.
8. WHEN the Analyst edits a Section 3 statement or changes its Verification_Status after the financial analysis is approved, THE Backend SHALL return the financial analysis to unapproved and record the revocation, the analyst name and the timestamp in the Audit_Trail.

### Requirement 17: Identify Key Risks and Suggest Mitigants (Section 4)

**User Story:** As an Analyst, I want the most material, evidenced risks with mitigants and proposed terms, so that I can structure the facility.

#### Acceptance Criteria

1. WHEN the Analyst runs Section 4 after the Section 3 approval is recorded, THE Risk_Analyst SHALL receive the approved Section 3 statements (with Analyst-corrected text replacing the original text), the Section 2 items with their Evidence_IDs, the Financial_Dataset with its Anomaly_Flags, the Comparison_Records, the list of Unavailable_Metrics and the Deal_Intake_Fields.
2. THE Risk_Analyst SHALL return between 3 and 5 risks (fewer only as permitted by criterion 3), each with exactly one identified risk, exactly one category (Financial, Business and Operational, or Industry and External), evidence, exactly one impact (High, Medium or Low), exactly one likelihood (High, Medium or Low), at least one possible mitigant and at least one proposed term or monitoring condition.
3. IF fewer than 3 risks each cite at least one Evidence_ID that passes the Reference_Validator, THEN THE Risk_Analyst SHALL return only those evidenced risks (0 to 2) and state in the limitations that fewer than 3 risks are supported by the evidence provided.
4. THE Risk_Analyst SHALL assign each risk a consecutive rank starting at 1, ordering by impact (High before Medium before Low), then likelihood (High before Medium before Low), then risks citing at least one CSV Evidence_ID before risks citing only `EV-###` or `DI-<FIELD>` Evidence_IDs.
5. THE Risk_Analyst SHALL state each risk's evidence as the cited metrics' CSV display values with their period labels, the time horizon relative to the Deal_Intake_Field tenor, and the business context from Section 2 items, citing the Evidence_ID of every value and item used, naming any Anomaly_Flag on a cited value, and describing any Unavailable_Metric as "Not available in database" without estimating a value.
6. THE Risk_Analyst SHALL classify each proposed term as exactly one of Covenant, Reporting / Monitoring or Structural Protection.
7. IF a proposed term contains a numeric threshold (any ratio level, amount, percentage, number of days or count), THEN THE Risk_Analyst SHALL label the term ASSUMPTION and state "Illustrative; analyst to calibrate against credit policy."
8. THE Frontend SHALL display the risks as a table with one row per risk in rank order and the columns Identified Risk (showing rank, category, impact and likelihood), Evidence (showing the cited Evidence_IDs), Possible Mitigant and Proposed Term / Monitoring Condition (showing the term classification and any ASSUMPTION label), with the disclaimer "Suggestions for the analyst's consideration only, not automatic lending decisions." shown above the table whenever the table is displayed, including when it has 0 rows.
9. WHEN a Section 4 output is received, THE Number_Verifier SHALL check that every number in each risk's evidence equals the display value of a cited Financial_Dataset entry, the change of a cited Comparison_Record or text in a cited Evidence_Record excerpt, and mark each non-matching risk "Number mismatch" with the unmatched values displayed to the Analyst.
10. IF a Section 4 output contains more than 5 risks, a risk missing a field required by criterion 2, a category, impact, likelihood or term classification outside the listed values, or risks not in the order defined by criterion 4, THEN THE Backend SHALL fail validation and apply the LLM retry process (up to 2 retries, then stop the section and display the validation errors to the Analyst).
11. THE Risk_Analyst SHALL NOT include any approval, decline, credit decision or lending recommendation in the Section 4 output.

### Requirement 18: Generate the Credit Memo with Evidence (Section 5)

**User Story:** As an Analyst, I want a structured credit memo citing existing evidence, so that a credit committee can read it and an auditor can trace it.

#### Acceptance Criteria

1. WHEN the Analyst runs Section 5, THE Memo_Generator SHALL receive the Deal_Intake_Fields (Section 1), the Section 2 items, the approved Section 3 analysis including Analyst corrections, the Section 4 risk table, the Evidence_Store, the Financial_Dataset, the Comparison_Records and the recorded information gaps.
2. THE Memo_Generator SHALL produce exactly 7 sections containing exactly the following 22 subsections, in this fixed order, with no additional sections or subsections: 1 Executive Summary (borrower and facility, purpose, key strengths and risks); 2 Business Overview (business model and industry, revenue sources, management / ownership); 3 Financial Analysis (revenue and profitability, cash flow and liquidity, leverage and historical trends); 4 Repayment Capacity (cash generation, DSCR and debt-servicing capacity, existing debt obligations); 5 Key Credit Risks (financial, business and operational, industry and external); 6 Risk Mitigants / Proposed Loan Structure (suggested covenants, collateral and security, tenor and repayment structure, monitoring requirements); 7 Information Gaps (missing information or documents, conflicting information, unsupported statements).
3. IF a memo subsection has no content supported by a cited Evidence_ID, THEN THE Memo_Generator SHALL return for that subsection exactly one Memo_Statement with the text "Not available in the documents provided." and the Statement_Label NOT VERIFIED.
4. THE Memo_Generator SHALL cite only Evidence_IDs present in its Section 5 input, SHALL create no Evidence_IDs of its own, and SHALL cite at least one Evidence_ID in every Memo_Statement labelled Sourced.
5. THE Memo_Generator SHALL quote only figures that appear exactly as display values in the Financial_Dataset, as changes in Comparison_Records, or as values in Evidence_Records or Deal_Intake_Fields, and SHALL calculate no ratios or other figures.
6. THE Memo_Generator SHALL include in Information Gaps one Memo_Statement for each recorded information gap, for each Unavailable_Metric referenced in the Section 3, Section 4 or Section 5 outputs, and for each Anomaly_Flag in the Financial_Dataset, with each Anomaly_Flag statement naming the metric, period, display value and flag type and citing that value's CSV Evidence_ID.
7. THE Memo_Generator SHALL include in the Repayment Capacity subsection "DSCR and debt-servicing capacity" a Memo_Statement labelled NOT VERIFIED stating that pro-forma debt service including the requested facility has not been assessed and must be assessed by the Analyst.
8. THE Credit_Analysis_App SHALL include in the memo no statement recommending that the facility be approved, declined or approved with conditions, and no overall credit decision.
9. WHEN the memo is received, THE Backend SHALL assign each Memo_Statement a statement ID, sequential from 1 in memo order and unique within the Deal, set its Verification_Status to Pending unless the Reference_Validator sets it to Flagged, and link each cited Evidence_ID to its Evidence_Record, Financial_Dataset entry or Deal_Intake_Field.
10. WHILE no Section 4 output exists for the Deal, THE Backend SHALL reject requests to run Section 5 with a message stating that Section 4 must be completed first.
11. IF a memo subsection refers to an Unavailable_Metric, THEN THE Memo_Generator SHALL state "Not available in database" for that metric with the Statement_Label NOT VERIFIED and SHALL quote no figure for it.
12. WHEN the memo is received, THE Number_Verifier SHALL check every number in each Memo_Statement against its cited Financial_Dataset entries, Comparison_Records, Evidence_Records and Deal_Intake_Fields, and mark the statement "Numbers verified" if all match or "Number mismatch" with the unmatched values listed.

### Requirement 19: Reference Validation

**User Story:** As an Analyst, I want citations that do not exist caught automatically, so that the memo never points to fabricated sources.

#### Acceptance Criteria

1. WHEN an LLM output from Section 2, 3, 4 or 5 is received, THE Reference_Validator SHALL check every cited Evidence_ID by exact, case-sensitive match against the Evidence_IDs of that Deal's Evidence_Store (`EV-###`), Financial_Dataset (`CSV-<METRIC_KEY>-<PERIOD>`) and Deal_Intake_Fields (`DI-<FIELD>`), and SHALL treat as unknown any Evidence_ID that has no match, including a malformed Evidence_ID or one that belongs to another Deal.
2. WHEN the Reference_Validator finishes checking an LLM output, THE Reference_Validator SHALL return a result of pass or fail, listing each unknown Evidence_ID together with the ID of the item or Memo_Statement that cites it.
3. IF a Section 2, 3, 4 or 5 output cites one or more unknown Evidence_IDs, THEN THE Reference_Validator SHALL fail validation of that output, and THE Backend SHALL not store the failed output and SHALL start the LLM retry process (up to 2 retries), sending the list of unknown Evidence_IDs back as the validation errors.
4. IF a Section 5 Memo_Statement still cites one or more unknown Evidence_IDs after the 2 retries, THEN THE Reference_Validator SHALL set that statement's Verification_Status to Flagged with the note "Reference does not exist" naming each unknown Evidence_ID, leave the statement text unchanged and keep the links to its other cited Evidence_IDs, and THE Backend SHALL not stop Section 5.
5. IF a Memo_Statement with the Statement_Label Sourced or ASSUMPTION cites zero Evidence_IDs, THEN THE Reference_Validator SHALL set that statement's Verification_Status to Flagged with the note "No supporting reference".
6. WHEN every Evidence_ID cited by a Memo_Statement exists in the Deal and the statement meets neither the criterion 4 nor the criterion 5 flag condition, THE Reference_Validator SHALL leave that statement's Verification_Status as Pending.

### Requirement 20: Analyst Review and Source Verification (Section 6)

**User Story:** As an Analyst, I want to open the source behind each memo statement and approve or flag it, so that I verify the memo rather than trust it.

#### Acceptance Criteria

1. THE Frontend SHALL display each Memo_Statement on the Section 6 review screen with its statement ID, text, Statement_Label, Verification_Status as text, and each cited Evidence_ID as a separate control that can be activated by mouse click or keyboard.
2. WHEN the Analyst activates a document Evidence_ID, THE Backend SHALL retrieve the Evidence_Record, run the Passage_Locator on the referenced PDF page, and return within 5 seconds the document name, 1-based page number, supporting excerpt, and an image of that page rendered by the Backend with PyMuPDF at 150 dots per inch with a highlight drawn over every match location the Passage_Locator returned.
3. WHEN the Analyst activates a CSV Evidence_ID, THE Backend SHALL return the CSV file name, the metric label as written in the CSV, the period column header, the cell display value as written in the CSV, and the name of each Anomaly_Flag on that value, or "None" if the value has no Anomaly_Flags.
4. WHEN the Backend returns a source for an activated Evidence_ID, THE Frontend SHALL display every returned field in a source panel on the same screen as the Memo_Statement, keeping the statement visible.
5. IF the Passage_Locator returns "not located" for a document Evidence_ID cited by a Memo_Statement the first time that Evidence_ID is activated, THEN THE Backend SHALL return the page image without a highlight together with the supporting excerpt, and set the statement's Verification_Status to Flagged with the note "Source passage not located".
6. THE Frontend SHALL give each Memo_Statement three actions (approve, flag with an optional note of up to 500 characters, and correct the statement text) and SHALL provide one analyst name field of 1 to 100 characters, excluding leading and trailing spaces, that applies to every review action.
7. WHEN the Analyst saves corrected text for a Memo_Statement whose Verification_Status is Approved or Flagged, THE Backend SHALL replace the statement text with the corrected text, keep the original text in the Audit_Trail, and reset the statement's Verification_Status to Pending.
8. WHEN the Memo_Generator output passes the Reference_Validator and a Memo_Statement cites one or more Evidence_IDs, all of them CSV Evidence_IDs whose figures passed the Number_Verifier in the approved Section 3 analysis, and every figure in the statement equals the display value of its cited CSV Evidence_ID, THE Backend SHALL pre-set the statement's Verification_Status to Approved with the note "Verified in Section 3 financial review".
9. WHILE the Section 6 review screen is open, THE Frontend SHALL display the notice "A citation to an existing page does not confirm accuracy. Compare the statement with the source before approving." above the list of Memo_Statements.
10. THE Frontend SHALL let the Analyst filter Memo_Statements by All, Pending, Approved or Flagged, with All as the default and each filter option showing the number of Memo_Statements it matches.
11. IF the referenced Document is not stored for the Deal or the referenced page number is greater than the Document's page count, THEN THE Backend SHALL return an error message indicating the source is unavailable and set the citing Memo_Statement's Verification_Status to Flagged with the note "Source document unavailable".
12. IF the Analyst submits an approve, flag or correct action while the analyst name field is empty or longer than 100 characters, THEN THE Frontend SHALL reject the action with a message indicating that a valid analyst name is required, and leave the statement text and Verification_Status unchanged.
13. IF the Analyst saves corrected text that is empty after removing leading and trailing spaces, or that is longer than 2,000 characters, THEN THE Backend SHALL reject the correction with an error message indicating the length limit, and keep the existing statement text and Verification_Status.

### Requirement 21: Preliminary Support Check (Section 6, optional)

**User Story:** As an Analyst, I want an optional AI check of whether an excerpt supports a statement, so that I can prioritise my review.

#### Acceptance Criteria

1. WHERE the support check is enabled in `.env`, WHEN the Analyst requests the support check for a Deal whose memo has been received, THE Support_Checker SHALL assess, through the LLM_Client, each Memo_Statement that cites at least one document Evidence_ID (`EV-###`) existing in the Deal's Evidence_Store, using only the Memo_Statement text and the supporting text excerpts of those cited Evidence_Records.
2. WHERE the support check is enabled in `.env`, THE Support_Checker SHALL return for each assessed Memo_Statement exactly one assessment from the fixed vocabulary Supported, Partially supported or Not supported, with a reason of one sentence of at most 300 characters.
3. WHERE the support check is enabled in `.env`, THE Frontend SHALL display beside each Memo_Statement its latest assessment and reason labelled "AI preliminary check; analyst verification required", or the text "Not checked" for any Memo_Statement that cites no document Evidence_ID, has not been assessed, or has been edited since its latest assessment.
4. THE Support_Checker SHALL leave each Memo_Statement's Verification_Status, note, text and cited Evidence_IDs unchanged, including when the assessment is Not supported.
5. IF the LLM_Client call fails or the Support_Checker output still fails schema or Reference_Validator validation after the 2 retries of the LLM retry process, THEN THE Backend SHALL return an indication that the support check is unavailable for the affected Memo_Statements, leave every Verification_Status unchanged and keep Section 6 review and final PDF generation available.
6. WHERE the support check is disabled in `.env`, THE Credit_Analysis_App SHALL make no Support_Checker LLM call and display no support check request control or assessment.
7. THE PDF_Renderer SHALL exclude every Support_Checker assessment and reason from the Credit Memo PDF.

### Requirement 22: Audit Trail Record

**User Story:** As a reviewer, I want a complete audit trail, so that the chain from source to memo to analyst verification is traceable.

#### Acceptance Criteria

1. WHEN a Deal is created, THE Backend SHALL create exactly one Audit_Trail JSON file for that Deal and record all Audit_Trail entries for that Deal only in that file.
2. WHEN the Analyst changes the Verification_Status or the text of a Memo_Statement, THE Backend SHALL append one Audit_Trail entry containing the statement ID; the statement text before and after the change; the cited Evidence_IDs; the original source data for each cited Evidence_ID (for `EV-###`, the doc_id, doc_name, page and supporting text excerpt; for `CSV-<METRIC_KEY>-<PERIOD>`, the metric label, column header and cell display value; for `DI-<FIELD>`, the Deal_Intake_Field value); the previous and new Verification_Status; the Analyst correction (empty if none was entered); the analyst name; and a timestamp in local time with UTC offset, to the second.
3. WHEN the Number_Verifier completes a check of a Section 3 Trend_Analyst output, THE Backend SHALL append one Audit_Trail entry that lists, for each checked figure or comparison, the claimed value, the matching Financial_Dataset value or Comparison_Record, the result (match or mismatch) and the timestamp.
4. WHEN the LLM_Client returns an output for any LLM task (Extraction_Service, Trend_Analyst, Risk_Analyst, Memo_Generator or Support_Checker), THE Backend SHALL append one Audit_Trail entry containing the prompt name, prompt version, model name, timestamp and an input hash computed over the complete input sent to the LLM, so that identical inputs produce identical hashes.
5. WHEN the Backend appends an Audit_Trail entry, THE Backend SHALL leave every earlier entry unchanged in content and order, and SHALL NOT edit or delete any existing Audit_Trail entry.
6. WHEN the Analyst edits or approves the Section 3 AI analysis, THE Backend SHALL append one Audit_Trail entry containing the Dashboard panel affected, the text before and after the edit (or the approval action), the analyst name and the timestamp.
7. IF the analyst name submitted with a Verification_Status change, a statement text change or a Section 3 edit or approval is empty, whitespace-only or longer than 100 characters, THEN THE Backend SHALL reject the change, keep the item's prior Verification_Status and text, append no Audit_Trail entry, and return an error indicating that a valid analyst name is required.
8. IF the Backend cannot write an Audit_Trail entry for an Analyst-triggered change, THEN THE Backend SHALL leave the change unapplied (prior Verification_Status, statement text and Section 3 approval state retained) and return an error indicating that the audit entry was not saved.

### Requirement 23: Final Credit Memo PDF

**User Story:** As an Analyst, I want a final memo PDF that keeps its source references, so that I can submit it to the credit committee.

#### Acceptance Criteria

1. IF the Analyst requests the final memo while one or more Memo_Statements have the Verification_Status Pending, THEN THE Backend SHALL reject the request, generate no Credit Memo PDF and return a message stating the number of Pending Memo_Statements.
2. WHEN every Memo_Statement has the Verification_Status Approved or Flagged and the Analyst requests the final memo, THE PDF_Renderer SHALL generate the Credit Memo PDF containing exactly the 7 memo sections of Requirement 18, numbered 1-7 and titled in this order: Executive Summary; Business Overview; Financial Analysis; Repayment Capacity; Key Credit Risks; Risk Mitigants / Proposed Loan Structure; Information Gaps, with every Memo_Statement in statement ID order using its latest statement text, including any Analyst correction.
3. THE PDF_Renderer SHALL render, immediately after each Memo_Statement's text and in the order cited, each document Evidence_ID as `[<doc_name>, p.<page>]` using the doc_name and page of its Evidence_Record, each CSV Evidence_ID as `[Financial database: <metric label>, <period>]` using the metric label as written in the Financial_Database and the period column header, and each Deal_Intake_Field reference as `[Deal intake: <field name>]`, followed once by the statement ID.
4. THE PDF_Renderer SHALL retain each Flagged Memo_Statement in the Credit Memo PDF, preceded by the text "FLAGGED" and followed by its recorded flag note, and SHALL print the Statement_Label beside each Memo_Statement labelled ASSUMPTION or NOT VERIFIED.
5. THE PDF_Renderer SHALL print the header "AI-generated draft reviewed by the analyst. Not a credit decision." on every page, and print the borrower name, the analyst name and the review date in YYYY-MM-DD format on the first page, where the review date is the date of the latest Verification_Status change recorded in the Audit_Trail.
6. THE PDF_Renderer SHALL name the file `<Borrower>_CreditMemo_<YYYYMMDD>.pdf`, where `<Borrower>` is the borrower name Deal_Intake_Field with each character other than A-Z, a-z, 0-9 and hyphen replaced by an underscore and truncated to 50 characters, and `<YYYYMMDD>` is the local generation date.
7. THE PDF_Renderer SHALL include no approve, decline, recommendation or credit decision field in the Credit Memo PDF.
8. IF the analyst name is empty or whitespace-only when the Analyst requests the final memo, THEN THE Backend SHALL reject the request, generate no Credit Memo PDF and return a message indicating that the analyst name is required.
9. IF the PDF_Renderer fails during Credit Memo PDF generation, THEN THE Backend SHALL return an error message indicating that generation failed, keep no partial PDF file and leave every Verification_Status and Audit_Trail entry unchanged.

### Requirement 24: Audit Trail PDF

**User Story:** As a reviewer, I want a downloadable Audit Trail PDF, so that I can check every statement without the application.

#### Acceptance Criteria

1. WHEN the Analyst requests the Audit Trail PDF for a Deal with a generated memo, THE PDF_Renderer SHALL generate a PDF from the Audit_Trail and Evidence_Store as stored at the time of the request, listing every Memo_Statement in statement ID order with its statement ID, memo section number (1-7), current text, Statement_Label, Verification_Status, any Reference_Validator or Passage_Locator note, the analyst name and timestamp of the latest Verification_Status change, and for each Analyst correction the original text, corrected text, analyst name and timestamp.
2. THE PDF_Renderer SHALL begin the Audit Trail PDF with the Deal_Intake_Fields and their `DI-<FIELD>` references, the list of Documents with doc_id, display name, document type, period covered and audited flag, the Financial_Database file name, the generation date and time, and the counts of Approved, Flagged and Pending Memo_Statements computed by the Backend from the stored Verification_Status values, whose sum equals the total number of Memo_Statements.
3. THE PDF_Renderer SHALL include a Section 3 review section listing each Section 3 statement with its text, its Number_Verifier result ("Numbers verified", or "Number mismatch" with the unmatched values), any Analyst edit with original and corrected text, and the financial analysis approval with analyst name and timestamp.
4. THE PDF_Renderer SHALL name the file `<Borrower>_CreditMemo_AuditTrail_<YYYYMMDD>.pdf`, using the same `<Borrower>` sanitising rule and local generation date as the Credit Memo PDF file name.
5. THE PDF_Renderer SHALL show under each Memo_Statement one entry per cited Evidence_ID: for document evidence the Evidence_ID, doc_id, doc_name, page number, supporting excerpt and location status; for CSV evidence the Evidence_ID, Financial_Database file name, metric label as written in the CSV, period column header, display value and any Anomaly_Flags; for deal intake evidence the `DI-<FIELD>` reference and entered value; and the text "No supporting reference" for a statement that cites no Evidence_ID.
6. IF any Memo_Statement has the Verification_Status Pending when the Audit Trail PDF is generated, THEN THE PDF_Renderer SHALL mark each Pending statement with the text "PENDING" and print on the first page a notice stating the number of Pending statements and that analyst review is incomplete.
7. IF no memo has been generated for the Deal, THEN THE Backend SHALL reject the Audit Trail PDF request with a message stating that Section 5 must be run first, and SHALL produce no file.

### Requirement 25: Provider-Agnostic LLM Client

**User Story:** As the project owner, I want to choose the LLM provider in a settings file, so that I can use whichever API key I have.

#### Acceptance Criteria

1. THE LLM_Client SHALL read three settings from `.env` (provider, model name, API key) and SHALL accept provider values for at least OpenAI, Google Gemini and Anthropic.
2. WHEN a section's LLM task is run, THE LLM_Client SHALL send the Master System Prompt from the Instructions_File as the system message and that section's runtime prompt with its input JSON as the user message, with temperature 0.
3. WHEN an LLM response is received, THE Backend SHALL validate the response against the section's fixed JSON output schema (parseable JSON, every required key present, only the schema's allowed vocabulary values) and then check every cited Evidence_ID with the Reference_Validator.
4. IF a response fails schema validation, a Section 2-4 response cites an unknown Evidence_ID, or a Section 5 response contains a Memo_Statement citing an unknown Evidence_ID, THEN THE Backend SHALL resend the request with the list of validation errors added, up to 2 retries (at most 3 attempts per section run).
5. IF the third attempt still fails schema validation, or a Section 2-4 output still cites an unknown Evidence_ID, THEN THE Backend SHALL stop the section, store no output from that run, keep all earlier stored section outputs unchanged, and display the validation errors to the Analyst.
6. IF the third Section 5 attempt passes schema validation but one or more Memo_Statements still cite an unknown Evidence_ID, THEN THE Backend SHALL store the memo and set the Verification_Status of only those Memo_Statements to Flagged with the note "Reference does not exist", leaving every other Memo_Statement's Verification_Status unchanged.
7. THE Backend SHALL store the output of the accepted attempt with the same text, figures and Evidence_IDs the LLM returned, and setting a Verification_Status or note SHALL NOT change a Memo_Statement's text or cited Evidence_IDs.
8. IF the provider value is missing or not supported, or the model name or API key is missing or empty in `.env`, THEN THE Backend SHALL reject the section run without sending an LLM request and display a message naming each missing or invalid `.env` setting, without showing the API key value.
9. IF an LLM request for Section 3, 4, 5 or 6 fails with a network error or provider error, or returns no response within 120 seconds, THEN THE Backend SHALL stop the section without automatic retry, store no output from that run, keep all earlier stored section outputs unchanged, and display the provider's error message or a timeout message with any API key value removed.
10. IF a Section 2 extraction request fails with a network error or provider error, or returns no response within 120 seconds, THEN THE Extraction_Service SHALL count that failure against the 2-retry budget defined in Requirements 5.6 and 6.7 and SHALL display any provider error message with any API key value removed.

### Requirement 26: Single-Click Launch

**User Story:** As the user, I want to start the application by double-clicking one file, so that I can use the app without technical setup.

#### Acceptance Criteria

1. WHEN the user double-clicks the Launcher and no virtual environment with every pinned dependency successfully installed exists, THE Launcher SHALL create a Python virtual environment and install every dependency at its exact pinned version into that virtual environment.
2. WHEN the user double-clicks the Launcher, THE Launcher SHALL start the Backend from the virtual environment on the configured local address (default `127.0.0.1:8000`) and, only after the Backend responds at that address, open the Frontend at that address in the default browser.
3. THE Backend SHALL serve the Frontend as static files from the same address and port as the Backend, requiring no installed runtime other than Python 3.11 or later and no Frontend build step.
4. IF no Python interpreter of version 3.11 or later is found on the machine, THEN THE Launcher SHALL display a message stating that Python 3.11 or later is required, SHALL NOT create the virtual environment or start the Backend, and SHALL keep its window open until the user presses a key.
5. IF `.env` does not exist, THEN THE Launcher SHALL create `.env` as a copy of `.env.example`, display a message asking the user to add an API key and select the LLM provider in `.env`, and SHALL NOT start the Backend during that launch; IF `.env` already exists, THEN THE Launcher SHALL leave its contents unchanged.
6. IF the configured port is already in use when the Launcher attempts to start the Backend, THEN THE Launcher SHALL display a message naming the port and stating that it is in use, SHALL NOT open the browser, and SHALL keep its window open until the user presses a key.
7. THE Frontend SHALL load every script, style sheet, font and chart library from files served by the Backend, making no request to an external host for any Frontend asset.
8. WHEN the user double-clicks the Launcher and a virtual environment with every pinned dependency successfully installed exists, THE Launcher SHALL reuse that virtual environment without recreating it or reinstalling dependencies.
9. IF creating the virtual environment or installing any pinned dependency fails, THEN THE Launcher SHALL display a message identifying the failed step, SHALL NOT start the Backend, SHALL keep its window open until the user presses a key, and SHALL repeat the virtual environment creation and installation on the next launch.
10. IF the Backend does not respond at the configured local address within 30 seconds of being started, THEN THE Launcher SHALL display a message indicating that the Backend failed to start, SHALL NOT open the browser, and SHALL keep its window open until the user presses a key.

### Requirement 27: Local Storage and Security

**User Story:** As the project owner, I want confidential documents and keys kept local, so that borrower data and credentials are not exposed.

#### Acceptance Criteria

1. THE Backend SHALL persist all Deals, uploaded Document files, Evidence_Stores, Financial_Datasets, section outputs, Audit_Trails, Credit Memo PDFs and Audit Trail PDFs only within a single data folder located inside the project folder on the local machine.
2. THE Backend SHALL send Document text, Deal_Intake_Field values and Financial_Dataset values only through the LLM_Client and only to the LLM provider configured in `.env`.
3. THE Backend SHALL make no outbound network request other than LLM_Client calls to the LLM provider configured in `.env`.
4. IF `.env` does not specify an LLM provider or the API key for that provider, THEN THE Backend SHALL send no data to any LLM provider, SHALL return an error message to the Frontend indicating which `.env` setting is missing, and SHALL leave all stored Deal data unchanged.
5. THE Backend SHALL accept connections only on the loopback address 127.0.0.1, so that a connection attempt from another machine on the same network is refused.
6. WHEN the Frontend displays the start screen, THE Credit_Analysis_App SHALL display the notice "Local prototype: no authentication. Do not deploy to a shared environment without adding access control." verbatim, visible without scrolling and with no control to dismiss it.
7. THE project SHALL include a `.gitignore` file that excludes `.env`, the virtual environment folder and the data folder, so that none of their files appear as untracked or staged in `git status`.
8. THE Backend SHALL exclude every API key value, in full or as any substring of 8 or more consecutive characters, from log files, console output (including the Launcher window), error messages (including errors relayed from the LLM provider) and responses sent to the Frontend.
9. THE Backend SHALL exclude every API key value, in full or as any substring of 8 or more consecutive characters, from Evidence_Stores, section outputs, Audit_Trails, the Credit Memo PDF and the Audit Trail PDF.

### Requirement 28: Accessibility

**User Story:** As an Analyst using a keyboard or screen reader, I want the interface to be operable, so that I can complete every step.

#### Acceptance Criteria

1. THE Frontend SHALL display a visible text label for every input control (including each Deal_Intake_Field, Document upload, Document type, period covered, audited flag, Verification_Status selector, Analyst correction field and analyst name) and SHALL programmatically associate that label with the control so that the control's accessible name contains the visible label text.
2. THE Frontend SHALL make every action (entering Deal_Intake_Fields, uploading Documents, starting each Section task, approving the Section 3 output, setting Verification_Status, entering Analyst corrections, opening cited sources, and downloading the Credit Memo PDF and Audit Trail PDF) reachable with Tab and Shift+Tab in an order matching the visual reading order, operable with Enter or Space, free of any point where focus cannot be moved away by Tab, Shift+Tab or Escape, and visibly focus-indicated for as long as each element holds focus.
3. THE Frontend SHALL display each Verification_Status (Pending, Approved, Flagged), each Anomaly_Flag type (zero value, negative value, large swing, unit not stated, unparseable value), each Statement_Label and each Comparison_Record direction ("up", "down", "~") as visible text, so that every one of these values remains identifiable when colour is removed from the display.
4. THE Frontend SHALL render text with a contrast ratio against its background of at least 4.5:1 for text smaller than 24 CSS px (or smaller than 18.66 CSS px when bold) and at least 3:1 for larger text, and SHALL render focus indicators and input control boundaries with a contrast ratio of at least 3:1 against adjacent colours.
5. WHEN the Dashboard displays a chart, THE Frontend SHALL provide a text alternative reachable by keyboard that lists, for each period from oldest to newest, every plotted Canonical_Metric display value and any Anomaly_Flag on that value.
6. WHEN a Backend operation changes state (Document processing, an Extraction_Service, Trend_Analyst, Risk_Analyst, Memo_Generator or Support_Checker task completing or failing, or a Number_Verifier or Reference_Validator result), THE Frontend SHALL expose a text status message to assistive technology without moving keyboard focus.
7. IF an Analyst input fails validation, THEN THE Frontend SHALL display a text error message identifying the field and the reason, programmatically associate the message with that field, move keyboard focus to the first invalid field, and keep all values the Analyst entered.

### Requirement 29: Testing

**User Story:** As the project owner, I want automated tests, so that the prototype's anti-hallucination safeguards are demonstrably correct.

#### Acceptance Criteria

1. THE project SHALL include pytest unit tests for the CSV_Loader that assert: the label "Operating Cash Flow " maps to OPERATING_CASH_FLOW and "Debt-Service Coverage Ratio (DSCR)" maps to DSCR; the header "Q2 2026 (Jun 27 2026)" parses to period label "Q2-2026" and period end date 27 June 2026; periods supplied newest-first are ordered oldest to newest; "25.40%" parses to unit type "percent", "5.6x" to "multiple", "22.8" for DSO to "days" and "7006" for other metrics to "amount"; an empty or non-numeric cell yields a null parsed value, the display value "Not available in database" and the Anomaly_Flag "unparseable value"; an unrecognised metric label is retained with the flag "Unrecognised metric"; and an unparseable period header stops loading and reports the header text.
2. THE project SHALL include a golden test confirming that loading `intel_quarterly_ratios.csv` yields exactly 10 Canonical_Metrics in the Canonical_Metric order across exactly 4 periods ordered Q3-2025, Q4-2025, Q1-2026, Q2-2026; that each of the 40 display values equals the corresponding trimmed CSV cell text; that each value carries the Evidence_ID `CSV-<METRIC_KEY>-<PERIOD>` (e.g. `CSV-DSCR-Q2-2026`); that no row carries the flag "Unrecognised metric"; and that exactly 30 Comparison_Records (3 per metric) are created.
3. THE project SHALL include hypothesis property tests, each running at least 100 generated examples, that assert: for every value with at most 2 decimal places between -999,999,999.99 and 999,999,999.99 and every unit type, formatting with the Value_Formatter then parsing with the CSV_Loader returns the same value and unit type; every Comparison_Record has direction "~" when the absolute change is within the inclusive Stable_Band default for its unit type, "up" when the change is positive and outside the band, and "down" when negative and outside the band; and every Comparison_Record's from period and to period belong to the same metric.
4. THE project SHALL include Anomaly_Flag tests confirming that, for `intel_quarterly_ratios.csv`, EBITDA_MARGIN Q1-2026 and DSCR Q1-2026 carry "zero value", INTEREST_COVERAGE Q1-2026 carries "negative value", REVENUE_GROWTH Q4-2025 (-4.11%) carries no "negative value" flag, and all 4 periods of OPERATING_CASH_FLOW and WORKING_CAPITAL carry "unit not stated"; and confirming with constructed data that a change above the configured large-swing threshold flags the later period with "large swing" while a change at or below the threshold attaches no "large swing" flag.
5. THE project SHALL include Number_Verifier tests confirming that a statement whose numbers all equal cited display values or Comparison_Record changes is marked "Numbers verified"; that a statement containing a number absent from its cited entries is marked "Number mismatch" with that number listed as unmatched; that a structured comparison claim whose direction differs from the matching Comparison_Record is marked "Number mismatch"; and that the statement text is unchanged after verification in all three cases.
6. THE project SHALL include Reference_Validator tests confirming that existing `EV-###`, `CSV-<METRIC_KEY>-<PERIOD>` and `DI-<FIELD>` Evidence_IDs of the Deal are accepted, that an Evidence_ID absent from the Deal is rejected and reported, and that an Evidence_ID existing only in a different Deal is rejected.
7. THE project SHALL include Passage_Locator tests using a generated PDF confirming that an excerpt present on the referenced page returns "Located" with a match position; that an excerpt split across a line break with end-of-line hyphenation, or containing typographic quotes or dashes, returns "Located"; and that an excerpt absent from the referenced page (including one present only on a different page) returns "Not located" and flags the Evidence_Record for Analyst review.
8. THE project SHALL include review-gate tests confirming that editing an Approved Memo_Statement resets its Verification_Status to Pending; that final memo PDF generation is rejected while at least one Memo_Statement is Pending, with a message stating the number of pending statements; and that generation proceeds once every Memo_Statement is Approved or Flagged.
9. THE project SHALL include schema tests confirming, for each of the Section 2A, 2B, 3, 4, 5 and 6 output schemas, that one valid sample output passes validation, that an output missing any one required key is rejected, and that an output containing a value outside its fixed vocabulary (e.g. a Statement_Label other than Sourced, ASSUMPTION or NOT VERIFIED) is rejected.
10. THE project SHALL run the full test suite with a single `pytest` command using a mocked LLM_Client, passing with no API key present in the environment and making no outbound network calls.
11. THE project SHALL include LLM_Client retry tests using the mocked LLM_Client confirming that a response that is invalid once and then valid is accepted after 1 retry with the validation errors sent back in the retry, and that a response that is invalid on all attempts results in exactly 3 calls in total, the section stopped and the validation errors returned for display to the Analyst.
12. THE project SHALL include Section 3 gate tests confirming that a request to run the Section 4 analysis is rejected while the financial analysis is unapproved, and that approval is refused while any statement is marked "Number mismatch" and is neither corrected nor flagged.
