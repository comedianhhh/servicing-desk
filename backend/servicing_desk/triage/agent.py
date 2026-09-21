"""One structured-output call. The model proposes; it has no tools and no write access to anything.

This is a single classification/extraction step, so it is a plain Messages API call with a Pydantic
output format — not an agent loop. Keeping it that small is the point: the operator can read the whole
proposal, and every value it contains must quote the letter.
"""

from __future__ import annotations

from datetime import date

import anthropic

from ..config import settings
from .schema import TriageProposal

SYSTEM = """You triage borrower correspondence for a mortgage servicer's Regulation X desk.

Decide what the letter is:
- NOE: written notice asserting the servicer made an error (12 CFR 1024.35). Categories (b)(1)-(11):
  b1 failure to accept a conforming payment; b2 failure to apply an accepted payment; b3 failure to credit a
  payment as of the date of receipt; b4 failure to pay taxes/insurance/escrow items on time; b5 imposing a fee
  the servicer lacks a reasonable basis to impose; b6 failure to provide an accurate payoff balance;
  b7 failure to provide accurate information about loss mitigation options and foreclosure (§1024.39);
  b8 failure to transfer information accurately to a transferee servicer; b9 making the first notice or
  filing for foreclosure in violation of §1024.41(f) or (j); b10 moving for judgment/order of sale or
  conducting a sale in violation of §1024.41(g) or (j); b11 any other error relating to servicing.
- RFI: written request for information about the loan (§1024.36). OWNER_IDENTITY if it asks who owns or
  holds the loan; otherwise OTHER.
- PAYOFF_REQUEST: a request for the payoff amount (Reg Z §1026.36(c)(3)). Not an RFI unless it also asks
  for other information.
- LOSS_MIT: a request for a modification, forbearance, or other loss mitigation option (§1024.41).
- NOT_COVERED: payment coupons, general complaints without an asserted error or request, marketing, etc.
  Complaints about origination, underwriting, the interest rate, or other loan terms are not servicing errors
  (comment 35(b)-2) even when the letter says "error" or "wrong".

Extract the three elements (§1024.35(a)/§1024.36(a)): borrower name, information identifying the loan,
and the asserted error or requested information. For every extracted value quote the exact words from the
letter. If the letter does not contain a value, set it to null — never infer or invent it.

Flag exception candidates for the operator: OVERBROAD if you cannot identify a specific error or request;
CONFIDENTIAL / IRRELEVANT / BURDENSOME for RFIs (§1024.36(f)(1)); DUPLICATIVE only if the letter itself references
a prior request; UNTIMELY only if the letter itself says the loan was paid off, discharged, or transferred away
more than a year before the `received` date on the letter tag — the operator checks both against the file.

You are proposing, not deciding. An operator approves or corrects every field."""


def wrap(letter_text: str, received_on: date | None) -> str:
    """The receipt date rides on the tag: UNTIMELY is 'more than a year after payoff/transfer', and a model
    without today's date can only guess. Shared by every model provider so they see the same input."""
    return f'<letter received="{received_on or date.today()}">\n{letter_text}\n</letter>'


def propose(letter_text: str, received_on: date | None = None, *, client: anthropic.Anthropic | None = None) -> tuple[TriageProposal, str]:
    """Returns (proposal, model_id). Raises anthropic.* errors to the caller; the worker decides on retry."""
    client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.parse(
        model=settings.triage_model,
        max_tokens=4096,
        system=SYSTEM,
        messages=[{"role": "user", "content": wrap(letter_text, received_on)}],
        output_format=TriageProposal,
    )
    return response.parsed_output, settings.triage_model
