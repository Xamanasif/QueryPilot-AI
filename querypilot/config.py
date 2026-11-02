"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    db_path: str = field(default_factory=lambda: os.getenv("QUERYPILOT_DB", "data/querypilot.db"))
    groq_api_key: str | None = field(default_factory=lambda: os.getenv("GROQ_API_KEY"))
    model: str = field(default_factory=lambda: os.getenv("QUERYPILOT_MODEL", "llama-3.3-70b-versatile"))
    max_steps: int = field(default_factory=lambda: _int_env("QUERYPILOT_MAX_STEPS", 8))
    max_tool_calls: int = field(default_factory=lambda: _int_env("QUERYPILOT_MAX_TOOL_CALLS", 12))
    max_citation_repairs: int = 1
    max_tool_output_chars: int = 6000
    max_sql_rows: int = field(default_factory=lambda: _int_env("QUERYPILOT_MAX_SQL_ROWS", 200))
