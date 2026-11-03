# AI-Assisted Credit Memo: group presentation script (about 14 minutes)

Slides: `Credit_Memo_AI_Presentation.pptx`. Each slide's speaker notes contain the same script.

| Part | Speaker | Time | Slides |
|---|---|---|---|
| The problem | Person A | 1 min | 1–2 |
| Proposed solution | Person A | 1 min | 3 |
| Solution architecture | Person A | 1 min | 4 |
| Key design choices | Person B | 3 min | 5–8 |
| Prototype demo | Person C | 5 min | 9 |
| Limitations and future developments | Person D | 2 min | 10–11 |
| Conclusion | Person D | 1 min | 12 |
| Backup for Q&A | All | – | 13 |

Spoken parts (excluding the demo): about 1185 words, roughly 8.5 minutes at a steady pace.

## Slide 1: Title (Person A, 0:00)

(Open on this slide; introduce the team in one sentence, then move straight to the problem.)

## Slide 2: The problem (Person A, 1 min)

Before a bank lends, a credit analyst writes a credit memo. It is the basis for the committee's decision, and the formal record that approvers, internal audit and regulators look at later. To write it, the analyst pulls together fragmented sources: filings that run to hundreds of pages, internal financial systems, and the deal terms. Most of that information, over eighty percent of enterprise data, is unstructured text. Every conclusion has to be backed by evidence and properly caveated, and the analyst has to catch what is missing, what is unsupported, and where the numbers disagree. That takes days per deal. So our brief, simplified: help analysts draft the memo, from the business and financial overview to a recommended structure, in a way that is explainable, defensible to a credit committee, and reproducible at scale.

## Slide 3: Proposed solution (Person A, 1 min)

Our answer is an AI-assisted credit memo prototype. One rule runs through it: the AI drafts, Python calculates and checks, and the analyst decides. It is built around the three questions every credit memo answers. Who are they: the business overview, extracted from the borrower's own filings. Can they repay: the financial overview, with ratios, a peer comparison, and a forecast of debt service including the new loan. And how do we protect the bank: a ranked risk register, with mitigants and proposed covenants. For the analyst, that means less time collating and more time on judgement, with every statement one click from its source. For the bank, it means the same structure and checks on every deal, a full audit trail, and one pipeline that works for any borrower in the database.

## Slide 4: Solution architecture (Person A, 1 min)

Here is the workflow, left to right. Three inputs come in: the deal terms the analyst enters, the borrower's filings as PDFs, and the bank's financial database. First, the AI extracts business and debt facts from the filings, quoting the passage behind each one, and Python checks that quote is really on its page. Next, the financial analysis: Python produces every number, from the ratios to the forecast, and the AI writes commentary that quotes them. Then the AI drafts the risk register, with mitigants and proposed covenants, and writes the memo, while Python checks every figure and reference. Everything sits in one evidence store, where each item has an ID and a fixed JSON format. The analyst signs off at the three green gates, and the output is the memo plus a full audit trail. [Person B] will now explain the key choices behind this design.

## Slide 5: Design choice 1: LLM vs deterministic (Person B, 0:45)

Thanks. I'll walk through the choices behind that design. The first: use each tool for what it is good at. The language model does the qualitative work: reading hundreds of pages, extracting facts, writing commentary and identifying risks. But it never calculates a number. Every figure, from the ratios and quarter-on-quarter changes to the peer comparison and the three-scenario forecast, is calculated by Python, so the same input always gives the same answer. This follows a point from the JPMorgan session: AI is not a silver bullet, and in regulated settings it works best alongside traditional deterministic analytics.

## Slide 6: Design choice 2: external database (Person B, 0:45)

The second choice: an external financial database. In a bank, the analyst's figures come from internal systems, not from reading PDFs. So we simulated one. We took the 10-Q and 10-K filings and earnings releases for Intel, our borrower, and four peers, entered the raw figures by hand with their sources, and built the ratios an analyst uses as spreadsheet formulas: 24 metrics over four to six quarters. The app connects to it like a bank system, and every value links back to its cell. Two rules matter: each company's definitions are recorded, because DSCR, for example, is defined differently by company, and a blank input means not verified, never zero.

## Slide 7: Design choice 3: hallucination mitigation (Person B, 0:45)

Third, how we control hallucination, in three layers. Source grounding: every statement must cite an Evidence ID that exists. For document facts, Python opens the PDF and searches the cited page word for word for the AI's quote. Validation: Python checks every figure the AI quotes against its source, and rejects made-up references and any approve-or-decline recommendation. Anything that fails goes back to the AI with the errors, up to three attempts. Structured inputs and outputs: the AI gets JSON and must return JSON in a fixed schema, with fixed labels, and missing data is flagged as an information gap, never guessed. So a wrong figure is caught before anyone relies on it.

