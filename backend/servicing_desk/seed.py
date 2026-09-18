"""Load a handful of synthetic borrower letters so the desk has something to triage.

Names, loan numbers and amounts are invented. Run the triage worker afterwards to get proposals.
"""

from __future__ import annotations

from datetime import date

from .db import engine, session_scope
from .models import Base
from .service import intake

LETTERS = [
    (
        "mail",
        """Maria Chen
Loan number 4400-118-2231

I'm disputing the $75.00 late fee on my August statement. My payment was mailed on July 28 and your own
website shows it received on August 3, which is inside the 15-day grace period. Please remove the fee and
send me a corrected statement.""",
    ),
    (
        "email",
        """To whom it may concern,

My name is Devon Okafor, account 7719-002-5540. I would like to know who currently owns my mortgage note
and who the master servicer is. I was told the loan was sold last spring but never received notice.""",
    ),
    (
        "portal",
        """Please send a payoff statement for loan 3350-771-0092 good through October 15, 2026. The property is
being refinanced with another lender. — Priya and Tom Nadeau""",
    ),
    (
        "mail",
        """I lost my job in July and cannot make the full payment this month. My loan number is 5561-330-8812.
What options do I have? I can pay about half for the next three months. Thank you. Luis Ortega""",
    ),
    (
        "fax",
        """Everything about this loan has been wrong from the start and I want it all fixed. — R. Sandoval""",
    ),
]


def main() -> None:
    Base.metadata.create_all(engine)
    with session_scope() as s:
        for channel, body in LETTERS:
            case, created = intake(s, body=body, channel=channel, received_on=date.today())
            print(("opened " if created else "duplicate ") + case.id)
