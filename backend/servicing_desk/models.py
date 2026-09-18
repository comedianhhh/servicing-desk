from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class CaseType(str, enum.Enum):
    NOE = "NOE"  # notice of error, §1024.35
    RFI = "RFI"  # request for information, §1024.36
    PAYOFF_REQUEST = "PAYOFF_REQUEST"  # Reg Z §1026.36(c)(3); need not be treated as an RFI (§1024.36(a))
    LOSS_MIT = "LOSS_MIT"  # §1024.41 — routed out of this desk
    NOT_COVERED = "NOT_COVERED"  # payment coupon, general inquiry, marketing…


class ErrorCategory(str, enum.Enum):
    """§1024.35(b)(1)–(11). The category sets the response clock (§1024.35(e)(3))."""

    B1_ACCEPT_PAYMENT = "b1"
    B2_APPLY_PAYMENT = "b2"
    B3_CREDIT_PAYMENT = "b3"
    B4_ESCROW = "b4"
    B5_FEES = "b5"
    B6_PAYOFF_BALANCE = "b6"  # 7 bd
    B7_TRANSFER = "b7"
    B8_LOSS_MIT_OPTIONS = "b8"
    B9_FORECLOSURE_MOTION = "b9"  # min(sale date, 30 bd)
    B10_FORECLOSURE_SALE = "b10"  # min(sale date, 30 bd)
    B11_OTHER = "b11"


class RfiCategory(str, enum.Enum):
    OWNER_IDENTITY = "OWNER_IDENTITY"  # 10 bd, §1024.36(d)(2)(i)(A)
    OTHER = "OTHER"  # 30 bd, §1024.36(d)(2)(i)(B)


class ExceptionCode(str, enum.Enum):
    DUPLICATIVE = "DUPLICATIVE"  # §1024.35(g)(1)(i) / §1024.36(f)(1)(i)
    OVERBROAD = "OVERBROAD"  # §1024.35(g)(1)(ii) / §1024.36(f)(1)(iv)
    UNTIMELY = "UNTIMELY"  # §1024.35(g)(1)(iii) / §1024.36(f)(1)(v)
    CONFIDENTIAL = "CONFIDENTIAL"  # RFI only, §1024.36(f)(1)(ii)
    IRRELEVANT = "IRRELEVANT"  # RFI only, §1024.36(f)(1)(iii)
    BURDENSOME = "BURDENSOME"  # RFI only, §1024.36(f)(1)(iv)


class CaseStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    TRIAGE = "TRIAGE"
    NOT_COVERED = "NOT_COVERED"
    ROUTED_LOSS_MIT = "ROUTED_LOSS_MIT"
    PAYOFF_REQUEST = "PAYOFF_REQUEST"
    PAYOFF_REASONABLE_TIME = "PAYOFF_REASONABLE_TIME"
    EXCEPTION_REVIEW = "EXCEPTION_REVIEW"
    ACK_PENDING = "ACK_PENDING"
    EARLY_RESOLVED = "EARLY_RESOLVED"
    INVESTIGATING = "INVESTIGATING"
    EXTENDED = "EXTENDED"
    RESPONDED = "RESPONDED"
    DOCS_REQUESTED = "DOCS_REQUESTED"
    CLOSED = "CLOSED"


class ClockKind(str, enum.Enum):
    ACK = "ACK"
    RESPONSE = "RESPONSE"
    EXTENSION = "EXTENSION"
    EXCEPTION_NOTICE = "EXCEPTION_NOTICE"
    DOCS = "DOCS"
    PAYOFF = "PAYOFF"
    CREDIT_REPORTING_HOLD = "CREDIT_REPORTING_HOLD"


class ClockStatus(str, enum.Enum):
    PENDING = "PENDING"
    FIRED = "FIRED"
    CANCELLED = "CANCELLED"
    SATISFIED = "SATISFIED"


class Correspondence(Base):
    """One inbound item. Idempotency key = sha256(normalized body), so the same letter arriving by mail scan
    and by email does not open two cases (and two sets of clocks)."""

    __tablename__ = "correspondence"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    channel: Mapped[str] = mapped_column(String(16))  # mail | email | portal | fax
    received_on: Mapped[date] = mapped_column(Date)  # clock base date
    sent_to_designated_address: Mapped[bool] = mapped_column(Boolean, default=True)  # §1024.35(c)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    case: Mapped[Case | None] = relationship(back_populates="correspondence", uselist=False)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    correspondence_id: Mapped[str] = mapped_column(ForeignKey("correspondence.id"), unique=True)
    status: Mapped[CaseStatus] = mapped_column(Enum(CaseStatus), default=CaseStatus.RECEIVED, index=True)
    version: Mapped[int] = mapped_column(default=0)  # optimistic lock for concurrent operators

    loan_id: Mapped[str | None] = mapped_column(String(64), index=True)
    borrower_name: Mapped[str | None] = mapped_column(String(200))
    case_type: Mapped[CaseType | None] = mapped_column(Enum(CaseType))
    error_category: Mapped[ErrorCategory | None] = mapped_column(Enum(ErrorCategory))
    rfi_category: Mapped[RfiCategory | None] = mapped_column(Enum(RfiCategory))
    exception_code: Mapped[ExceptionCode | None] = mapped_column(Enum(ExceptionCode))
    three_elements_ok: Mapped[bool | None] = mapped_column(Boolean)  # name + loan identifiable + assertion

    foreclosure_sale_date: Mapped[date | None] = mapped_column(Date)  # drives (e)(3)(i)(B) and (f)(2)
    servicing_transfer_date: Mapped[date | None] = mapped_column(Date)  # untimely, (g)(1)(iii)
    discharge_date: Mapped[date | None] = mapped_column(Date)
    assignee: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    correspondence: Mapped[Correspondence] = relationship(back_populates="case")
    clocks: Mapped[list[Clock]] = relationship(back_populates="case", cascade="all, delete-orphan")
    proposals: Mapped[list[Proposal]] = relationship(back_populates="case", cascade="all, delete-orphan")
    letters: Mapped[list[Letter]] = relationship(back_populates="case", cascade="all, delete-orphan")


