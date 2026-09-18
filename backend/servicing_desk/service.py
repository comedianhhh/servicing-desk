"""Use cases the API and workers call. Each function is one transaction's worth of work on an open session."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import letters as letters_mod
from .models import (
    Case,
    CaseStatus,
    CaseType,
    Correspondence,
    ErrorCategory,
    ExceptionCode,
    Proposal,
    RfiCategory,
)
from .state_machine import TransitionError, audit, emit, transition
from .triage.schema import TriageProposal


def idempotency_key(body: str) -> str:
    normalized = re.sub(r"\s+", " ", body).strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()


def intake(
    session: Session,
    *,
    body: str,
    channel: str,
    received_on: date,
    sent_to_designated_address: bool = True,
    actor: str = "system:intake",
) -> tuple[Case, bool]:
    """Open a case for a letter. Returns (case, created). A duplicate body returns the existing case."""
    key = idempotency_key(body)
    existing = session.scalar(select(Correspondence).where(Correspondence.idempotency_key == key))
    if existing is not None and existing.case is not None:
        audit(session, existing.case.id, actor, "intake.duplicate", {"channel": channel})
        return existing.case, False
    corr = Correspondence(
        idempotency_key=key,
        channel=channel,
        received_on=received_on,
        sent_to_designated_address=sent_to_designated_address,
        body=body,
    )
    case = Case(correspondence=corr, status=CaseStatus.RECEIVED)
    session.add(case)
    session.flush()
    audit(session, case.id, actor, "intake", {"channel": channel, "received_on": received_on.isoformat()})
    emit(session, case, "correspondence.received", {"channel": channel})
    return case, True


def record_proposal(session: Session, case: Case, proposal: TriageProposal, model: str) -> Proposal:
    p = Proposal(case_id=case.id, model=model, proposed=proposal.model_dump())
    case.proposals.append(p)
    session.flush()  # callers get p.id
    audit(session, case.id, f"llm:{model}", "triage.proposed", {"confidence": proposal.confidence})
    if case.status == CaseStatus.RECEIVED:
        transition(session, case, CaseStatus.TRIAGE, actor="system:triage")
    return p


_TARGET = {
    "NOE": CaseStatus.ACK_PENDING,
    "RFI": CaseStatus.ACK_PENDING,
    "PAYOFF_REQUEST": CaseStatus.PAYOFF_REQUEST,
    "LOSS_MIT": CaseStatus.ROUTED_LOSS_MIT,
    "NOT_COVERED": CaseStatus.NOT_COVERED,
}


def approve_triage(
    session: Session,
    case: Case,
    proposal: Proposal,
    *,
    approved: dict,
    operator: str,
    expected_version: int,
    exception_code: str | None = None,
    today: date | None = None,
) -> Case:
    """The operator's decision. `approved` is the (possibly edited) proposal; it — not the LLM output — is
    what gets written to the case. Passing an exception_code sends the case to EXCEPTION_REVIEW instead."""
    if proposal.decided_at is not None:
        raise TransitionError("proposal already decided")
    final = TriageProposal.model_validate(approved)
    proposal.approved = final.model_dump()
    proposal.decided_by = operator
    proposal.decided_at = datetime.now(UTC)

    case.case_type = CaseType(final.case_type)
    case.error_category = ErrorCategory(final.error_category) if final.error_category else None
    case.rfi_category = RfiCategory(final.rfi_category) if final.rfi_category else None
    case.borrower_name = final.three_elements.borrower_name.value
    case.loan_id = final.three_elements.loan_identifier.value
    case.three_elements_ok = all(
        e.value for e in (final.three_elements.borrower_name, final.three_elements.loan_identifier, final.three_elements.assertion_or_request)
    )
    changed = {k: (proposal.proposed.get(k), v) for k, v in proposal.approved.items() if proposal.proposed.get(k) != v}
    audit(session, case.id, operator, "triage.approved", {"proposal_id": proposal.id, "edited_fields": sorted(changed)})

    if exception_code:
        case.exception_code = ExceptionCode(exception_code)
        return transition(session, case, CaseStatus.EXCEPTION_REVIEW, actor=operator, expected_version=expected_version, today=today)
    return transition(session, case, _TARGET[final.case_type], actor=operator, expected_version=expected_version, today=today)


def send_letter(session: Session, case: Case, template: str, fields: dict, *, operator: str) -> letters_mod.Letter:
    letter = letters_mod.render(case, template, fields)
    letter.sent_at = datetime.now(UTC)  # step 2: sent_at is set by the letter worker after delivery
    case.letters.append(letter)
    audit(session, case.id, operator, "letter.sent", {"template": template, "letter_id": letter.id})
    emit(session, case, "letter.requested", {"template": template, "letter_id": letter.id})
    return letter
