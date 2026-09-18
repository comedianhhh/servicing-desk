"""Letter templates whose required contents are a schema, not a reviewer's memory.

CFPB Supervisory Highlights 33 (2024) cited servicers for acknowledgment letters missing a required
statement. Here a letter cannot be rendered unless every field the rule names is present.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .models import Case, Letter


class _Fields(BaseModel):
    model_config = ConfigDict(extra="forbid")


class L1Acknowledgment(_Fields):
    """§1024.35(d) / §1024.36(c): acknowledge receipt within 5 bd."""

    received_on: str
    reference: str


class L2Correction(_Fields):
    """§1024.35(e)(1)(i)(A): what was corrected, effective date, contact info incl. phone. (e)(2): additional
    errors found during investigation, each with action taken and effective date."""

    correction_made: str
    effective_date: str
    contact_phone: str
    additional_errors: list[dict] = Field(default_factory=list)


class L3NoError(_Fields):
    """§1024.35(e)(1)(i)(B): statement that no error occurred, reasons, right to request relied-upon
    documents, how to request them, contact phone."""

    reasons: str
    how_to_request_documents: str
    contact_phone: str


class L4Extension(_Fields):
    """§1024.35(e)(3)(ii) / §1024.36(d)(2)(ii): extension + reasons, sent before the original due date."""

    original_due_on: str
    new_due_on: str
    reasons: str


class L5Exception(_Fields):
    """§1024.35(g)(2) / §1024.36(f)(2): determination not to respond + the basis."""

    exception_code: str
    basis: str


class L6DocumentsProvided(_Fields):
    """§1024.35(e)(4): relied-upon documents, free of charge; withheld privileged parts explained."""

    documents: list[str]
    withheld: list[dict] = Field(default_factory=list)


class RfiResponse(_Fields):
    """§1024.36(d)(1)(i)/(ii): the information + phone, or a statement it is not available + basis + phone."""

    information: str | None = None
    not_available_basis: str | None = None
    contact_phone: str


class PayoffStatement(_Fields):
    """§1026.36(c)(3): accurate total outstanding balance as of a specified date."""

    as_of_date: str
    total_balance: str


TEMPLATES: dict[str, type[_Fields]] = {
    "L1": L1Acknowledgment,
    "L2": L2Correction,
    "L3": L3NoError,
    "L4": L4Extension,
    "L5": L5Exception,
    "L6": L6DocumentsProvided,
    "RFI_RESPONSE": RfiResponse,
    "PAYOFF": PayoffStatement,
}

_BODY = {
    "L1": "We received your correspondence dated {received_on} (reference {reference}) and are reviewing it.",
    "L2": "We corrected the following: {correction_made}, effective {effective_date}. Questions: {contact_phone}.",
    "L3": (
        "After investigation we determined that no error occurred. Reasons: {reasons}. You may request the "
        "documents we relied on, free of charge: {how_to_request_documents}. Questions: {contact_phone}."
    ),
    "L4": "We need additional time to respond. Original date {original_due_on}; new date {new_due_on}. Reason: {reasons}.",
    "L5": "We have determined that we are not required to respond ({exception_code}). Basis: {basis}.",
    "L6": "Enclosed are the documents we relied on: {documents}.",
    "RFI_RESPONSE": "{information}{not_available_basis} Questions: {contact_phone}.",
    "PAYOFF": "Total amount required to pay your loan in full as of {as_of_date}: {total_balance}.",
}


def render(case: Case, template: str, fields: dict) -> Letter:
    """Validate against the rule's required contents, then render. Raises pydantic.ValidationError otherwise."""
    schema = TEMPLATES[template]
    validated = schema.model_validate(fields)
    if template == "RFI_RESPONSE" and not (validated.information or validated.not_available_basis):
        raise ValueError("RFI response needs either the information or a not-available basis")
    data = validated.model_dump()
    if template == "RFI_RESPONSE":
        data["information"] = data["information"] or ""
        data["not_available_basis"] = (
            f" The information is not available to the servicer: {data['not_available_basis']}."
            if data["not_available_basis"]
            else ""
        )
    if template == "L6":
        data["documents"] = ", ".join(data["documents"])
    body = _BODY[template].format(**data)
    return Letter(case_id=case.id, template=template, fields=validated.model_dump(), body=body)
