"""Document intake: archive first, derive text, open a case; originals come back byte-for-byte."""

import hashlib
import io
from datetime import date

import pytest
from fpdf import FPDF

from servicing_desk import documents, service
from servicing_desk.config import settings
from servicing_desk.models import Document
from tests.conftest import NOE_LETTER


@pytest.fixture(autouse=True)
def archive(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "docs_dir", str(tmp_path / "docs"))
    monkeypatch.setattr(documents, "_storage", None)
    monkeypatch.setattr(settings, "ocr_provider", "none")


def _pdf(text: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in text.splitlines():
        pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def test_pdf_with_text_layer_opens_a_case_without_ocr(session):
    data = _pdf(NOE_LETTER.replace("$", "USD "))  # Helvetica core font: keep to Latin-1
    case, created, doc = service.intake_document(session, data=data, filename="scan.pdf", content_type="application/pdf", channel="mail", received_on=date(2026, 9, 1))
    assert created and doc.text_engine == "pdf-text-layer" and doc.pages == 1
    assert "late fee" in case.correspondence.body
    assert doc.storage_key == hashlib.sha256(data).hexdigest()
    assert documents.storage().get(doc.storage_key) == data  # archived byte-for-byte


def test_same_scan_twice_is_one_object_and_one_case(session, monkeypatch):
    data = _pdf(NOE_LETTER.replace("$", "USD "))
    calls = []
    real = documents.extract_text
    monkeypatch.setattr(service, "intake_document", service.intake_document)  # keep reference stable
    monkeypatch.setattr(documents, "extract_text", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    c1, created1, d1 = service.intake_document(session, data=data, filename="a.pdf", content_type="application/pdf", channel="mail", received_on=date(2026, 9, 1))
    c2, created2, d2 = service.intake_document(session, data=data, filename="b.pdf", content_type="application/pdf", channel="email", received_on=date(2026, 9, 2))
    assert created1 and not created2 and c1.id == c2.id
    assert d1.storage_key == d2.storage_key  # one archived object, two document rows pointing at it
    assert session.query(Document).count() == 2
    assert len(calls) == 1  # text derived once; the second arrival reuses it (no second OCR bill)


def test_text_upload(session):
    case, created, doc = service.intake_document(session, data=NOE_LETTER.encode(), filename="letter.txt", content_type="text/plain", channel="portal", received_on=date(2026, 9, 1))
    assert created and doc.text_engine == "text/plain" and case.correspondence.body == NOE_LETTER


def test_image_without_ocr_provider_is_refused_loudly(session):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
    with pytest.raises(ValueError, match="OCR_PROVIDER"):
        service.intake_document(session, data=buf.getvalue(), filename="scan.png", content_type="image/png", channel="mail", received_on=date(2026, 9, 1))


def test_unknown_type_is_refused(session):
    with pytest.raises(ValueError, match="unsupported"):
        service.intake_document(session, data=b"\x00\x01", filename="x.bin", content_type="application/octet-stream", channel="mail", received_on=date(2026, 9, 1))
