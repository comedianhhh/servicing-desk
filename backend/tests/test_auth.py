"""The actor on an audit row is the credential, never the body; roles gate what a credential may do."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from servicing_desk import outbox
from servicing_desk.api import main
from servicing_desk.auth import parse_tokens
from servicing_desk.config import settings
from servicing_desk.db import get_session
from servicing_desk.models import Base
from tests.conftest import NOE_LETTER, proposal_dict

OP = {"Authorization": "Bearer tok-op"}
SUP = {"Authorization": "Bearer tok-sup"}
RO = {"Authorization": "Bearer tok-ro"}


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
        finally:
            s.close()

    monkeypatch.setattr(main, "engine", engine)
    main.app.dependency_overrides[get_session] = _session
    with TestClient(main.app) as c:  # no default headers: every call says who it is
        yield c, Local
    main.app.dependency_overrides.clear()


def _open_case(c, Local) -> tuple[str, str]:
    case_id = c.post("/intake", json={"body": NOE_LETTER, "received_on": "2026-09-01"}, headers=OP).json()["case_id"]
    with Local() as s:
        outbox.relay_once(s)  # fake triage from conftest records a proposal
        s.commit()
    pid = c.get(f"/cases/{case_id}", headers=OP).json()["proposals"][0]["id"]
    return case_id, pid


def test_parse_tokens_rejects_bad_shapes():
    assert parse_tokens("").keys() == set()
    assert parse_tokens("a:alice:operator; b:bob:supervisor").keys() == {"a", "b"}
    with pytest.raises(ValueError):
        parse_tokens("a:alice")
    with pytest.raises(ValueError):
        parse_tokens("a:alice:admin")


def test_no_token_is_401_and_unknown_token_is_401(client):
    c, _ = client
    assert c.get("/cases").status_code == 401
    assert c.get("/cases", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.get("/cases", headers=RO).status_code == 200
    assert c.get("/healthz").status_code == 200  # probes stay open


def test_unconfigured_tokens_is_a_deployment_error_not_open_access(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(settings, "operator_tokens", "")
    assert c.get("/cases", headers=OP).status_code == 503


def test_readonly_cannot_mutate(client):
    c, Local = client
    case_id, pid = _open_case(c, Local)
    case = c.get(f"/cases/{case_id}", headers=RO).json()
    r = c.post(f"/cases/{case_id}/proposals/{pid}/approve", json={"approved": proposal_dict(), "expected_version": case["version"]}, headers=RO)
    assert r.status_code == 403
    assert c.post("/intake", json={"body": "x", "received_on": "2026-09-01"}, headers=RO).status_code == 403


def test_exception_determination_needs_supervisor(client):
    c, Local = client
    case_id, pid = _open_case(c, Local)
    case = c.get(f"/cases/{case_id}", headers=OP).json()
    body = {"approved": proposal_dict(exception_candidates=["OVERBROAD"]), "expected_version": case["version"], "exception_code": "OVERBROAD"}
    assert c.post(f"/cases/{case_id}/proposals/{pid}/approve", json=body, headers=OP).status_code == 403
    r = c.post(f"/cases/{case_id}/proposals/{pid}/approve", json=body, headers=SUP)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "EXCEPTION_REVIEW"


def test_audit_actor_is_the_credential_not_the_body(client):
    c, Local = client
    case_id, pid = _open_case(c, Local)
    case = c.get(f"/cases/{case_id}", headers=OP).json()
    # a body that tries to claim another identity is simply ignored
    r = c.post(
        f"/cases/{case_id}/proposals/{pid}/approve",
        json={"approved": proposal_dict(), "expected_version": case["version"], "operator": "someone-else"},
        headers=SUP,
    )
    assert r.status_code == 200, r.text
    actors = {row["action"]: row["actor"] for row in c.get(f"/cases/{case_id}/audit", headers=RO).json()}
    assert actors["triage.approved"] == "sup-1"
    assert "someone-else" not in actors.values()
