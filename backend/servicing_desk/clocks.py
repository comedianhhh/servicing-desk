"""Which clocks a case carries, and where each one comes from.

Every rule here is one row in the regulation. Calendar choice matters as much as the number:
§1024.35/.36 count business days excluding federal holidays, §1026.36(c)(3) counts creditor business days,
§1024.35(i)(1) counts calendar days.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .calendars import add_days
from .models import Case, CaseType, Clock, ClockKind, ClockStatus, ErrorCategory, RfiCategory


@dataclass(frozen=True)
class ClockRule:
    kind: ClockKind
    days: int
    calendar: str
    citation: str
    extendable: bool = False  # only (e)(3)(i)(C) / (d)(2)(i)(B) may be extended by 15 bd


ACK = ClockRule(ClockKind.ACK, 5, "reg_x_bd", "§1024.35(d) / §1024.36(c)")
CREDIT_HOLD = ClockRule(ClockKind.CREDIT_REPORTING_HOLD, 60, "calendar", "§1024.35(i)(1)")
EXCEPTION_NOTICE = ClockRule(ClockKind.EXCEPTION_NOTICE, 5, "reg_x_bd", "§1024.35(g)(2) / §1024.36(f)(2)")
DOCS = ClockRule(ClockKind.DOCS, 15, "reg_x_bd", "§1024.35(e)(4)")
PAYOFF = ClockRule(ClockKind.PAYOFF, 7, "reg_z_bd", "§1026.36(c)(3)")
EXTENSION_DAYS = 15  # §1024.35(e)(3)(ii) / §1024.36(d)(2)(ii)

_NOE_RESPONSE = {
    ErrorCategory.B6_PAYOFF_BALANCE: ClockRule(ClockKind.RESPONSE, 7, "reg_x_bd", "§1024.35(e)(3)(i)(A)"),
    ErrorCategory.B9_FORECLOSURE_MOTION: ClockRule(ClockKind.RESPONSE, 30, "reg_x_bd", "§1024.35(e)(3)(i)(B)"),
    ErrorCategory.B10_FORECLOSURE_SALE: ClockRule(ClockKind.RESPONSE, 30, "reg_x_bd", "§1024.35(e)(3)(i)(B)"),
}
_NOE_DEFAULT = ClockRule(ClockKind.RESPONSE, 30, "reg_x_bd", "§1024.35(e)(3)(i)(C)", extendable=True)
_RFI_RESPONSE = {
    RfiCategory.OWNER_IDENTITY: ClockRule(ClockKind.RESPONSE, 10, "reg_x_bd", "§1024.36(d)(2)(i)(A)"),
    RfiCategory.OTHER: ClockRule(ClockKind.RESPONSE, 30, "reg_x_bd", "§1024.36(d)(2)(i)(B)", extendable=True),
}


def response_rule(case: Case) -> ClockRule:
    if case.case_type == CaseType.NOE:
        return _NOE_RESPONSE.get(case.error_category, _NOE_DEFAULT)
    if case.case_type == CaseType.RFI:
        return _RFI_RESPONSE[case.rfi_category or RfiCategory.OTHER]
    raise ValueError(f"no response clock for {case.case_type}")


def due_date(rule: ClockRule, received_on: date, case: Case | None = None) -> date:
    due = add_days(received_on, rule.days, rule.calendar)
    # (e)(3)(i)(B): "prior to the date of a foreclosure sale or within 30 days, whichever is earlier"
    if case is not None and case.error_category in (
        ErrorCategory.B9_FORECLOSURE_MOTION,
        ErrorCategory.B10_FORECLOSURE_SALE,
    ) and case.foreclosure_sale_date is not None:
        due = min(due, case.foreclosure_sale_date)
    return due


def make_clock(case: Case, rule: ClockRule, base: date | None = None) -> Clock:
    start = base or case.correspondence.received_on
    return Clock(
        case_id=case.id,
        kind=rule.kind,
        calendar=rule.calendar,
        citation=rule.citation,
        due_on=due_date(rule, start, case),
        status=ClockStatus.PENDING,
    )


def clocks_on_acknowledged(case: Case) -> list[Clock]:
    """Set when an operator confirms a valid NOE/RFI. ACK + RESPONSE always; CREDIT_HOLD for NOE only."""
    out = [make_clock(case, ACK), make_clock(case, response_rule(case))]
    if case.case_type == CaseType.NOE:
        out.append(make_clock(case, CREDIT_HOLD))
    return out


def extend_response(case: Case, today: date) -> Clock:
    """Only the 30-day class may be extended, and only before the original due date (notice must go out first)."""
    rule = response_rule(case)
    if not rule.extendable:
        raise ValueError(f"{rule.citation} response is not extendable")
    current = next(c for c in case.clocks if c.kind == ClockKind.RESPONSE and c.status == ClockStatus.PENDING)
    if today > current.due_on:
        raise ValueError("extension notice must be sent before the original due date")
    current.status = ClockStatus.SATISFIED
    return Clock(
        case_id=case.id,
        kind=ClockKind.EXTENSION,
        calendar=rule.calendar,
        citation="§1024.35(e)(3)(ii) / §1024.36(d)(2)(ii)",
        due_on=add_days(current.due_on, EXTENSION_DAYS, rule.calendar),
        status=ClockStatus.PENDING,
    )


def satisfy(case: Case, kind: ClockKind) -> None:
    for c in case.clocks:
        if c.kind == kind and c.status == ClockStatus.PENDING:
            c.status = ClockStatus.SATISFIED


def cancel_all(case: Case) -> None:
    for c in case.clocks:
        if c.status == ClockStatus.PENDING and c.kind != ClockKind.CREDIT_REPORTING_HOLD:
            c.status = ClockStatus.CANCELLED
