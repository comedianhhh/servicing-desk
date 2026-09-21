from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from datetime import date

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import service
from ..auth import Operator, Principal, Reader
from ..db import engine, get_session
from ..models import AuditLog, Base, Case, CaseStatus, CreditHold, Document, LedgerAdjustment, Proposal, Saga
from ..state_machine import TransitionError, transition
from ..telemetry import HTTP_REQUESTS, HTTP_SECONDS, configure_logging


@asynccontextmanager
async def _lifespan(_: FastAPI):
    Base.metadata.create_all(engine)  # demo; a real deployment runs migrations
    yield


app = FastAPI(title="servicing-desk", version="0.1.0", lifespan=_lifespan)


@app.middleware("http")
async def _http_metrics(request: Request, call_next):
    # Label by route template, not path: /cases/{case_id} is one series, not one per case.
    start = time.perf_counter()
    response = await call_next(request)
    route = getattr(request.scope.get("route"), "path", request.url.path)
    if route != "/metrics":
        HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        HTTP_SECONDS.labels(request.method, route).observe(time.perf_counter() - start)
    return response


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class IntakeIn(BaseModel):
    body: str
    channel: str = "mail"
    received_on: date
    sent_to_designated_address: bool = True


# No `operator` field on any of these: the actor is whoever the bearer token says (auth.py), never the body.
class ApproveIn(BaseModel):
    approved: dict
    expected_version: int
    exception_code: str | None = None


class LetterIn(BaseModel):
    template: str
    fields: dict


class TransitionIn(BaseModel):
    to: CaseStatus
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
        "letter_text": case.correspondence.body,
        "documents": [
            {"id": d.id, "filename": d.filename, "content_type": d.content_type, "size": d.size, "pages": d.pages, "engine": d.text_engine, "sha256": d.storage_key}
            for d in case.correspondence.documents
        ],
        "created_at": case.created_at,
        "clocks": [
            {"kind": c.kind.value, "due_on": c.due_on.isoformat(), "calendar": c.calendar, "citation": c.citation, "status": c.status.value}
            for c in sorted(case.clocks, key=lambda c: c.due_on)
        ],
        "letters": [
            {"id": lt.id, "template": lt.template, "body": lt.body, "fields": lt.fields, "sent_at": lt.sent_at, "voided_at": lt.voided_at}
            for lt in case.letters
        ],
        "proposals": [
            {"id": p.id, "model": p.model, "proposed": p.proposed, "approved": p.approved, "decided_by": p.decided_by}
            for p in case.proposals
        ],
    }


@app.get("/healthz")
def healthz():
    """Liveness: the process is up. No dependencies checked, so a broken DB does not get the pod killed."""
    return {"ok": True}


@app.get("/readyz")
def readyz(session: Session = Depends(get_session)):
    """Readiness: can serve traffic — the database answers."""
    session.execute(text("select 1"))
    return {"ok": True}


@app.post("/intake", status_code=201)
def intake(body: IntakeIn, session: Session = Depends(get_session), who: Principal = Operator):
    case, created = service.intake(session, **body.model_dump())
    session.commit()
    return {"case_id": case.id, "created": created}


