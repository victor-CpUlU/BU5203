# AI-Assisted Credit Memo: presentation script (about 4 minutes)

Slides: `Credit_Memo_AI_Presentation.pptx` (the same script is in each slide's speaker notes).

About 547 words, roughly 4 minutes at a steady speaking pace. Times are approximate starts.

## Slide 1 (0:00): Title

Good morning. Our project is an AI-assisted credit memo tool. Its whole design fits in one line: the AI drafts, Python calculates and checks, and the analyst decides.

## Slide 2 (0:10): The problem

Today a credit analyst spends days reading filings that run to hundreds of pages, re-typing ratios, and writing each memo from scratch. Then the committee asks: where does this number come from? Generative AI could do the drafting in minutes, but it can invent facts, it's hard to trace, and it gives different answers each run. So our goal was simple: help the analyst draft the memo, from the business and financials to a recommended structure, in a way that is explainable, defensible to a committee, and reproducible at scale.

## Slide 3 (0:45): Three questions

We framed the tool around the three questions every credit memo has to answer. One: who are they? Two: can they repay? Three: how do we structure the loan to protect the bank? The app walks the analyst through exactly that path, in six steps, ending in an exported memo and a full audit trail.

## Slide 4 (1:05): 1. Who are they? (Business overview)

For question one, who are they, the AI reads the borrower's filings and extracts business and debt facts. The key decision: every fact must quote the exact passage it came from. Python then confirms that passage really is on the cited page, and the analyst can click any fact and see the page with the passage highlighted.

## Slide 5 (1:30): 2. Can they repay? (Financial overview)

Question two, can they repay, is where AI is most dangerous, so here the AI calculates nothing. Every ratio comes from the financial database, a workbook covering Intel and four peers. Python computes the changes, the peer comparison, and a base, upside and downside forecast of debt service, using assumptions the analyst can change. The AI only writes commentary, and Python checks every number it quotes against the source. A wrong figure is flagged before anyone relies on it.

## Slide 6 (2:10): 3. How do we protect the bank? (Risk and structuring)

For question three, the AI builds a ranked risk register with mitigants and proposed covenants, then drafts the memo. But these are suggestions only. Any covenant threshold is labelled an illustrative assumption for the analyst to calibrate, and the AI is never allowed to recommend approve or decline. The credit decision stays with the analyst.

## Slide 7 (2:35): Design decisions

Each requirement became a design rule. Explainable: every statement carries an Evidence ID, so one click shows the PDF passage, the database cell or the forecast value behind it. Defensible: Python produces every number and checks every quoted figure, missing data is flagged rather than filled, and the audit trail records who changed what. Reproducible: fixed output formats, versioned prompts, and one pipeline that works for any company in the database.

## Slide 8 (3:05): Trade-offs

These choices have costs, and we made them on purpose. We kept a closed source boundary, so there's no market data, and gaps are flagged instead. We added approval gates, which is slower than full automation but means nothing unreviewed reaches the memo. We kept the forecast simple so every line can be explained. And code checks numbers, not meaning: whether a summary is faithful to its source is still the analyst's call.

## Slide 9 (3:40): Close

So the result: a full draft memo in minutes rather than days, where every figure traces back to its source, and the analyst stays in control and accountable. The AI drafts, Python checks, and the analyst decides. Thank you.
