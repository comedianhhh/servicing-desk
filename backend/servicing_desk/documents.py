"""Inbound documents: the scan or upload a case starts from, kept as the servicing file requires.

§1024.38(c)(1): records documenting actions on a loan are retained until one year after discharge or
transfer; (c)(2): the servicing file, including notices of error, must be retrievable within five days.
So the original bytes are stored content-addressed (sha256) and never modified; the text we act on is
derived from them and recorded with which extractor produced it.

Storage is a small interface with a filesystem implementation. An object store (S3 / MinIO) is the same
two calls with a different backend.
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from pathlib import Path

from .config import settings

log = logging.getLogger("documents")


# ---- storage -----------------------------------------------------------------------------------------------


class Storage:
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class FilesystemStorage(Storage):
    """Content-addressed layout: <root>/<aa>/<sha256>. Same bytes → same key → stored once."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / key

    def put(self, key: str, data: bytes) -> None:
        p = self._path(key)
        if p.exists():
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(p)  # atomic on the same filesystem: a reader never sees a half-written file

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


_storage: Storage | None = None


def storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = FilesystemStorage(settings.docs_dir)
    return _storage


def content_key(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---- text extraction ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Extraction:
    text: str
    engine: str  # text/plain | pdf-text-layer | gemini-vision | none
    pages: int = 1


def extract_text(data: bytes, content_type: str, filename: str = "") -> Extraction:
    """Cheapest reliable path first: a text file is text; a PDF with a text layer needs no OCR; only an image
    (or a scanned PDF with no text layer) goes to a vision model — and which one is a config choice."""
    ct = (content_type or "").lower()
    name = filename.lower()

    if ct.startswith("text/") or name.endswith(".txt"):
        return Extraction(data.decode("utf-8", errors="replace"), "text/plain")

    if ct == "application/pdf" or name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = [(p.extract_text() or "").strip() for p in reader.pages]
        text = "\n\n".join(t for t in pages if t)
        if len(text) >= 40:  # a real text layer, not just a page number
            return Extraction(text, "pdf-text-layer", len(reader.pages))
        # scanned PDF: rasterise page 1..n would need poppler; hand the whole PDF to the vision model instead
        return _ocr(data, "application/pdf", len(reader.pages))

    if ct.startswith("image/"):
        return _ocr(data, ct, 1)

    raise ValueError(f"unsupported document type {content_type or filename!r}")


def _ocr(data: bytes, mime: str, pages: int) -> Extraction:
    if settings.ocr_provider == "gemini":
        from .triage.gemini_ocr import ocr

        return Extraction(ocr(data, mime), "gemini-vision", pages)
    if settings.ocr_provider == "tesseract":
        import pytesseract  # type: ignore[import-not-found]
        from PIL import Image

        return Extraction(pytesseract.image_to_string(Image.open(io.BytesIO(data))), "tesseract", pages)
    raise ValueError("document has no text layer and OCR_PROVIDER is not set")
