"""Three calendars, because three rules use three different definitions of a day.

- reg_x_bd:  Reg X subpart C "days (excluding legal public holidays, Saturdays, and Sundays)" — §1024.35/.36.
             Assumption (see README): "legal public holidays" = federal holidays, 5 U.S.C. 6103(a).
- reg_z_bd:  Reg Z *general* business day, §1026.2(a)(6): a day the creditor's offices are open. §1026.36 is
             not in the special-definition list, so payoff statements (§1026.36(c)(3)) use this one.
- calendar:  §1024.31 "Day means calendar day" — used for the 60-day credit-reporting hold, §1024.35(i)(1).
"""

from __future__ import annotations

from datetime import date, timedelta

import holidays

from .config import settings

_US_FED = holidays.country_holidays("US", categories=["public"], observed=True)


def is_reg_x_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _US_FED


def is_reg_z_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in settings.creditor_closed_days


_PREDICATES = {"reg_x_bd": is_reg_x_business_day, "reg_z_bd": is_reg_z_business_day}


def add_days(start: date, n: int, calendar: str) -> date:
    """Due date = the n-th qualifying day strictly after `start`; the day of receipt itself does not count."""
    if calendar == "calendar":
        return start + timedelta(days=n)
    pred = _PREDICATES[calendar]
    d, left = start, n
    while left > 0:
        d += timedelta(days=1)
        if pred(d):
            left -= 1
    return d
