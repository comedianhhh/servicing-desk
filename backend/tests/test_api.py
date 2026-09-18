"""End-to-end through HTTP: intake → (fake) triage → approve → L1 → investigating → L3 → responded → closed."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from servicing_desk import outbox
from servicing_desk.api import main
from servicing_desk.db import get_session
from servicing_desk.models import Base
from servicing_desk.triage.schema import TriageProposal
from servicing_desk.workers import triage_worker
from tests.conftest import NOE_LETTER, proposal_dict


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Local = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def _session():
        s = Local()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(main, "engine", engine)
    main.app.dependency_overrides[get_session] = _session
    monkeypatch.setattr(triage_worker, "propose", lambda body: (TriageProposal.model_validate(proposal_dict()), "fake"))
    with TestClient(main.app) as c:
        yield c, Local
    main.app.dependency_overrides.clear()


def test_full_noe_lifecycle(client):
    c, Local = client
    r = c.post("/intake", json={"body": NOE_LETTER, "channel": "mail", "received_on": "2026-09-01"})
    assert r.status_code == 201 and r.json()["created"] is True
    case_id = r.json()["case_id"]

    # same letter again by email → same case, nothing new opened
    r = c.post("/intake", json={"body": NOE_LETTER, "channel": "email", "received_on": "2026-09-02"})
    assert r.json() == {"case_id": case_id, "created": False}

    # worker pass (in-process relay) records the proposal
    with Local() as s:
        outbox.relay_once(s)
        s.commit()
    case = c.get(f"/cases/{case_id}").json()
    assert case["status"] == "TRIAGE" and len(case["proposals"]) == 1
    pid = case["proposals"][0]["id"]

    # operator approves with an edit (b5 → b11); stale version is rejected first
    r = c.post(f"/cases/{case_id}/proposals/{pid}/approve", json={"approved": proposal_dict(), "operator": "op-1", "expected_version": 99})
    assert r.status_code == 409
    r = c.post(
        f"/cases/{case_id}/proposals/{pid}/approve",
        json={"approved": proposal_dict(error_category="b11"), "operator": "op-1", "expected_version": case["version"]},
    )
    assert r.status_code == 200, r.text
    case = r.json()
    assert case["status"] == "ACK_PENDING" and case["error_category"] == "b11"
    assert {k["kind"] for k in case["clocks"]} == {"ACK", "RESPONSE", "CREDIT_REPORTING_HOLD"}

    # cannot move to INVESTIGATING without the acknowledgment letter
    r = c.post(f"/cases/{case_id}/transition", json={"to": "INVESTIGATING", "operator": "op-1", "expected_version": case["version"]})
    assert r.status_code == 409 and "L1" in r.json()["detail"]

    # letter with a missing required field is refused; complete one is accepted
    r = c.post(f"/cases/{case_id}/letters", json={"template": "L1", "fields": {"received_on": "2026-09-01"}, "operator": "op-1"})
    assert r.status_code == 422
    r = c.post(f"/cases/{case_id}/letters", json={"template": "L1", "fields": {"received_on": "2026-09-01", "reference": case_id}, "operator": "op-1"})
    assert r.status_code == 201

    r = c.post(f"/cases/{case_id}/transition", json={"to": "INVESTIGATING", "operator": "op-1", "expected_version": case["version"]})
    assert r.status_code == 200 and r.json()["status"] == "INVESTIGATING"
    v = r.json()["version"]

    r = c.post(
        f"/cases/{case_id}/letters",
        json={"template": "L3", "fields": {"reasons": "fee is contractual", "how_to_request_documents": "write to PO Box 1", "contact_phone": "800-555-0100"}, "operator": "op-1"},
    )
    assert r.status_code == 201
    r = c.post(f"/cases/{case_id}/transition", json={"to": "RESPONDED", "operator": "op-1", "expected_version": v})
    assert r.status_code == 200
    r = c.post(f"/cases/{case_id}/transition", json={"to": "CLOSED", "operator": "op-1", "expected_version": r.json()["version"]})
    assert r.status_code == 200 and r.json()["status"] == "CLOSED"

    audit = c.get(f"/cases/{case_id}/audit").json()
    actions = [a["action"] for a in audit]
    assert actions[:3] == ["intake", "intake.duplicate", "triage.proposed"]
    assert "triage.approved" in actions and actions.count("letter.sent") == 2
    approved = next(a for a in audit if a["action"] == "triage.approved")
    assert approved["detail"]["edited_fields"] == ["error_category"]