class Proposal(Base):
    """What the LLM suggested. Never applied directly: an operator approves (possibly with edits), and the
    approval is what transitions the case. Both JSON blobs are kept so the diff is auditable."""

    __tablename__ = "proposals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    model: Mapped[str] = mapped_column(String(64))
    proposed: Mapped[dict] = mapped_column(JSON)
    approved: Mapped[dict | None] = mapped_column(JSON)
    decided_by: Mapped[str | None] = mapped_column(String(64))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    case: Mapped[Case] = relationship(back_populates="proposals")


class Clock(Base):
    """A regulatory deadline persisted as a row, so it survives restarts and can be swept by a worker."""

    __tablename__ = "clocks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[ClockKind] = mapped_column(Enum(ClockKind))
    calendar: Mapped[str] = mapped_column(String(16))  # reg_x_bd | reg_z_bd | calendar
    citation: Mapped[str] = mapped_column(String(64))
    due_on: Mapped[date] = mapped_column(Date)
    status: Mapped[ClockStatus] = mapped_column(Enum(ClockStatus), default=ClockStatus.PENDING)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    case: Mapped[Case] = relationship(back_populates="clocks")
    __table_args__ = (Index("ix_clock_sweep", "status", "due_on"),)


class Letter(Base):
    __tablename__ = "letters"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    template: Mapped[str] = mapped_column(String(32))  # L1..L6, RFI_RESPONSE, PAYOFF
    fields: Mapped[dict] = mapped_column(JSON)
    body: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # set by the letter worker on delivery
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # saga compensation
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    case: Mapped[Case] = relationship(back_populates="letters")


class SagaState(str, enum.Enum):
    RUNNING = "RUNNING"
    DONE = "DONE"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"


class Saga(Base):
    """Orchestration state for a multi-step, multi-system action. The row is the source of truth for where
    the saga is; every step is driven by an event and advances the row in the same transaction."""

    __tablename__ = "sagas"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(32))  # respond
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    state: Mapped[SagaState] = mapped_column(Enum(SagaState), default=SagaState.RUNNING)
    step: Mapped[str] = mapped_column(String(32))  # deliver_letter | release_hold | finish
    started_by: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class LedgerAdjustment(Base):
    """Stand-in for the servicing system of record. Amounts are decimal strings — money is never a float."""

    __tablename__ = "ledger_adjustments"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    saga_id: Mapped[str] = mapped_column(String(32), unique=True)  # idempotency: one adjustment per saga
    case_id: Mapped[str] = mapped_column(String(32), index=True)
    loan_id: Mapped[str | None] = mapped_column(String(64))
    amount: Mapped[str] = mapped_column(String(32))
    memo: Mapped[str] = mapped_column(Text)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CreditHold(Base):
    """Stand-in for the credit-reporting system: a hold on negative reporting for a loan, §1024.35(i)(1)."""

    __tablename__ = "credit_holds"
    case_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    loan_id: Mapped[str | None] = mapped_column(String(64), index=True)
    until: Mapped[date] = mapped_column(Date)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Append-only. §1024.38(c): if it is not in the servicing file, it did not happen."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # monotonic: order is evidence
    case_id: Mapped[str] = mapped_column(String(32), index=True)
    actor: Mapped[str] = mapped_column(String(64))  # operator id | system:<worker> | llm:<model>
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OutboxEvent(Base):
    """Transactional outbox. Written in the same transaction as the state change; a relay publishes it
    (in-process now, Kafka later). Consumers dedupe on event id via ProcessedEvent."""

    __tablename__ = "outbox"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    aggregate_type: Mapped[str] = mapped_column(String(32))
    aggregate_id: Mapped[str] = mapped_column(String(32))  # partition key once this goes to Kafka
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_outbox_unpublished", "published_at", "created_at"),)


class ProcessedEvent(Base):
    """At-least-once delivery + this table = effectively-once processing per consumer."""

    __tablename__ = "processed_events"
    consumer: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
