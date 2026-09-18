from datetime import date

from servicing_desk.calendars import add_days
from servicing_desk.config import settings


def test_reg_x_skips_weekends_and_federal_holidays():
    # Fri 2026-09-04 → 5 bd: skips Sat/Sun and Labor Day (Mon 2026-09-07) → Mon 2026-09-14
    assert add_days(date(2026, 9, 4), 5, "reg_x_bd") == date(2026, 9, 14)


def test_calendar_days_do_not_skip_anything():
    assert add_days(date(2026, 9, 1), 60, "calendar") == date(2026, 10, 31)


def test_reg_z_uses_creditor_calendar_not_federal_holidays(monkeypatch):
    # Labor Day is a federal holiday but if the creditor is open it counts for Reg Z; a company closure does not.
    monkeypatch.setattr(settings, "creditor_closed_days", {date(2026, 9, 8)})
    assert add_days(date(2026, 9, 4), 2, "reg_z_bd") == date(2026, 9, 9)  # Mon 7th counts, Tue 8th closed, Wed 9th
    assert add_days(date(2026, 9, 4), 2, "reg_x_bd") == date(2026, 9, 9)  # Mon 7th holiday, Tue 8th, Wed 9th


def test_day_of_receipt_does_not_count():
    assert add_days(date(2026, 9, 1), 1, "reg_x_bd") == date(2026, 9, 2)
