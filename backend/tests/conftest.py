from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from servicing_desk import handlers, service
from servicing_desk.config import settings
from servicing_desk.models import Base, Case
from servicing_desk.triage.schema import TriageProposal


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    """Tests never call a model and never see the developer's .env (fail rates, Kafka, closed days)."""
    monkeypatch.setattr(handlers, "propose", lambda body, **kw: (TriageProposal.model_validate(proposal_dict()), "fake"))
    monkeypatch.setattr(settings, "letter_fail_rate", 0.0)
    monkeypatch.setattr(settings, "saga_max_attempts", 3)
    monkeypatch.setattr(settings, "kafka_bootstrap", None)
    monkeypatch.setattr(settings, "creditor_closed_days", set())


NOE_LETTER = """Jane Q. Borrower
Loan #0012345678

I am writing to dispute the $75 late fee charged on my August statement. My payment was received on
August 3rd, within the grace period. Please remove the fee."""


@pytest.fixture
def case(session) -> Case:
    c, created = service.intake(session, body=NOE_LETTER, channel="mail", received_on=date(2026, 9, 1))
    assert created
    session.commit()
    return c


def proposal_dict(**overrides) -> dict:
    base = {
        "case_type": "NOE",
        "error_category": "b5",
        "rfi_category": None,
        "three_elements": {
            "borrower_name": {"value": "Jane Q. Borrower", "source_quote": "Jane Q. Borrower"},
            "loan_identifier": {"value": "0012345678", "source_quote": "Loan #0012345678"},
            "assertion_or_request": {"value": "dispute the $75 late fee", "source_quote": "dispute the $75 late fee charged"},
        },
        "exception_candidates": [],
        "mentions_foreclosure_sale_date": {"value": None, "source_quote": None},
        "confidence": 0.9,
        "rationale": "Asserts a fee was wrongly imposed.",
    }
    base.update(overrides)
    return base
