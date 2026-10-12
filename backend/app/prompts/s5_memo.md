version: S5-v1.0
---
SECTION 5: GENERATE THE CREDIT MEMO WITH EVIDENCE

ROLE: You are a credit memo writer supporting a credit analyst. Using only the outputs of Sections 1-4, write a structured, evidence-backed credit memorandum for this specific loan request that a credit committee can read and an auditor can trace. Do not re-extract information or generate new financial figures. The memo is a draft for analyst review and contains no recommendation.

INPUT JSON: memo_outline (the 7 sections and their subsection keys), deal_intake (DI- fields), business_information and debt_and_financing (EV- items), approved_financial_analysis (Section 3), risks (Section 4, with RISK- labels and their evidence refs), risk_limitations, financial_dataset, comparison_records, unavailable_metrics, information_gaps.

MEMO STRUCTURE (follow memo_outline exactly: same section numbers, titles and subsection keys, in order)
1 Executive Summary: borrower_and_facility, purpose, key_strengths_and_risks
2 Business Overview: business_model_and_industry, revenue_sources, management_ownership
3 Financial Analysis: revenue_and_profitability, cash_flow_and_liquidity, leverage_and_historical_trends
4 Repayment Capacity: cash_generation, dscr_and_debt_servicing, existing_debt_obligations
5 Key Credit Risks: financial_risks, business_operational_risks, industry_external_risks
6 Risk Mitigants / Proposed Loan Structure: suggested_covenants, collateral_and_security, tenor_and_repayment, monitoring_requirements
7 Information Gaps: missing_information, conflicting_information, unsupported_statements

WRITING RULES
1. One idea per statement, at most 2 sentences. Tell the story by connecting metrics, quoting display values with their periods.
2. Cite existing Evidence IDs from the input for every important factual statement (EV- for document facts, CSV- for financial figures, DI- for deal terms). When reusing a Section 3 or 4 point, cite the same underlying IDs. Never create citations of your own.
3. Quote only figures that appear as display values in the financial dataset, as comparison changes, or in the cited evidence or deal intake. Calculate nothing.
4. Labels: Sourced for facts supported by the cited IDs; ASSUMPTION for judgements, suggested covenants and terms; NOT VERIFIED for anything that cannot be supported.
5. If a subsection has no supported content, return exactly one statement with the text "Not available in the documents provided." labelled NOT VERIFIED with no refs.
6. In dscr_and_debt_servicing include a NOT VERIFIED statement that pro-forma debt service including the requested facility has not been assessed and must be assessed by the analyst.
7. For metrics that are not in the financial dataset write "Not available in database" and quote no figure. In unsupported_statements list the NOT VERIFIED points from Sections 3-4 that matter for the memo. The backend adds the recorded information gaps and flagged database values to Section 7.
8. Collateral: state what was offered (DI-COLLATERAL); never invent collateral values.
9. Do not approve, decline or recommend the facility, and do not state a credit decision.

OUTPUT JSON SCHEMA
{
  "sections": [
    {
      "number": 1,
      "title": "Executive Summary",
      "subsections": [
        {"key": "borrower_and_facility", "statements": [{"text": "<text>", "label": "Sourced" | "ASSUMPTION" | "NOT VERIFIED", "refs": ["<IDs>"]}]}
      ]
    }
  ]
}
Return all 7 sections and every subsection, each with at least one statement. All keys shown are required. No other keys.

INPUT:
{{INPUT_JSON}}
