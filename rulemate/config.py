"""Settings read from the environment / .env. No secrets are hard-coded."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _path(var: str, default: str) -> Path:
    p = Path(os.getenv(var, default))
    return p if p.is_absolute() else ROOT / p


RULES_DIR = _path("RULES_DIR", "data/rules")
INDEX_DIR = _path("INDEX_DIR", "data/index")
CLAUSES_FILE = INDEX_DIR / "clauses.json"
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".txt", ".md"}
