from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    # backend/.env regardless of the working directory; real env vars still win over the file
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://desk:desk@localhost:5432/desk"
    anthropic_api_key: str | None = None
    triage_model: str = "claude-opus-5"
    # claude | gemini | stub (keyword rules; no key, for CI and dry runs) | score (stub extraction + local
    # next-token scoring for the enumerated fields) | hybrid (gemini extraction + scoring)
    triage_provider: str = "claude"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.1-flash-lite"
    score_base_url: str = "http://127.0.0.1:8080"  # llama-server exposing /apply-template, /tokenize, /completion
    score_model: str = "qwen3-4b-instruct-q8"  # label for audit rows; the server decides what it actually runs
    score_rotations: int = 5  # option orders scored per decision (position-bias averaging), capped at len(options)
    score_flag_threshold: float = 0.5  # p(YES) at or above which an exception is proposed as a candidate
    # Reg Z general "business day" = days the creditor is open (§1026.2(a)(6)). Weekends plus these dates.
    creditor_closed_days: Annotated[set[date], NoDecode] = set()  # comma-separated ISO dates, not JSON
    clock_poll_seconds: float = 5.0
    kafka_bootstrap: str | None = None  # unset → in-process relay (tests, single-process demo)
    kafka_topic: str = "desk.case-events"
    letter_fail_rate: float = 0.0  # 0..1, simulated mail-vendor failures for the saga demo
    saga_max_attempts: int = 3
    docs_dir: str = "./documents"  # content-addressed archive of original scans/uploads (S3 later)
    # "<token>:<name>:<role>;..." — roles readonly | operator | supervisor (see auth.py). Empty = API refuses.
    operator_tokens: str = ""
    metrics_port: int | None = None  # workers expose /metrics here; the API serves it on its own port
    ocr_provider: str = "none"  # gemini | tesseract | none — only for images and PDFs without a text layer

    @field_validator("creditor_closed_days", mode="before")
    @classmethod
    def _split_dates(cls, v):
        if isinstance(v, str):
            return {date.fromisoformat(s.strip()) for s in v.split(",") if s.strip()}
        return v


settings = Settings()
