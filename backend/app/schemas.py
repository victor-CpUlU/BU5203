"""Fixed JSON output schemas for every AI task (Req 1.3, 25.3). Unknown keys and values are rejected."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

BUSINESS_FIELDS = [
    ("business_description", "Business description"),
    ("industry_and_business_model", "Industry and business model"),
    ("key_revenue_drivers", "Key revenue drivers"),
    ("main_products_services", "Main products / services"),
    ("geographic_exposure", "Geographic exposure"),
    ("main_customers", "Main customers"),
    ("main_suppliers", "Main suppliers"),
    ("capital_intensity_and_investment_plans", "Capital intensity and major investment plans"),
    ("management_and_ownership", "Management and ownership"),
]
DEBT_FIELDS = [
    ("existing_debt_obligations", "Existing debt obligations"),
    ("debt_maturity_profile", "Debt maturity profile"),
    ("interest_obligations", "Interest obligations"),
    ("secured_vs_unsecured_debt", "Secured versus unsecured debt"),
    ("existing_financing_arrangements", "Existing financing arrangements"),
    ("financial_covenants", "Financial covenants"),
    ("upcoming_maturities_and_refinancing", "Upcoming maturities and refinancing requirements"),
]
PANEL_KEYS = ["profitability", "leverage", "liquidity", "cash_flow", "debt_servicing"]
REPAYMENT_DIMENSIONS = ["profitability", "cash_generation", "leverage", "liquidity", "debt_servicing"]

MEMO_OUTLINE = [
    (1, "Executive Summary", [("borrower_and_facility", "Borrower and facility"), ("purpose", "Purpose"),
                              ("key_strengths_and_risks", "Key strengths and risks")]),
    (2, "Business Overview", [("business_model_and_industry", "Business model and industry"), ("revenue_sources", "Revenue sources"),
                              ("management_ownership", "Management / ownership")]),
    (3, "Financial Analysis", [("revenue_and_profitability", "Revenue and profitability"), ("cash_flow_and_liquidity", "Cash flow and liquidity"),
                               ("leverage_and_historical_trends", "Leverage and historical trends")]),
    (4, "Repayment Capacity", [("cash_generation", "Cash generation"), ("dscr_and_debt_servicing", "DSCR and debt-servicing capacity"),
                               ("existing_debt_obligations", "Existing debt obligations"),
                               ("forecast_and_scenarios", "Forecast and scenario analysis")]),
    (5, "Key Credit Risks", [("financial_risks", "Financial"), ("business_operational_risks", "Business and operational"),
                             ("industry_external_risks", "Industry and external")]),
    (6, "Risk Mitigants / Proposed Loan Structure", [("suggested_covenants", "Suggested covenants"), ("collateral_and_security", "Collateral and security"),
                                                     ("tenor_and_repayment", "Tenor and repayment structure"),
                                                     ("monitoring_requirements", "Monitoring requirements")]),
    (7, "Information Gaps", [("missing_information", "Missing information or documents"), ("conflicting_information", "Conflicting information"),
                             ("unsupported_statements", "Unsupported statements")]),
]
PLACEHOLDER = "Not available in the documents provided."
CALIBRATION = "Illustrative; analyst to calibrate against credit policy."

Label = Literal["Sourced", "ASSUMPTION", "NOT VERIFIED"]
Level = Literal["High", "Medium", "Low"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- Section 2
class S2AItem(Strict):
    field: Literal[tuple(k for k, _ in BUSINESS_FIELDS)]  # type: ignore[valid-type]
    statement: str
    doc_id: str
    page: int = Field(ge=1)
    section_heading: str
    excerpt: str


class S2BItem(Strict):
    field: Literal[tuple(k for k, _ in DEBT_FIELDS)]  # type: ignore[valid-type]
    statement: str
    doc_id: str
    page: int = Field(ge=1)
    section_heading: str
    excerpt: str
    item_key: str | None = None
    as_of: str | None = None


class S2AOutput(Strict):
    items: list[S2AItem]


class S2BOutput(Strict):
    items: list[S2BItem]


# --------------------------------------------------------------------------- Section 3
class Claim(Strict):
    metric_key: str
    from_period: str
    to_period: str
    direction: Literal["up", "down", "~"]
    quoted_change: str


class S3Statement(Strict):
    text: str
    label: Label
    refs: list[str]
    claims: list[Claim] = []


class S3Panel(Strict):
    panel: Literal[tuple(PANEL_KEYS)]  # type: ignore[valid-type]
    statements: list[S3Statement] = Field(min_length=1)


class S3Repayment(Strict):
    dimension: Literal[tuple(REPAYMENT_DIMENSIONS)]  # type: ignore[valid-type]
    supports: list[S3Statement] = Field(min_length=1)
    weakens: list[S3Statement] = Field(min_length=1)


class S3Output(Strict):
    panels: list[S3Panel]
    cross_metric: list[S3Statement] = []
    repayment_capacity: list[S3Repayment]
    forecast: list[S3Statement] = []


# --------------------------------------------------------------------------- Section 4
class S4Text(Strict):
    text: str
    refs: list[str]


class S4Term(Strict):
    term_type: Literal["Covenant", "Reporting / Monitoring", "Structural Protection"]
    text: str
    label: Label
    refs: list[str] = []


class S4Risk(Strict):
    rank: int = Field(ge=1)
    identified_risk: str
    category: Literal["Financial", "Business and Operational", "Industry and External"]
    impact: Level
    likelihood: Level
    evidence: S4Text
    time_horizon: str
    business_context: S4Text | None = None
    mitigants: list[str] = Field(min_length=1)
    terms: list[S4Term] = Field(min_length=1)


class S4Output(Strict):
    risks: list[S4Risk] = Field(max_length=5)
    limitations: list[str] = []


# --------------------------------------------------------------------------- Section 5
class S5Statement(Strict):
    text: str
    label: Label
    refs: list[str]


class S5Subsection(Strict):
    key: str
    statements: list[S5Statement] = Field(min_length=1)


class S5Section(Strict):
    number: int
    title: str
    subsections: list[S5Subsection]


class S5Output(Strict):
    sections: list[S5Section]


# --------------------------------------------------------------------------- Section 6
class S6Assessment(Strict):
    statement_id: str
    assessment: Literal["Supported", "Partially supported", "Not supported"]
    reason: str = Field(max_length=300)


class S6Output(Strict):
    assessments: list[S6Assessment]


SCHEMAS = {"S2A": S2AOutput, "S2B": S2BOutput, "S3": S3Output, "S4": S4Output, "S5": S5Output, "S6": S6Output}
