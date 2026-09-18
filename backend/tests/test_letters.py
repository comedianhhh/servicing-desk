import pytest
from pydantic import ValidationError

from servicing_desk import letters


def test_no_error_letter_requires_every_element_of_e1iB(case):
    # §1024.35(e)(1)(i)(B): reasons + right to documents + how to request + phone. Missing phone → refuse to render.
    with pytest.raises(ValidationError):
        letters.render(case, "L3", {"reasons": "payment posted late", "how_to_request_documents": "write to us"})
    letter = letters.render(
        case, "L3", {"reasons": "payment posted late", "how_to_request_documents": "write to us", "contact_phone": "800-555-0100"}
    )
    assert "no error occurred" in letter.body and "800-555-0100" in letter.body


def test_unknown_fields_are_rejected(case):
    with pytest.raises(ValidationError):
        letters.render(case, "L1", {"received_on": "2026-09-01", "reference": "x", "tone": "friendly"})


def test_rfi_response_needs_information_or_basis(case):
    with pytest.raises(ValueError):
        letters.render(case, "RFI_RESPONSE", {"contact_phone": "800-555-0100"})
    letter = letters.render(case, "RFI_RESPONSE", {"not_available_basis": "not in servicing file", "contact_phone": "800-555-0100"})
    assert "not available to the servicer" in letter.body
