"""Vision-model OCR for scans and images. Transcription only — no interpretation, no fixing, no summarising.
The triage step gets the transcript and does its own reading."""

from __future__ import annotations

from google import genai
from google.genai import types

from ..config import settings

PROMPT = (
    "Transcribe every word of this document exactly as written, preserving line breaks and the order on the "
    "page. Do not summarise, correct, translate, or add anything. If part of the page is unreadable, write "
    "[illegible] in its place. Output the transcript only."
)


def ocr(data: bytes, mime: str, *, client: genai.Client | None = None) -> str:
    client = client or genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[types.Part.from_bytes(data=data, mime_type=mime), PROMPT],
        config=types.GenerateContentConfig(temperature=0),
    )
    return (response.text or "").strip()
