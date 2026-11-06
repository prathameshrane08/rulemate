"""UI-side access to RuleMate: the FastAPI server if it is running, otherwise in-process calls.

The fallback keeps the demo alive if the API process dies.
"""

from __future__ import annotations

import os

import httpx

from rulemate.answer import Answer, answer_question
from rulemate.compliance.check import DesignRow, RowResult
from rulemate.compliance.limits import RuleTable
from rulemate.compliance.service import check_rows, get_rule_table, save_edited_table
from rulemate.api import ClauseView
from rulemate.ingest.pipeline import load_index
from rulemate.llm import get_llm
from rulemate.models import Clause
from rulemate.retrieval import get_retriever

API_URL = os.getenv("RULEMATE_API_URL", "http://localhost:8000")


class Backend:
    def __init__(self) -> None:
        self.remote = self._ping()

    def _ping(self) -> bool:
        try:
            return httpx.get(f"{API_URL}/health", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    @property
    def mode(self) -> str:
        return f"API {API_URL}" if self.remote else "in-process"

    # ---------------------------------------------------------------- calls
    def health(self) -> dict:
        if self.remote:
            try:
                return httpx.get(f"{API_URL}/health", timeout=5).json()
            except httpx.HTTPError:
                self.remote = False
        idx = load_index()
        return {
            "documents": [d.model_dump() for d in idx.documents],
            "n_clauses": len(idx.clauses),
            "retrieval_mode": get_retriever().mode,
            "llm": get_llm().label,
            "synthetic_data": any(d.synthetic for d in idx.documents),
        }

    def ask(self, question: str, provider: str | None, use_cache: bool, docs: list[str] | None = None) -> Answer:
        if self.remote:
            try:
                r = httpx.post(
                    f"{API_URL}/ask",
                    json={"question": question, "provider": provider, "use_cache": use_cache, "docs": docs},
                    timeout=200,
                )
                r.raise_for_status()
                return Answer.model_validate(r.json())
            except httpx.HTTPError:
                self.remote = False  # fall through to in-process
        return answer_question(question, retriever=get_retriever(), llm=get_llm(provider), use_cache=use_cache,
                               docs=docs)

    def clause(self, uid: str) -> ClauseView | None:
        r = get_retriever()  # clause text is tiny; read locally even in API mode
        c = r.by_uid.get(uid)
        if c is None:
            return None
        return ClauseView(
            clause=c,
            children=[x.clause_id for x in r.children.get(c.uid, [])],
            referenced_by=[x.clause_id for x in r.clauses if x.doc == c.doc and c.clause_id in x.refs],
        )

    def clauses(self) -> list[Clause]:
        return get_retriever().clauses

    # ---------------------------------------------------------------- compliance
    def check(self, rows: list[DesignRow], explain: bool, provider: str | None,
              docs: list[str] | None = None) -> list[RowResult]:
        if self.remote:
            try:
                r = httpx.post(
                    f"{API_URL}/check",
                    json={"rows": [x.model_dump() for x in rows], "explain": explain, "provider": provider, "docs": docs},
                    timeout=600,
                )
                r.raise_for_status()
                return [RowResult.model_validate(x) for x in r.json()]
            except httpx.HTTPError:
                self.remote = False
        return check_rows(rows, explain=explain, provider=provider, docs=docs)

    def rule_table(self, rebuild: bool = False, provider: str | None = None) -> RuleTable:
        return get_rule_table(provider=provider, force=rebuild)

    def save_rule_table(self, table: RuleTable) -> None:
        save_edited_table(table)
