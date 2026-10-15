# AI-Assisted Credit Analysis: User Guide

This app helps a credit analyst decide whether a borrower can support a specific loan request. The analyst uploads the borrower's filings and a financial database (CSV). The AI extracts information and drafts the analysis and credit memo. Python checks every figure and citation, and the analyst reviews and approves everything before the final memo is produced.

> The app runs only on your own computer and has **no login**. Do not put it on a shared network without adding access control.

> **Developers:** this file is the user guide. For the design spec, pipeline rules, data conventions and the AI prompts, see [`Instructions.md`](Instructions.md). See [section 8](#8-for-developers) for the developer workflow.

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
- **The financial database is connected automatically.** You don't load or upload it. The app fetches the borrower's figures from the external financial database (by default `intel_quarterly_ratios.csv`) as soon as you create the deal, and shows them in Section 2. See [section 5](#5-financial-database-csv-format) for the format the database uses.

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

**2C Financial data (external database).** Below 2A and 2B, Section 2 shows the figures fetched automatically from the external financial database when the deal was created, with a note that they come from the database. The AI never extracts or calculates these numbers; Python loads them exactly as stored (with Pandas). This card lists the periods and metrics found, the **values flagged for review** and the **information gaps**. Each value has a `CSV-` Evidence ID used throughout the memo.

### Section 3: Financial dashboard and AI analysis

The dashboard shows five panels: **Profitability, Leverage, Liquidity, Cash Flow and Debt Servicing**.

- **Charts** use the CSV values exactly. A triangle marker means the value is flagged. Each panel has a **data table** (click to expand) and lists any metrics that are **not available in database**.
- Click **Run AI financial analysis**. The AI commentary appears beside each chart. Python then checks each statement and marks it:
  - **Numbers verified**: every figure matches the cited data.
  - **Number mismatch**: something doesn't match. The unmatched values are listed.
- The **Divergence patterns** table shows the five patterns from the Project Details. With the current CSV they are all **Not assessable**, because Revenue, EBITDA, Debt and Cash are not in the database.

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

The app adds the information gaps and flagged database values to Section 7 itself. There is **no AI recommendation**; the analyst decides.

Regenerating the memo replaces it and resets all Section 6 reviews.

### Section 6: Review, verify and export

1. **Click an Evidence ID** on a statement. The source panel on the right shows:
   - for a document, the document name, page, supporting text and an image of the page with the passage highlighted;
   - for a CSV value, the file, metric, period column and value, with any flags.
   If the passage cannot be found on the page, the statement is **flagged automatically**.
2. Compare the statement with its source. A citation to a real page does not by itself mean the statement is correct.
3. Use **Approve**, **Flag** (with an optional note) or **Correct**. A corrected statement goes back to **Pending** until you approve it again.
4. Use the filter buttons (All / Pending / Approved / Flagged) to find what still needs review. Statements based only on database values that you already approved in Section 3 start as Approved.
5. **Download final Credit Memo PDF.** This works only when no statement is Pending. Flagged statements are kept in the PDF and marked **FLAGGED**, and every statement keeps its source citations.
6. **Download Audit Trail PDF.** This lists every statement with its sources, supporting text or CSV values, status, corrections and who made them, plus the Section 3 review. You can download it at any time after the memo exists.

**Optional AI support check.** Set `SUPPORT_CHECK_ENABLED=true` in `.env` to show a **Run AI support check** button. It gives an advisory "Supported / Partially supported / Not supported" rating for each statement and never changes a status.

### Re-running earlier steps

If you re-run an earlier step (for example re-extract documents), the later steps are marked **"Out of date"**. Re-run them so the memo matches the latest data. The financial database is connected once when the deal is created; to pick up changed figures, start a new deal.

---

## 4. Where things are saved

- Each deal is stored in `data/deals/<deal id>/`. This folder holds the uploaded PDFs, the extracted evidence, the outputs of each section, `audit_trail.json` and the exported PDFs in `exports/`.
- The audit trail is append-only: earlier entries are never changed.
- To remove all deals, close the app and delete the `data` folder.
- `.env`, `.venv` and `data` are excluded from Git, so your API key and borrower documents are not uploaded to GitHub.

---

## 5. Financial database (CSV) format

```
Metric,Q2 2026 (Jun 27 2026),Q1 2026 (Mar 28 2026),Q4 2025 (Dec 27 2025),Q3 2025 (Sep 27 2025)
Revenue Growth,25.40%,7.18%,-4.11%,2.78%
Debt/EBITDA,4.11x,6.37x,4.93x,5.23x
Operating Cash Flow,7006,1096,4288,2546
```

- **First column:** must be headed `Metric`.
- **Period headers:** must look like `Q2 2026 (Jun 27 2026)`. They can be in any order; the app sorts them oldest to newest.
- **Recognised metrics:** Revenue Growth, EBITDA Margin, Debt/EBITDA, Interest Coverage, Current Ratio, Debt-Service Coverage Ratio (DSCR), Operating Cash Flow, Operating Cash Flow Margin, Working Capital, Days Sales Outstanding (DSO). Any other rows are kept and marked "Unrecognised metric".
- **Values:** `25.40%`, `4.11x`, or a plain number. Empty or text cells show as "Not available in database".
- **Several borrowers in one file (optional):** add a `Borrower` column. The app then uses only the rows matching the deal's borrower name. Without a `Borrower` column, the whole file is treated as this borrower's data and the app records the information gap "Database has no borrower identifier".
- **Which file is used:** the app always connects to the default database set by `financial_db_path` (by default `intel_quarterly_ratios.csv` in the project folder). The connection happens automatically when a deal is created.

---

## 6. Frequently asked questions

**Do I need to put 10-K or 10-Q files in the project folder first?**
No. The analyst uploads the borrower's documents inside the app (Section 1 → Documents), like an AI credit memo tool. Nothing needs to be in the project folder except the financial database file the app connects to.

**Where do the financial figures come from? I never loaded them.**
The app simulates a connection to an external financial database and fetches the figures automatically when you create the deal, so there is no load or upload step. They appear in Section 2 (2C) with a note that they come from the database, and in the Section 3 dashboard. The default database is `intel_quarterly_ratios.csv` (set by `financial_db_path`).

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
| Section 2 shows "Could not connect to the financial database" | The database file is missing or malformed. Check that `financial_db_path` points to a valid CSV (default `intel_quarterly_ratios.csv`, see [section 5](#5-financial-database-csv-format) for the format), then create the deal again. |
| A section "failed" | Expand **Last run failed** to see why. Earlier results are kept, so you can simply run it again. |
| "No relevant pages were found" | The PDF may be scanned (no text), or may not cover that topic. Upload a text-based PDF. |
| Section 4 or 5 button is greyed out | Approve Section 3 first (for Section 4), or complete Section 4 (for Section 5). |
| "Not located" on an Evidence ID | The AI's quote could not be found on that page. Open the page, check the statement, and flag or correct it. |

---

## 8. For developers

- **Prompts:** the AI prompts live in `Instructions.md` (Parts 5 and 6). After editing a prompt, run `.venv\Scripts\python tools\sync_prompts.py` to update the copies the app loads from `backend\app\prompts\`.
- **Thresholds and keywords:** large-swing and stable-band thresholds, page-selection keywords and size limits are set in `config/analysis.toml`. The PDF upload limit is `max_upload_mb` (default 200 MB) and the CSV limit is `max_csv_mb`.
- **Tests:** run `.venv\Scripts\python -m pytest`. The tests use a simulated AI, so they need no API key or internet connection.
- **Code layout:** the backend (Python/FastAPI) is in `backend/app/` and the frontend (HTML/CSS/JavaScript) is in `frontend/`. `Instructions.md` Part 4.6 describes each file.
