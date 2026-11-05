"""Glue used by the CLI, API and UI: load or build the rule table, run checks."""

from __future__ import annotations

import os
from typing import Literal

from ..ingest.pipeline import load_index
from ..llm import get_llm
from ..retrieval import get_retriever
from .check import DesignRow, RowResult, run_check
from .limits import LIMITS_FILE, RuleTable, _hash, build_rule_table, is_candidate, load_rule_table, save_rule_table

Method = Literal["auto", "llm", "regex"]


def _has_hosted_llm(spec: str | None) -> bool:
    names = [n.strip() for n in (spec or os.getenv("LLM_PROVIDER", "groq,ollama")).split(",")]
    return any(
        (n == "groq" and os.getenv("GROQ_API_KEY")) or (n == "openai" and os.getenv("OPENAI_API_KEY")) for n in names
    )


def resolve_method(method: Method, provider: str | None) -> str:
    """'auto' uses the LLM for extraction only when a hosted model is configured: on the sample rules a small
    local model (llama3.2 3B) extracted worse limits than the regex fallback."""
    if method != "auto":
        return method
    return "auto" if _has_hosted_llm(provider) else "regex"


def get_rule_table(method: Method = "auto", provider: str | None = None, force: bool = False) -> RuleTable:
    clauses = load_index().clauses
    table = None if force else load_rule_table()
    if table is not None:
        cands = {c.uid: _hash(c) for c in clauses if is_candidate(c)}
        if cands == table.clause_hashes:
            return table  # up to date
    m = resolve_method(method, provider)
    llm = get_llm(provider) if m in ("auto", "llm") else None
    table = build_rule_table(clauses, llm=llm, method=m, previous=None if force else table)  # type: ignore[arg-type]
    save_rule_table(table)
    return table


def save_edited_table(table: RuleTable) -> None:
    save_rule_table(table)


def get_encoder():
    r = get_retriever()
    return r._model_obj() if r.mode == "hybrid" else None


def check_rows(rows: list[DesignRow], explain: bool = False, provider: str | None = None) -> list[RowResult]:
    table = get_rule_table(provider=provider)
    return run_check(
        rows,
        table,
        load_index().clauses,
        encoder=get_encoder(),
        llm=get_llm(provider) if explain else None,
        explain=explain,
    )


__all__ = ["get_rule_table", "check_rows", "save_edited_table", "LIMITS_FILE"]
