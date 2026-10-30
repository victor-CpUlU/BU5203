# AI-Assisted Credit Analysis: User Guide

This app helps a credit analyst decide whether a borrower can support a specific loan request. The analyst uploads the borrower's filings (PDFs). The app connects automatically to a financial database, the workbook `Semiconductor_Financial_Performance_Indicators_Combined.xlsx`, which covers AMD, Intel, Micron, NVIDIA and TSMC. The AI extracts information from the filings and drafts the analysis and credit memo. Python supplies and checks every figure and citation, and the analyst reviews and approves everything before the final memo is produced.

> The app runs only on your own computer and has **no login**. Do not put it on a shared network without adding access control.

> **Developers:** this file is the user guide. For the design spec, pipeline rules, data conventions and the AI prompts, see [`Instructions.md`](Instructions.md). See [section 8](#8-for-developers) for the developer workflow.

**Quick start:** install Python 3.11+ and the Kiro CLI, then run `kiro-cli login` ([setup](#1-first-time-setup)). Double-click `start.bat`, create a deal for one of the five companies, upload its PDFs, and work through Sections 1 to 6 in the left-hand menu ([walkthrough](#3-using-the-app-section-by-section)).

---

## Where the numbers come from, and what the AI does

**The AI never calculates a number.** Every figure in the app comes from the financial database or from Python. The AI writes sentences that quote those figures, and Python checks every quoted figure against its source before the analyst sees it.

| What you see | Produced by | How |
|---|---|---|
| Historical figures and ratios (Revenue, EBITDA, Debt/EBITDA, DSCR, interest coverage, current ratio, ...) | **Financial database** | Read from the borrower's sheet in the workbook. Each ratio is defined by the workbook's own formula over its `Inputs` sheet. If the file has no saved formula results, Python evaluates those formulas exactly as written. It never invents its own definition. Definitions can differ by company (for example, DSCR is a proxy for AMD and NVIDIA); hover a metric name to see its definition. |
| Quarter-on-quarter changes and up/down/stable labels | **Python** | Difference between consecutive quarters: percentage points for %, x for multiples, days for DSO, % change for amounts. See [stable bands and large swings](#stable-bands-and-large-swings) below. |
| Flags (zero, negative, large swing, n/m, blank) | **Python** | Fixed rules, listed in `Instructions.md` 4.4 and [below](#stable-bands-and-large-swings). Values are never changed. |
| Divergence patterns (e.g. revenue up while operating cash flow down) | **Python** | Compares the up/down labels of two metrics in the same quarters. |
| Forecast, scenarios and pro-forma debt service | **Python**, from **analyst-editable assumptions** | See [the forecast model](#how-the-forecast-is-calculated) below. Base-case defaults are the averages of the database quarters. |
| Thresholds that highlight forecast quarters | **Analyst** | Optional; there are no defaults and no pass/fail result. |
| 2A business and 2B debt statements from the PDFs | **AI**, checked by Python | The AI summarises each fact and quotes a passage from the page. Python checks the quote really is on the cited page, and that every debt figure appears in the quote. Whether the summary matches the quote is for the analyst to judge. |
| Trend commentary, risk list (impact, likelihood, ranking), mitigants, proposed covenants, memo text | **AI**, checked by Python | The AI may only quote figures it was given, with their Evidence IDs. Python marks each statement **Numbers verified** or **Number mismatch** and rejects citations that don't exist. Covenant thresholds and forecast statements are always labelled **ASSUMPTION**. |
| Information gaps, flagged-value checks and scenario summaries in the memo | **Python** | Written by the app, not the AI, and marked "Backend-generated". |
| Approve, flag or correct, and the final decision | **Analyst** | Nothing is final until the analyst approves it. The AI never approves, declines or recommends the loan. |

**Evidence IDs** show where each figure comes from. Click any ID in the app to see its source.

| ID | Source |
|---|---|
| `CSV-...` | A database value (workbook sheet, cell and formula) |
| `FC-...` | A forecast value |
| `FA-...` | A forecast assumption |
| `FT-...` | A threshold you entered |
| `EV-...` | A passage in an uploaded PDF |
| `DI-...` | A field from the deal intake |

### Stable bands and large swings

The stable bands are **not calculated from the data**. They are fixed tolerances set in `config/analysis.toml` (`[stable_band]`), chosen to ignore rounding-level movements. They are labelling rules, not credit benchmarks.

For each pair of consecutive quarters, Python works out the change in the metric's own unit:

| Metric unit | Change measured as | Stable band ("~") | Large swing flag |
|---|---|---|---|
| Percent (e.g. EBITDA margin, revenue growth) | later value - earlier value, in percentage points | within ±1.0 pp | more than 10.0 pp |
| Multiple (e.g. Debt/EBITDA, DSCR) | later value - earlier value, in x | within ±0.10x | more than 2.0x |
| Days (DSO) | later value - earlier value, in days | within ±3.0 days | more than 5.0 days |
| Amount (e.g. revenue, cash, USD m) | (later - earlier) / \|earlier\| x 100, in % | within ±5.0% | more than 50% of the earlier value |

How the label is chosen:
- **Inside the band:** the change is labelled **~ (stable)**.
- **Above the band:** **up**.
- **Below the band:** **down**.

Rules:
- The band is inclusive: a change of exactly +1.0 pp on a percent metric is still "stable".
- Changes use the database values as displayed (e.g. 18.79% vs -0.71% gives +19.5 pp).
- Only consecutive quarters are compared. A blank quarter breaks the chain, so no change is computed across it.
- If an amount's earlier value is 0, the % change is "Not computable". The label then follows the sign of the later value.

**Example (Intel Q1-FY2026 to Q2-FY2026):**
- **DSCR** 0.62x to 0.90x is +0.28x. That is outside ±0.10x, so it is labelled **up**.
- **Revenue** 13,577 to 16,128 is +18.8%. That is outside ±5%, so it is labelled **up**.

The **large-swing** thresholds (`[large_swing]`) only add a review flag; they never change a value.

**Sustained trends:** a metric is labelled "sustained improvement" or "sustained deterioration" when its last two changes have the same direction and neither is stable.
- Lower is better for Debt/EBITDA, DSO, total debt, net debt, Debt/Equity, short-term debt and interest expense.
- Capital expenditure is neutral: it gets "sustained increase" or "sustained decrease".

To change any band or threshold, edit `config/analysis.toml` and restart the app. New values apply to deals connected (or reconnected) afterwards. A missing or invalid value falls back to the defaults shown above.

### How the forecast is calculated

Python projects each quarter forward from the latest database quarter, for a base, an upside and a downside case:

- **Revenue** = previous quarter x (1 + revenue growth per quarter)
- **EBITDA** = revenue x EBITDA margin; **capex** = revenue x capex % of revenue
- **Cash flow available for debt service** = EBITDA - capex (before tax, working capital, dividends and buybacks)
- **Interest** = latest quarterly interest x (1 + scenario change) + facility balance x facility rate / 4
- **Principal** = existing short-term debt repaid over 4 quarters + the requested facility (bullet at the end, or equal quarterly instalments)
- **DSCR** = cash flow available / (interest + principal); **interest coverage** = EBITDA / interest
- **Debt/EBITDA** = total debt / EBITDA of the last 4 quarters
- **Cash after debt service** = previous cash + cash flow available - debt service

Defaults:
- The base case uses the averages of the database quarters for revenue growth, EBITDA margin and capex %.
- Upside and downside add illustrative shocks from `config/analysis.toml`.
- The facility rate defaults to an illustrative 6% per year.

The analyst can change every assumption on the dashboard, and the forecast and its charts recalculate immediately. Saved assumptions are recorded in the audit trail.

Limits:
- Long-term debt maturities aren't in the database, so they aren't in debt service.
- The forecast DSCR uses the formula above, not each company's historical definition.

---

## 1. First-time setup

### What you need to download

| What | Why | Where |
|---|---|---|
| **Windows 11** | The Kiro CLI only runs on Windows 11 | (check with Settings → System → About) |
| **Python 3.11 or later** | Runs the app | [python.org/downloads](https://www.python.org/downloads/). When installing, tick **"Add python.exe to PATH"**. |
| **GitHub Desktop** (optional) | Get the project and keep it in sync with your team. It includes its own Git, so you don't need to install Git separately. | [desktop.github.com](https://desktop.github.com/) |
| **Kiro CLI** | The AI that runs the analysis (uses your Kiro account) | Installed with one PowerShell command, see below |
| **The borrower's filings as PDFs** | The analyst uploads these in the app | Company investor relations site, or SEC EDGAR (see [section 2](#2-before-you-start-a-deal)) |

You do **not** need Node.js or anything else. The app's other Python packages and the chart library are installed or included automatically.

### Get the project

- **With GitHub Desktop:** File → **Clone repository**, pick the repository and choose an **empty** local folder (cloning can't go into a folder that already has files). Click **Clone**.
- **Without Git:** download the project folder (e.g. as a ZIP from GitHub) and unzip it.

Keep the folder structure as it is. `start.bat` must stay next to `requirements.txt`, `backend\` and `frontend\`.

### Set up the AI (Kiro CLI)

The app needs an AI model it can call automatically for Sections 2 to 5 (extraction, trend commentary, risks and memo). The Kiro chat inside the Kiro editor **cannot** be called by other programs, so the app uses the **Kiro CLI**: a separate command-line version of Kiro that programs can run. It is a different program from the Kiro editor and must be installed on its own.

1. Open **PowerShell** from the Start menu (not Command Prompt) and run:
   ```powershell
   irm 'https://cli.kiro.dev/install.ps1' | iex
   ```
2. **Close PowerShell and open a new one** (so it picks up the new PATH), then check the install:
   ```powershell
   kiro-cli --version
   ```
3. Sign in with your Kiro account (a browser window opens):
   ```powershell
   kiro-cli login
   ```
4. Check which account the CLI is signed into. AI usage is charged to this account's Kiro credits:
   ```powershell
   kiro-cli whoami
   ```
5. Optional test, the same way the app calls it:
   ```powershell
   kiro-cli chat --no-interactive "Reply with only this JSON: {""ok"": true}"
   ```
   You should get `{"ok": true}` back (extra lines around it are fine).

**Do I need a Kiro API key?** Not if you are signed in with `kiro-cli login`: the CLI uses that session. An API key is only an alternative, for example if login doesn't work for headless use. To use one, create it at **app.kiro.dev → API Keys** (needs a Pro, Pro+, Pro Max or Power plan) and put it in `.env` as `LLM_API_KEY=ksk_...`.

### Other AI providers (alternatives)

If you can't use the Kiro CLI, the app also works with an API key from another provider. Change these lines in `.env`:

| Provider | What you need | `.env` settings |
|---|---|---|
| **Kiro CLI** (default) | Kiro CLI installed and signed in (above) | `LLM_PROVIDER=kiro_cli` (model and key can stay blank) |
| Google Gemini | Google AI Studio API key (has a free tier) | `LLM_PROVIDER=gemini`, `LLM_MODEL=gemini-2.5-flash`, `LLM_API_KEY=...` |
| OpenAI | OpenAI API key | `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-4o-mini`, `LLM_API_KEY=...` |
| Anthropic | Anthropic API key | `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-sonnet-4-5`, `LLM_API_KEY=...` |

### The `.env` settings file

- It is in the project folder: `<project folder>\.env` (next to `.env.example`). `start.bat` creates it on the first run. In the Kiro or VS Code file explorer it may look greyed out because Git ignores it; open it anyway, or use Notepad.
- Write values straight after `=`, with no spaces or quotes, then save and restart the app with `start.bat`.
- **Never put a key in `.env.example`** (that file is uploaded to GitHub), and never paste keys into a chat or email. `.env` stays on your computer only.

### Start the app

1. Double-click **`start.bat`**.
2. **First run only:** it installs the app's Python packages, which takes a few minutes. It then creates `.env`, opens it in Notepad and stops. Check the settings (the default `LLM_PROVIDER=kiro_cli` is fine if the Kiro CLI is set up), save the file, and double-click `start.bat` again.
3. The app opens in your browser at **http://127.0.0.1:8000**.
4. The black window that opens runs the backend. Leave it open while you work (you can minimise it).
5. **Closing the app shuts everything down.** Any of these stops the backend, any AI step still running, and the black window. Your saved deals are kept.
   - Click **Close app** at the top right (stops immediately), or
   - close the browser tab (stops about 20 seconds later; refreshing the page does not count as closing), or
   - close the black window.
   If the browser crashes without closing the tab properly, the backend stops on its own after 2 minutes.
6. **To open it again, double-click `start.bat`.** If an earlier copy is somehow still running, it is stopped and a fresh copy starts.

Keep the app in **one** browser tab. If you close one of two open tabs, the backend may stop while the other is still open.

The badge at the top right shows which AI provider is in use. A red **"AI not configured"** badge means a `.env` setting is missing.

---

## 2. Before you start a deal

- **Enter your name** in the **Analyst name** box at the top of the page. It is recorded with every approval, flag and correction in the audit trail. Your browser remembers it.
- **Get the borrower's documents as PDFs**, for example the 10-K, 10-Q, annual report or audited financial statements. SEC EDGAR filings are web pages, so download the PDF from the company's investor relations site, or open the filing in your browser and use **Print → Save as PDF**. Scanned PDFs without selectable text can be uploaded but cannot be read.
- **The financial database is connected automatically.** You don't load or upload it. The app fetches the borrower's figures from the external financial database (by default `Semiconductor_Financial_Performance_Indicators_Combined.xlsx`, which covers AMD, Intel, Micron, NVIDIA and TSMC) as soon as you create the deal, and shows them in Section 2. The borrower name must match one of these companies, for example "Intel Corporation" or "Micron Technology". See [section 5](#5-financial-database-format) for the format the database uses.

---

## 3. Using the app, section by section

The left-hand menu follows Sections 1 to 6. Under each step it shows that step's status, for example "completed", "not run" or "Out of date". Work through them in order.

### Section 1: Deal intake and data

1. On the home page, click **Start a new deal**.
2. Fill in the loan request: borrower, facility type, requested amount and currency, purpose, tenor and repayment structure. Collateral is optional; if you leave it blank, the app records "None provided". Click **Create deal**.
3. **Upload documents.** In the Documents card, choose a PDF and set its document type, the period it covers (e.g. `FY2025`) and whether it is audited. You can also give it a display name such as `Intel 2025 10-K`. Then click **Upload document**. Repeat for each file. Each file gets an ID (D1, D2, ...).

When you create the deal, the app automatically connects to the external financial database and fetches this borrower's figures. There is no button to press. The data, the **values flagged for review** (zero values, negative values, large swings, amounts with no stated unit) and the **information gaps** are shown in [Section 2](#section-2-extraction). The values themselves are never changed. If the database cannot be reached, Section 2 shows the error.

### Section 2: Extraction

Click **Run extraction (2A and 2B)**. The AI reads the relevant pages of your PDFs and extracts:

- **2A Business information:** what the company does, industry and business model, revenue drivers, products, geography, customers, suppliers, capital intensity and investment plans, management and ownership.
- **2B Debt and financing information:** existing debt, maturity profile, interest obligations, secured vs unsecured debt, financing arrangements, covenants, and upcoming maturities and refinancing.

Each item gets an **Evidence ID** (`EV-001`, ...). The app then checks that the quoted passage really appears on the cited page.

- **Located**: the passage was found on the page.
- **Not located: review**: the passage could not be found. Check it yourself.
- Click any Evidence ID to see the page with the passage highlighted.
- Items the app rejected, for example because they were too long or cited a page that wasn't supplied, are listed under **rejected items**.

You can re-run 2A or 2B on its own. Long filings take a few minutes because pages are sent in batches.

**2C Financial data (external database).** Below 2A and 2B, Section 2 shows the figures fetched automatically from the external financial database when the deal was created, with a note that they come from the database. The AI never extracts or calculates these numbers. The ratios are the workbook's own; if the workbook has no saved formula results, Python evaluates the workbook's formulas exactly as written, and the card says so. This card shows the company and sheet, the currency unit, the periods and metrics found, the **values flagged for review** and the **information gaps**. Each value has a `CSV-` Evidence ID used throughout the memo. After the workbook is updated, click **Reconnect financial database** to re-read it (this resets saved forecast assumptions and marks Sections 3-5 out of date).

### Section 3: Financial dashboard and AI analysis

The dashboard shows five panels: **Profitability, Leverage, Liquidity, Cash Flow and Debt Servicing**.

- **Charts** use the database values exactly. A triangle marker means the value is flagged. Each panel has a **data table** (click to expand) and lists any metrics that are **not available in database**. Hover a metric name to see how the workbook defines it for this company (for example, DSCR is a proxy for some companies).
- Click **Run AI financial analysis**. It takes about a minute: the app sends 7 requests to the AI at the same time. The AI commentary appears beside each chart. Python then checks each statement and marks it:
  - **Numbers verified**: every figure matches the cited data. A figure from a cited metric's definition note, such as "91 days" for DSO, also counts.
  - **Number mismatch**: something doesn't match. The unmatched values are listed.
- The **Divergence patterns** table shows the five patterns from the Project Details and, for each, the quarters where Python observed it (for example Revenue up while Operating Cash Flow fell).

**Peer comparison.** Below the panels, you can compare the borrower with the other companies in the database (AMD, Intel, Micron, NVIDIA, TSMC).
- **Choosing what to show:** a grid lists every metric (rows) against every company (columns). Tick any combination, for example Revenue for Intel, AMD and NVIDIA but EBITDA for Intel only.
  - Click a metric name to toggle that row.
  - Use **All / none** under a company to toggle its column.
  - The buttons **Key ratios, all companies**, **Borrower only** and **Clear all** give quick starting points.
  - Your choice is remembered in the browser for each deal.
- **Charts:** one chart per ticked metric, with one line per ticked company. The borrower's line is thicker, and a triangle marks a flagged value. Each chart has a data table, and a note on how each company defines the metric.
- **Lining up quarters:** the companies have different fiscal years, so quarters are matched by the calendar date range each fiscal quarter falls in, as stated in the workbook. For example, NVIDIA Q2-FY2027 and Intel Q2-FY2026 are both "CQ2 2026 (Apr–Jun)". Hover a point to see its fiscal quarter and report date.
- **Units:** amounts stay in each company's own unit, shown in the legend, such as "TSMC (NT$ bn)" or "Intel (USD m)". Ratios and percentages are directly comparable.
- **Source:** the values are the database's own, read from the workbook file; nothing is calculated. The AI does not see this comparison, and it is not part of the memo.

**Forecast and scenario analysis.** Below the peer comparison, Python projects the borrower's quarters forward under a **base, upside and downside case**. Set this up before running the AI analysis, because the AI commentary and the memo use it.
- **Assumptions:** revenue growth per quarter, EBITDA margin, capex as % of revenue, change in interest on existing debt, and the interest rate on the requested facility. Base-case defaults are the averages of the database quarters; upside and downside add illustrative shocks. Each assumption shows its historical reference and where its value came from. Change any value; the results update as you type.
- **Requested facility:** the amount comes from the deal intake. Set the repayment (bullet or equal quarterly instalments), tenor and forecast horizon. If the loan currency differs from the database (TSMC is in NT$ bn), enter an exchange rate.
- **Thresholds (optional):** enter a minimum DSCR, minimum interest coverage, maximum Debt/EBITDA or minimum cash. Quarters that breach them are highlighted in red; nothing is marked pass or fail.
- **Results:** a summary per scenario (lowest DSCR and coverage, highest Debt/EBITDA, cash after debt service, quarters where cash flow is below debt service), charts with history and the three scenarios, and full quarterly tables. Click **How the forecast is calculated** for the formulas.
- Click **Save assumptions** to use them (your name is recorded in the audit trail). Saving marks Sections 3-5 out of date so you can re-run them. **Reset to defaults** returns to the database averages.
- After you run the AI analysis, its forecast commentary appears at the bottom of the card. Every forecast statement is labelled **ASSUMPTION** and cites `FC-` (forecast value), `FA-` (assumption) or `FT-` (your threshold) Evidence IDs.

**Review each statement** with **Approve**, **Flag**, **Comment** or **Edit**. An edited statement is checked again and goes back to Pending.

**Bulk review** (shown while statements are Pending): after reading the commentary, use
- **Approve all pending with "Numbers verified"** for statements whose figures Python matched to the database, and
- **Flag all pending with "Number mismatch"** for the ones that didn't match (or fix them individually with **Edit**).

Approving a statement confirms that you agree with its interpretation, not only that its numbers match. Every bulk change is recorded in the audit trail, one entry per statement under your name.

You can click **Approve financial analysis** only when:
- no statement is still Pending, and
- every "Number mismatch" statement has been corrected or flagged.

Changing a statement after approval removes the approval.

### Section 4: Risks and mitigants

Available only after Section 3 is approved. Click **Identify key risks**. The AI produces 3 to 5 ranked risks in a table:

| Identified Risk | Evidence | Possible Mitigant | Proposed Term / Monitoring Condition |
|---|---|---|---|

Each risk shows its impact and likelihood, and its evidence is number-checked. Numeric covenant thresholds are always marked **ASSUMPTION** and *"Illustrative; analyst to calibrate against credit policy."* These are suggestions only, not lending decisions.

### Section 5: Credit memo

Click **Generate credit memo**. The memo has 7 sections:

1. Executive Summary
2. Business Overview
3. Financial Analysis
4. Repayment Capacity
5. Key Credit Risks
6. Risk Mitigants / Proposed Loan Structure
7. Information Gaps

Every statement has an ID (M1, M2, ...), a label and its Evidence IDs:
- **Sourced**: supported by the cited evidence.
- **ASSUMPTION**: a judgement or suggestion.
- **NOT VERIFIED**: could not be supported.

Section 4 includes **Forecast and scenario analysis**, and pro-forma debt service including the requested facility is taken from the base case. If the AI doesn't cover them, the app adds its own scenario summaries (marked Backend-generated, left Pending for you). The app adds the information gaps and flagged database values to Section 7 itself. There is **no AI recommendation**; the analyst decides.

Regenerating the memo replaces it and resets all Section 6 reviews.

### Section 6: Review, verify and export

1. **Click an Evidence ID** on a statement. The source panel on the right shows:
   - for a document, the document name, page, supporting text and an image of the page with the passage highlighted;
   - for a database value (`CSV-`), the file, sheet and cell, the workbook formula, metric, period and value, with any flags;
   - for a forecast value or assumption (`FC-`, `FA-`, `FT-`), the scenario, the value, its source and whether you saved the assumptions.
   If the passage cannot be found on the page, the statement is **flagged automatically**.
2. Compare the statement with its source. A citation to a real page does not by itself mean the statement is correct.
3. Use **Approve**, **Flag** (with an optional note) or **Correct**. A corrected statement goes back to **Pending** until you approve it again.
4. Use the filter buttons (All / Pending / Approved / Flagged) to find what still needs review. Statements based only on database values that you already approved in Section 3 start as Approved.
5. **Download final Credit Memo PDF.** This works only when no statement is Pending. Flagged statements are kept in the PDF and marked **FLAGGED**, and every statement keeps its source citations.
6. **Download Audit Trail PDF.** This lists the forecast assumptions, every Section 3 statement and every memo statement. For each statement it shows:
   - its position (for example "Section 1.3, statement 1 (M3)", meaning memo Section 1 Executive Summary, subsection 3 Key strengths and risks, first statement);
   - its text, AI original, label, status and number check;
   - whether the AI or the backend wrote it;
   - every review action in time order: who, when, the status change and any note or text change;
   - its sources. You can download it at any time after the memo exists.

**Optional AI support check.** Set `SUPPORT_CHECK_ENABLED=true` in `.env` to show a **Run AI support check** button. It gives an advisory "Supported / Partially supported / Not supported" rating for each statement and never changes a status.

### Re-running earlier steps

If you re-run an earlier step (for example re-extract documents), the later steps are marked **"Out of date"**. Re-run them so the memo matches the latest data. The financial database is connected when the deal is created or its borrower is changed; to pick up changed figures, click **Reconnect financial database** in Section 2C. Saving or resetting the forecast assumptions also marks Sections 3-5 out of date.

---

## 4. Where things are saved

- Each deal is stored in `data/deals/<deal id>/`. This folder holds the uploaded PDFs, the extracted evidence, the outputs of each section, `audit_trail.json` and the exported PDFs in `exports/`.
- The audit trail is append-only: earlier entries are never changed.
- To remove all deals, close the app and delete the `data` folder.
- `.env`, `.venv` and `data` are excluded from Git, so your API key and borrower documents are not uploaded to GitHub.

---

## 5. Financial database format

The database is the Excel workbook `Semiconductor_Financial_Performance_Indicators_Combined.xlsx`, with one KPI sheet per company (`AMD`, `Intel`, `Micron`, `NVIDIA`, `TSMC`) and a matching `<Company> Inputs` sheet. To add a company, copy an existing pair of sheets and keep the same layout:

- **A1:** "<Company name> – Quarterly Financial Performance Indicators". The borrower name is matched to the sheet name, this company name, or its abbreviation in brackets (Inc., Corporation, Co. and Ltd are ignored).
- **A4:** "Financial Performance Indicators". **Row 4** from column C: period headers like `Q2 FY2026`. **Row 5:** fiscal period end date. **Row 6:** calendar quarter.
- **From row 9:** one metric per row, label in column A and unit in column B (`USD m`, `NT$ bn`, `%`, `x`, `Days`). The column after the last period holds the company-specific basis note.
- **Recognised metrics:** Revenue, Revenue Growth (Q/Q), EBITDA, EBITDA Margin, Total Debt, Net Debt, Debt/Equity, Debt/EBITDA (LTM), Cash & Cash Equivalents, Short-Term Debt, Quick Ratio, Current Ratio, Capital Expenditure, Free Cash Flow, Interest Expense, Interest Coverage, Working Capital, Days Sales Outstanding (DSO), Operating Cash Flow, Operating Cash Flow Margin, Debt Service Coverage Ratio (DSCR), plus the memo rows Revenue Growth (Y/Y), EBITDA (LTM) and EBITDA excl. Asset Impairment Charges. Other rows are kept and marked "Unrecognised metric".
- **Values:** KPI cells may be formulas. If the file was last saved by Excel, the saved results are used; otherwise the app evaluates the formulas itself (supported: `+ - * / ^`, cell and range references, `SUM`, `IF`, `IFERROR`, `COUNT`, `OR`, `AND`, `ABS`, `MIN`, `MAX`). A blank input is treated as "not verified, not zero", so a value depending on it shows "Not available in database". `n/m` is shown as reported.
- **Which file is used:** set by `FINANCIAL_DB_PATH` in `.env` (default `Semiconductor_Financial_Performance_Indicators_Combined.xlsx` in the project folder). A legacy single-borrower CSV (`Metric` column and headers like `Q2 2026 (Jun 27 2026)`) is still accepted.

---

## 6. Frequently asked questions

**Do I need to put 10-K or 10-Q files in the project folder first?**
No. The analyst uploads the borrower's documents inside the app (Section 1 → Documents), like an AI credit memo tool. Nothing needs to be in the project folder except the financial database file the app connects to.

**Where do the financial figures come from? I never loaded them.**
The app simulates a connection to an external financial database and fetches the figures automatically when you create the deal, so there is no load or upload step. They appear in Section 2 (2C) with a note that they come from the database, and in the Section 3 dashboard. The default database is `Semiconductor_Financial_Performance_Indicators_Combined.xlsx` (set by `FINANCIAL_DB_PATH`).

**Why does the app need the Kiro CLI? Can't it use the Kiro chat?**
The Kiro chat in the editor has no way for another program to send it prompts. The Kiro CLI does, and it uses your Kiro account, so it is the way to run the app on Kiro. Any of the other providers in [section 1](#other-ai-providers-alternatives) work too.

**It works but I never entered an API key. Is that right?**
Yes. When `LLM_API_KEY` is blank, the Kiro CLI uses your `kiro-cli login` session. Usage is charged to that account (check it with `kiro-cli whoami`).

**Section 2 is taking a long time. Is it stuck?**
Probably not. Long filings are sent to the AI 30 pages at a time, first for 2A and then for 2B, and each batch can take around a minute. Results appear only once everything has finished. Keep the page open. You can see progress in `data\deals\<deal id>\audit_trail.json`, which gets one `llm_output` entry per batch.

**My PDF is bigger than the upload limit.**
The limit is `max_upload_mb` in `config\analysis.toml` (default 200 MB), and it applies without a restart. Large annual reports are usually big because of images. Saving the file again with "Reduce file size" or Print → Save as PDF makes it much smaller without losing the text.

**I closed the browser. Is the app still running in the background?**
No. Closing the tab (or clicking **Close app**) stops the backend and closes the black window. Double-click `start.bat` to open it again.

**The page says "The app has stopped."**
The backend was closed (from another tab, the Close app button, or the black window). Double-click `start.bat` to open it again.

---

## 7. Troubleshooting

| Problem | What to do |
|---|---|
| "Python 3.11 or later is required" | Install Python from python.org with "Add python.exe to PATH" ticked, then run `start.bat` again. |
| "The file is larger than the ... MB limit" | Raise `max_upload_mb` in `config/analysis.toml` (default 200) and upload again. |
| "Port 8000 is already in use" | The app is probably already open in another window. Close it, or change `PORT` in `.env`. |
| Red "AI not configured" badge | Fill in the missing setting it names in `.env`, then restart the app. |
| "Kiro CLI not found" | Install the Kiro CLI (see setup) and open a **new** PowerShell to check `kiro-cli --version`. Then restart the app with `start.bat`. If it is still not found, run `(Get-Command kiro-cli).Source` in PowerShell and put that path in `.env` as `KIRO_CLI_PATH=...`. |
| Kiro CLI login or "API key required" error | Run `kiro-cli login` in PowerShell (check with `kiro-cli whoami`), or put a Kiro API key in `LLM_API_KEY` in `.env`. |
| Section 2 shows "Could not connect to the financial database" | Either the borrower is not one of the companies in the database (the message lists them; use **Edit** on the deal to correct the name), or the file is missing or malformed. Check that `FINANCIAL_DB_PATH` points to the workbook (default `Semiconductor_Financial_Performance_Indicators_Combined.xlsx`, see [section 5](#5-financial-database-format)), then click **Reconnect financial database**. |
| The forecast says it needs values from the database | The deal was created on the old CSV database. Click **Reconnect financial database** in Section 2C. |
| "The Kiro CLI did not respond within ... seconds" | The AI took longer than `llm_timeout_s` in `config/analysis.toml` (default 600 seconds). Section 3 runs as 7 parallel AI requests (one per dashboard panel, one for repayment capacity, one for the forecast) and usually takes about 1 minute with the Kiro CLI. Section 5 sends a lot of data in one request and can take 2 to 3 minutes. Either takes longer if an AI answer fails a check and is retried. Run it again, or raise `llm_timeout_s`; the change applies on the next run without restarting. |
| A section "failed" | Expand **Last run failed** to see why. Earlier results are kept, so you can simply run it again. |
| "No relevant pages were found" | The PDF may be scanned (no text), or may not cover that topic. Upload a text-based PDF. |
| Section 4 or 5 button is greyed out | Approve Section 3 first (for Section 4), or complete Section 4 (for Section 5). |
| "Not located" on an Evidence ID | The AI's quote could not be found on that page. Open the page, check the statement, and flag or correct it. |

---

## 8. For developers

- **Prompts:** the AI prompts live in `Instructions.md` (Parts 5 and 6). After editing a prompt, run `.venv\Scripts\python tools\sync_prompts.py` to update the copies the app loads from `backend\app\prompts\`.
- **Thresholds and keywords:** large-swing and stable-band thresholds, page-selection keywords, size limits and the forecast defaults (`[forecast]`: default facility rate, horizon, upside and downside shocks) are set in `config/analysis.toml`. The PDF upload limit is `max_upload_mb` (default 200 MB) and the CSV limit is `max_csv_mb`.
- **Tests:** run `.venv\Scripts\python -m pytest`. The tests use a simulated AI, so they need no API key or internet connection.
- **Code layout:** the backend (Python/FastAPI) is in `backend/app/` and the frontend (HTML/CSS/JavaScript) is in `frontend/`. `Instructions.md` Part 4.6 describes each file.
