"""Keyword triage for CI and keyless local runs. Same contract as agent.propose(): a TriageProposal whose
every value quotes the letter. Deliberately dumb — it exists so the pipeline can run without a model, not to
compete with one."""

from __future__ import annotations

import re

from .schema import Extracted, ThreeElements, TriageProposal

_RULES: list[tuple[str, str, str | None, str | None]] = [
    # (regex, case_type, error_category, rfi_category)
    (r"payoff (statement|amount|balance)|pay(ing)? off", "PAYOFF_REQUEST", None, None),
    (r"who (currently )?owns|owner of (my|the) (loan|note)|master servicer|holder of", "RFI", None, "OWNER_IDENTITY"),
    (r"lost my job|hardship|forbearance|modification|cannot make (the )?(full )?payment|what options", "LOSS_MIT", None, None),
    (r"late fee|fee(s)? (was|were|is) (wrong|charged)|remove the fee", "NOE", "b5", None),
    (r"escrow|taxes|insurance", "NOE", "b4", None),
    (r"payment (was|is) (not|never) (applied|credited)|misapplied", "NOE", "b2", None),
    (r"payoff .*(wrong|incorrect)", "NOE", "b6", None),
    (r"foreclos", "NOE", "b10", None),
    (r"disput|error|incorrect|wrong", "NOE", "b11", None),
    (r"\?|please (send|provide|tell)|would like to know|request", "RFI", None, "OTHER"),
]


def _find(pattern: str, text: str, flags=re.I) -> Extracted:
    m = re.search(pattern, text, flags)
    if not m:
        return Extracted(value=None, source_quote=None)
    return Extracted(value=m.group(1).strip(), source_quote=m.group(0).strip())


def propose(letter_text: str) -> tuple[TriageProposal, str]:
    case_type, err, rfi = "NOT_COVERED", None, None
    for pattern, ct, ec, rc in _RULES:
        if re.search(pattern, letter_text, re.I):
            case_type, err, rfi = ct, ec, rc
            break

    loan = _find(r"(?:loan|account)(?: number|#| no\.?)?[:\s#]*([0-9][0-9-]{5,})", letter_text)
    name = _find(r"(?:my name is|—|sincerely,?|thank you\.)\s*([A-Z][a-z]+(?: [A-Z]\.)?(?: [A-Z][a-z]+)+)", letter_text)
    if name.value is None:  # first line that looks like a name
        first = letter_text.strip().splitlines()[0].strip()
        if re.fullmatch(r"[A-Z][a-z]+(?: [A-Z]\.)?(?: [A-Z][a-z]+)+", first):
            name = Extracted(value=first, source_quote=first)
    assertion = _find(r"((?:dispute|disputing|would like to know|please send|what options|cannot make)[^.\n]*)", letter_text)

    exceptions = []
    if case_type in ("NOE", "RFI") and assertion.value is None:
        exceptions.append("OVERBROAD")
    if re.search(r"(as I wrote|previous(ly)? (letter|request)|again)", letter_text, re.I):
        exceptions.append("DUPLICATIVE")

    proposal = TriageProposal(
        case_type=case_type,
        error_category=err,
        rfi_category=rfi,
        three_elements=ThreeElements(borrower_name=name, loan_identifier=loan, assertion_or_request=assertion),
        exception_candidates=exceptions,
        mentions_foreclosure_sale_date=_find(r"(?:sale|auction)[^.\n]*?(\w+ \d{1,2},? \d{4})", letter_text),
        confidence=0.35,
        rationale="Keyword stub — verify every field against the letter.",
    )
    return proposal, "stub-keywords"