## Slide 8: Design choice 4: human-in-the-loop (Person B, 0:45)

Finally, where the human sits. The analyst signs off at three gates. In Section 2, they approve, edit or flag each extracted fact after seeing its passage highlighted on the page. In Section 3, they set the forecast assumptions, including the loan's interest rate, and approve or flag every commentary statement. A statement with a number mismatch can't just be approved: it must be corrected or flagged, and Section 4 stays locked until the analysis is approved. In Section 6, they check every memo statement against its source, and the memo can't be exported while anything is pending. That's slower than full automation, but nothing unreviewed reaches the memo. [Person C] will now show this live.

## Slide 9: Prototype demo (Person C, 5 min)

**Run-sheet.** Use a deal prepared in advance with every section already run; the AI steps take 1 to 3 minutes each.

| Time | Section | What to show |
|---|---|---|
| 0:00–0:30 | Section 1 | Deal list: open the pre-built Intel deal. Show the loan request summary and the uploaded 10-K. Say that the database connected automatically. |
| 0:30–1:15 | Section 2 | Open one 2A business fact: click its Evidence ID and show the passage highlighted on the page and the “✓ found” check. Open 2C to show the database connected. |
| 1:15–2:45 | Section 3 | Trends: point to a statement with “✓ numbers verified”, open its sources, click a CSV- ID to show the workbook cell and formula. Show a Number mismatch card with Edit / Flag. Peers: tick Revenue for AMD and NVIDIA. Forecast: lower downside revenue growth and show the results update; enter a minimum DSCR and show the red highlights. |
| 2:45–3:30 | Section 4 | Read one risk across: evidence (numbers verified), mitigant, and a covenant labelled Assumption with “Illustrative; analyst to calibrate against credit policy.” |
| 3:30–4:30 | Section 6 | Open a memo statement's source in the side panel and approve it. Click “Show only what needs attention”. Download the memo and the audit trail PDFs. |
| 4:30–5:00 | PDFs | Show the memo's [n] citations and the numbered source list, then one audit trail entry: who did what, and when. Hand over to [Person D]. |

## Slide 10: Limitations (Person D, 1 min)

Thanks. Now, what the prototype doesn't do yet. It only uses the sources it is given, so there's no news, market or industry data; gaps are flagged instead. Our database is small and hand-built: five companies, four to six quarters each, and ratio definitions differ by company. The forecast is deliberately simple: cash flow is EBITDA minus capex, before tax and working capital, and long-term debt maturities aren't included. Python checks numbers and quotes, but whether a summary is a fair reading of its source is still the analyst's call. And it is a prototype: the risk section has no approval step of its own, scanned PDFs can't be read, and it runs locally for one user without a login.

## Slide 11: Future developments (Person D, 1 min)

Here is where we would take it next. First, external news monitoring: scanning news and reports for positive or negative signals on the borrower, like the counterparty early-warning use case from the JPMorgan session. Second, enhanced forecasting: using external analyst reports and consensus estimates to set the scenarios, and adding tax, working capital and debt maturities. Third, connecting to a bank's real systems, so the database has full history for any borrower. Fourth, ongoing monitoring: tracking the proposed covenants every quarter after the loan is made. And to make it production-ready: a sign-off step for risks, a second-model check on summaries, and login with maker-checker roles.

## Slide 12: Conclusion (Person D, 1 min)

To close, back to what the project asked for. Content: the app answers all three questions in one memo: who are they, can they repay, and how do we protect the bank. Validated and defensible: every statement is grounded in a source the committee can click on, every number is calculated and checked by Python, and the analyst signs off at three gates, with an audit trail to prove it. Reproducible at scale: fixed formats, versioned prompts, and one pipeline that works for any borrower in the database. The AI drafts, Python calculates and checks, and the analyst decides. Thank you; we're happy to take questions.

## Slide 13: Appendix: likely questions (All, Q&A)

**Why no approve / decline recommendation?** Accountability stays with the analyst and committee. The app drafts the structure and terms as suggestions, with every threshold labelled an illustrative assumption.

**What stops the AI inventing numbers?** It never calculates. Every quoted figure is checked against its cited source; a mismatch must be corrected or flagged before approval.

**How does it scale to another borrower?** Add the company to the database and upload its filings: same prompts, schemas and checks. Section 3 runs as parallel requests in about a minute.

**Is it reproducible?** All numbers are deterministic. AI wording can vary between runs, so each run is logged with its prompt version, model and an input hash.

**Why simulate a database?** Banks already hold financials internally. Keeping the AI out of financial extraction removes the biggest source of error.
