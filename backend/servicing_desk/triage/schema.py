"""What the model is allowed to say about a letter. Every extracted value carries the text it came from."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, PrivateAttr


class Extracted(BaseModel):
    value: str | None = Field(description="The extracted value, or null if the letter does not contain it.")
    source_quote: str | None = Field(description="Verbatim excerpt from the letter that supports the value. Null if value is null.")


class ThreeElements(BaseModel):
    """§1024.35(a) / §1024.36(a): name, information enabling the servicer to identify the account, and the
    asserted error / requested information."""

    borrower_name: Extracted
    loan_identifier: Extracted
    assertion_or_request: Extracted


class TriageProposal(BaseModel):
    case_type: Literal["NOE", "RFI", "PAYOFF_REQUEST", "LOSS_MIT", "NOT_COVERED"]
    error_category: Literal["b1", "b2", "b3", "b4", "b5", "b6", "b7", "b8", "b9", "b10", "b11"] | None = Field(
        description="Only for NOE. §1024.35(b)(1)-(11). Sets the response clock: b6 = 7 days, b9/b10 = before sale or 30 days, else 30 days."
    )
    rfi_category: Literal["OWNER_IDENTITY", "OTHER"] | None = Field(
        description="Only for RFI. OWNER_IDENTITY (identity of owner/assignee, 10 days) or OTHER (30 days)."
    )
    three_elements: ThreeElements
    exception_candidates: list[Literal["DUPLICATIVE", "OVERBROAD", "UNTIMELY", "CONFIDENTIAL", "IRRELEVANT", "BURDENSOME"]] = Field(
        description="Flags for the operator to check. DUPLICATIVE/UNTIMELY cannot be decided from the letter alone."
    )
    mentions_foreclosure_sale_date: Extracted
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(description="One or two sentences the operator can verify against the letter.")
    # Set by the scoring provider: per-field probability distributions and diagnostics. Not part of the
    # model-facing schema; read by the evals.
    _scores: dict | None = PrivateAttr(default=None)