@app.post("/intake/document", status_code=201)
async def intake_document(
    file: UploadFile = File(...),
    channel: str = Form("mail"),
    received_on: date = Form(...),
    sent_to_designated_address: bool = Form(True),
    session: Session = Depends(get_session),
    who: Principal = Operator,
):
    """Mailroom path: the scan is archived as-is, text is derived (text layer or OCR), a case is opened."""
    data = await file.read()
    if not data:
        raise HTTPException(422, "empty file")
    try:
        case, created, doc = service.intake_document(
            session,
            data=data,
            filename=file.filename or "upload",
            content_type=file.content_type or "",
            channel=channel,
            received_on=received_on,
            sent_to_designated_address=sent_to_designated_address,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    session.commit()
    return {"case_id": case.id, "created": created, "document_id": doc.id, "engine": doc.text_engine, "pages": doc.pages}


@app.get("/documents/{document_id}")
def get_document(document_id: str, session: Session = Depends(get_session), who: Principal = Reader):
    """The original bytes, unchanged. §1024.38(c)(2): the servicing file must be retrievable."""
    from ..documents import storage

    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    return Response(storage().get(doc.storage_key), media_type=doc.content_type, headers={"content-disposition": f'inline; filename="{doc.filename}"'})


@app.get("/letters/templates")
def letter_templates(who: Principal = Reader):
    """Required contents per template, straight from the schemas — the UI renders forms from this."""
    from ..letters import TEMPLATES

    out = {}
    for name, schema in TEMPLATES.items():
        props = schema.model_json_schema().get("properties", {})
        out[name] = {
            "doc": (schema.__doc__ or "").strip(),
            "fields": [{"name": k, "required": k in schema.model_json_schema().get("required", []), "type": v.get("type", "string")} for k, v in props.items()],
        }
    return out


@app.get("/cases")
def list_cases(status: CaseStatus | None = None, session: Session = Depends(get_session), who: Principal = Reader):
    stmt = select(Case).order_by(Case.created_at.desc())
    if status:
        stmt = stmt.where(Case.status == status)
    return [_view(c) for c in session.scalars(stmt)]


@app.get("/cases/{case_id}")
def get_case(case_id: str, session: Session = Depends(get_session), who: Principal = Reader):
    return _view(_case(session, case_id))


@app.get("/cases/{case_id}/audit")
def get_audit(case_id: str, session: Session = Depends(get_session), who: Principal = Reader):
    rows = session.scalars(select(AuditLog).where(AuditLog.case_id == case_id).order_by(AuditLog.id))
    return [{"at": r.at, "actor": r.actor, "action": r.action, "detail": r.detail} for r in rows]


@app.post("/cases/{case_id}/proposals/{proposal_id}/approve")
def approve(case_id: str, proposal_id: str, body: ApproveIn, session: Session = Depends(get_session), who: Principal = Operator):
    case = _case(session, case_id)
    proposal = session.get(Proposal, proposal_id)
    if proposal is None or proposal.case_id != case.id:
        raise HTTPException(404, "proposal not found")
    if body.exception_code and not who.can("supervisor"):
        # Declining under §1024.35(g) / §1024.36(f) is a determination, not a triage edit.
        raise HTTPException(403, f"{who.name} is {who.role}; an exception determination needs supervisor")
    try:
        service.approve_triage(session, case, proposal, operator=who.name, **body.model_dump())
    except (TransitionError, ValidationError, ValueError) as e:
        raise HTTPException(409, str(e)) from e
    session.commit()
    return _view(case)


@app.post("/cases/{case_id}/letters", status_code=201)
def send_letter(case_id: str, body: LetterIn, session: Session = Depends(get_session), who: Principal = Operator):
    case = _case(session, case_id)
    try:
        letter = service.send_letter(session, case, body.template, body.fields, operator=who.name)
    except (ValidationError, ValueError, KeyError) as e:
        raise HTTPException(422, str(e)) from e
    session.commit()
    return {"letter_id": letter.id, "body": letter.body}


@app.post("/cases/{case_id}/respond", status_code=202)
def respond(case_id: str, body: LetterIn, session: Session = Depends(get_session), who: Principal = Operator):
    """Starts the Respond saga: [post correction to ledger] → deliver letter → case RESPONDED."""
    case = _case(session, case_id)
    try:
        saga = service.respond(session, case, body.template, body.fields, operator=who.name)
    except (ValidationError, ValueError, KeyError) as e:
        raise HTTPException(422, str(e)) from e
    session.commit()
    return {"saga_id": saga.id, "step": saga.step}


@app.get("/cases/{case_id}/effects")
def get_effects(case_id: str, session: Session = Depends(get_session), who: Principal = Reader):
    """What happened outside the case table: sagas, ledger postings, credit hold."""
    sagas = session.scalars(select(Saga).where(Saga.case_id == case_id).order_by(Saga.created_at))
    adjs = session.scalars(select(LedgerAdjustment).where(LedgerAdjustment.case_id == case_id))
    hold = session.get(CreditHold, case_id)
    return {
        "sagas": [
            {"id": s.id, "kind": s.kind, "state": s.state.value, "step": s.step, "attempts": s.attempts, "last_error": s.last_error, "started_by": s.started_by}
            for s in sagas
        ],
        "ledger": [{"id": a.id, "amount": a.amount, "memo": a.memo, "posted_at": a.posted_at, "reversed_at": a.reversed_at} for a in adjs],
        "credit_hold": None if hold is None else {"until": hold.until.isoformat(), "placed_at": hold.placed_at, "released_at": hold.released_at},
    }


@app.post("/cases/{case_id}/transition")
def do_transition(case_id: str, body: TransitionIn, session: Session = Depends(get_session), who: Principal = Operator):
    case = _case(session, case_id)
    try:
        transition(session, case, body.to, actor=who.name, expected_version=body.expected_version)
    except (TransitionError, ValueError) as e:
        raise HTTPException(409, str(e)) from e
    session.commit()  # before the response goes out — see get_session
    return _view(case)


def run() -> None:
    configure_logging()
    uvicorn.run("servicing_desk.api.main:app", host="0.0.0.0", port=8000, reload=os.environ.get("DESK_RELOAD") == "1")
