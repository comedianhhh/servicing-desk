from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import service
from ..db import engine, get_session
from ..models import AuditLog, Base, Case, CaseStatus, Proposal
from ..state_machine import TransitionError, transition


@asynccontextmanager
async def _lifespan(_: FastAPI):
    Base.metadata.create_all(engine)  # demo; a real deployment runs migrations
    yield


app = FastAPI(title="servicing-desk", version="0.1.0", lifespan=_lifespan)


class IntakeIn(BaseModel):
    body: str
    channel: str = "mail"
    received_on: date
    sent_to_designated_address: bool = True


class ApproveIn(BaseModel):
    approved: dict
    operator: str
    expected_version: int
    exception_code: str | None = None


class LetterIn(BaseModel):
    template: str
    fields: dict
    operator: str


class TransitionIn(BaseModel):
    to: CaseStatus
    operator: str
    expected_version: int


def _case(session: Session, case_id: str) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    return case


def _view(case: Case) -> dict:
    return {
        "id": case.id,
        "status": case.status.value,
        "version": case.version,
        "case_type": case.case_type.value if case.case_type else None,
        "error_category": case.error_category.value if case.error_category else None,
        "rfi_category": case.rfi_category.value if case.rfi_category else None,
        "exception_code": case.exception_code.value if case.exception_code else None,
        "borrower_name": case.borrower_name,
        "loan_id": case.loan_id,
        "received_on": case.correspondence.received_on.isoformat(),
        "channel": case.correspondence.channel,
        "clocks": [
            {"kind": c.kind.value, "due_on": c.due_on.isoformat(), "calendar": c.calendar, "citation": c.citation, "status": c.status.value}
            for c in sorted(case.clocks, key=lambda c: c.due_on)
        ],
        "letters": [{"id": lt.id, "template": lt.template, "sent_at": lt.sent_at} for lt in case.letters],
        "proposals": [
            {"id": p.id, "model": p.model, "proposed": p.proposed, "approved": p.approved, "decided_by": p.decided_by}
            for p in case.proposals
        ],
    }


@app.post("/intake", status_code=201)
def intake(body: IntakeIn, session: Session = Depends(get_session)):
    case, created = service.intake(session, **body.model_dump())
    return {"case_id": case.id, "created": created}


@app.get("/cases")
def list_cases(status: CaseStatus | None = None, session: Session = Depends(get_session)):
    stmt = select(Case).order_by(Case.created_at.desc())
    if status:
        stmt = stmt.where(Case.status == status)
    return [_view(c) for c in session.scalars(stmt)]


@app.get("/cases/{case_id}")
def get_case(case_id: str, session: Session = Depends(get_session)):
    return _view(_case(session, case_id))


@app.get("/cases/{case_id}/audit")
def get_audit(case_id: str, session: Session = Depends(get_session)):
    rows = session.scalars(select(AuditLog).where(AuditLog.case_id == case_id).order_by(AuditLog.at))
    return [{"at": r.at, "actor": r.actor, "action": r.action, "detail": r.detail} for r in rows]


@app.post("/cases/{case_id}/proposals/{proposal_id}/approve")
def approve(case_id: str, proposal_id: str, body: ApproveIn, session: Session = Depends(get_session)):
    case = _case(session, case_id)
    proposal = session.get(Proposal, proposal_id)
    if proposal is None or proposal.case_id != case.id:
        raise HTTPException(404, "proposal not found")
    try:
        service.approve_triage(session, case, proposal, **body.model_dump())
    except (TransitionError, ValidationError, ValueError) as e:
        raise HTTPException(409, str(e)) from e
    return _view(case)


@app.post("/cases/{case_id}/letters", status_code=201)
def send_letter(case_id: str, body: LetterIn, session: Session = Depends(get_session)):
    case = _case(session, case_id)
    try:
        letter = service.send_letter(session, case, body.template, body.fields, operator=body.operator)
    except (ValidationError, ValueError, KeyError) as e:
        raise HTTPException(422, str(e)) from e
    return {"letter_id": letter.id, "body": letter.body}


@app.post("/cases/{case_id}/transition")
def do_transition(case_id: str, body: TransitionIn, session: Session = Depends(get_session)):
    case = _case(session, case_id)
    try:
        transition(session, case, body.to, actor=body.operator, expected_version=body.expected_version)
    except (TransitionError, ValueError) as e:
        raise HTTPException(409, str(e)) from e
    return _view(case)


def run() -> None:
    uvicorn.run("servicing_desk.api.main:app", host="0.0.0.0", port=8000, reload=True)
