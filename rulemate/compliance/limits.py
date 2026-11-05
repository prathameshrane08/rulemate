"""Structured rule table: numeric limits extracted from clauses.

The LLM proposes limits as JSON; code validates every one before it is stored:
* the value appears in the clause text (with the same unit, or the unit appears in a table header)
* the unit is understood by pint
* the comparator is one of >=, <=, >, <
* a quote, if given, is word for word in the clause (otherwise it is dropped)
A regex extractor is the offline fallback (and fills in clauses where the LLM gave nothing valid).

Result: data/index/limits.json
"""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel, Field

from ..config import INDEX_DIR
from ..guardrails import UNIT_ALIASES, _norm_text, extract_numbers
from ..models import Clause
from .units import UnitError, parse_unit

LIMITS_FILE = INDEX_DIR / "limits.json"
Comparator = Literal[">=", "<=", ">", "<"]


class Limit(BaseModel):
    id: str
    clause_uid: str
    doc: str
    clause_id: str
    parameter: str  # generic name of the quantity, e.g. "corridor clear width"
    subject: str = ""  # what it applies to, as stated
    qualifier: str | None = None  # limit only applies to this kind of space/item, e.g. "crew accommodation"
    condition: str | None = None  # extra condition code cannot verify, e.g. "serves not more than 50 persons"
    comparator: Comparator
    value: float
    unit: str
    quote: str | None = None
    method: Literal["llm", "regex", "manual"] = "llm"
    synthetic: bool = False
    context: str = ""  # the clause sentence that states the value (taken by code, used for matching)
    refs: list[str] = Field(default_factory=list)  # clause_ids the source clause refers to
    notes: list[str] = Field(default_factory=list)  # corrections made by validation

    @property
    def citation(self) -> str:
        return f"[{self.doc} § {self.clause_id}]"

    def describe(self) -> str:
        return f"{self.comparator} {self.value:g} {self.unit}"


class RuleTable(BaseModel):
    limits: list[Limit] = Field(default_factory=list)
    rejected: list[dict] = Field(default_factory=list)  # proposals that failed validation, with reasons
    clause_hashes: dict[str, str] = Field(default_factory=dict)  # clause uid -> text hash (for incremental rebuilds)
    model: str = ""


# ------------------------------------------------------------------ candidates

_LIMIT_WORDS = re.compile(
    r"\b(not less than|not more than|not exceed(?:ing)?|shall not exceed|at least|minimum|maximum|"
    r"no(?:t)? greater than|no(?:t)? smaller than|up to|min\.|max\.|increased to|reduced to)\b",
    re.I,
)


def is_candidate(c: Clause) -> bool:
    if c.kind == "heading":
        return False
    has_unit_number = any(u for _, u in extract_numbers(c.text))
    return (c.kind == "table" and bool(extract_numbers(c.text))) or (has_unit_number and bool(_LIMIT_WORDS.search(c.text)))


def _hash(c: Clause) -> str:
    return hashlib.sha1(c.text.encode()).hexdigest()[:12]


# ------------------------------------------------------------------ validation

_CMP_WORDS = {
    ">=": ">=", "≥": ">=", "min": ">=", "minimum": ">=", "at least": ">=", "not less than": ">=",
    "<=": "<=", "≤": "<=", "max": "<=", "maximum": "<=", "not more than": "<=", "not exceeding": "<=",
    ">": ">", "<": "<",
}


_MIN_PHRASE = re.compile(r"(not less than|at least|no less than|minimum(?: of)?|min\.)\s*$", re.I)
_MAX_PHRASE = re.compile(r"(not more than|not exceeding|shall not exceed|not exceed|no more than|up to|maximum(?: of)?|max\.|increased to)\s*$", re.I)
_BAD_QUALIFIERS = {"any", "all", "none", "table", "min", "max", "degrees", "division class", "both sides", "n/a"}


def _value_spans(text: str, value: float) -> list[re.Match]:
    return [m for m in re.finditer(r"(?<![\w.])\d+(?:\.\d+)?", text) if float(m.group(0)) == value]


_UNIT_NUM = re.compile(r"\d+(?:\.\d+)?\s?(?:mm|cm|m2|m²|m|degrees|°|min|s|kN|N|%)(?![A-Za-z])")


def comparator_from_text(text: str, value: float) -> str | None:
    """Direction stated right before the value, if unambiguous."""
    found = set()
    for m in _value_spans(text, value):
        before = text[max(0, m.start() - 30) : m.start()]
        if _MIN_PHRASE.search(before):
            found.add(">=")
        elif _MAX_PHRASE.search(before):
            found.add("<=")
    return found.pop() if len(found) == 1 else None


def context_sentence(text: str, value: float) -> str:
    for line in text.splitlines():
        if line.startswith("|") and _value_spans(line, value):
            return line.strip()  # table row
    for sent in re.split(r"(?<=[.;])\s+", text):
        spans = _value_spans(sent, value)
        if spans:
            # several limits in one sentence ("riser ... 200 mm and the tread ... 240 mm"): keep this limit's part
            prev_ends = [m.end() for m in _UNIT_NUM.finditer(sent) if m.end() <= spans[0].start()]
            start = prev_ends[-1] if prev_ends else 0
            end = sent.find(" and ", spans[0].end())
            return sent[start : end if end > 0 else len(sent)].strip(" ,.;")
    return text[:200]


def validate(raw: dict, clause: Clause, n: int, method: str) -> tuple[Limit | None, str]:
    try:
        cmp = _CMP_WORDS.get(str(raw.get("comparator", "")).strip().lower())
        if cmp is None:
            return None, f"bad comparator {raw.get('comparator')!r}"
        value = float(str(raw.get("value")).replace(",", ""))
        unit = str(raw.get("unit") or "").strip()
        parameter = str(raw.get("parameter") or "").strip()
    except (TypeError, ValueError):
        return None, "value is not a number"
    if not parameter:
        return None, "missing parameter"
    if not unit:
        return None, "missing unit"
    try:
        parse_unit(unit)
    except UnitError as e:
        return None, str(e)

    src = extract_numbers(clause.text)
    if value not in {v for v, _ in src}:
        return None, f"value {value:g} does not appear in the clause"
    canon = next((cu for cu, al in UNIT_ALIASES.items() if unit in al or unit.lower() in al), None)
    paired = {(v, u) for v, u in src if u}
    if (value, canon) not in paired:
        # tables give units in the header: accept if the unit word appears anywhere in the clause
        aliases = UNIT_ALIASES.get(canon, [unit]) if canon else [unit]
        if not any(re.search(rf"(?<![A-Za-z]){re.escape(a)}(?![A-Za-z])", clause.text) for a in aliases):
            return None, f"unit {unit} for value {value:g} not found in the clause"

    notes: list[str] = []
    text_cmp = comparator_from_text(clause.text, value)
    if text_cmp and text_cmp != cmp and cmp in (">=", "<="):
        notes.append(f"comparator corrected from {cmp} to {text_cmp} (text)")
        cmp = text_cmp

    if "/" not in unit and any(
        re.match(r"\s?[A-Za-z%°²]*\s+per\s+\w", clause.text[m.end():]) for m in _value_spans(clause.text, value)
    ):
        return None, f"{value:g} is a per-unit rate in the text; unit '{unit}' is not a rate"

    quote = raw.get("quote") or None
    if quote and _norm_text(quote) not in _norm_text(clause.text):
        quote = None  # keep the limit, drop the unverifiable quote

    def opt(k: str) -> str | None:
        v = raw.get(k)
        v = str(v).strip() if v not in (None, "", "null", "none", "None") else None
        return v or None

    qualifier = opt("qualifier")
    if qualifier and (qualifier.lower() in _BAD_QUALIFIERS or _norm_text(qualifier).rstrip("s") not in _norm_text(clause.text)):
        notes.append(f"qualifier '{qualifier}' dropped (not a space/item named in the clause)")
        qualifier = None

    return (
        Limit(
            id=f"{clause.uid}#{n}",
            clause_uid=clause.uid,
            doc=clause.doc,
            clause_id=clause.clause_id,
            parameter=parameter,
            subject=opt("subject") or "",
            qualifier=qualifier,
            condition=opt("condition"),
            comparator=cmp,  # type: ignore[arg-type]
            value=value,
            unit=unit,
            quote=quote,
            method=method,  # type: ignore[arg-type]
            synthetic=clause.synthetic,
            context=context_sentence(clause.text, value),
            refs=list(clause.refs),
            notes=notes,
        ),
        "",
    )


# ------------------------------------------------------------------ regex extractor (offline fallback)

_RX = re.compile(
    r"(?P<cmp>not less than|at least|not more than|not exceeding|shall not exceed|not exceed|"
    r"no more than|no less than|(?:be )?increased to|(?:be )?reduced to(?! not))\s+(?P<val>\d+(?:\.\d+)?)\s?(?P<unit>mm|cm|m2|m²|m|degrees|°|min|s|kN|N|%)(?![A-Za-z])",
    re.I,
)
_COND = re.compile(r"\b(provided that|where|if|unless|subject to)\b(.*)$", re.I)


def extract_regex(c: Clause) -> list[dict]:
    out = []
    for sent in re.split(r"(?<=[.;])\s+", c.text):
        cond = _COND.search(sent)
        last_end, subject = 0, ""
        for m in _RX.finditer(sent):
            words = m.group("cmp").lower()
            cmp = ">=" if words in ("not less than", "at least", "no less than") or "reduced" in words else "<="
            seg = re.sub(r"^\s*(and|or|,)\s+", "", sent[last_end : m.start()], flags=re.I)
            seg = re.sub(r"\b(shall|must|may)\b.*$", "", seg, flags=re.I).strip(" ,")
            subject = seg if len(re.findall(r"[A-Za-z]{3,}", seg)) >= 2 else (subject or c.title)
            last_end = m.end()
            q = re.match(r"^In ([^,]+),", sent)
            out.append(
                {
                    "parameter": f"{c.title} {subject}".strip()[:120],
                    "subject": subject,
                    "qualifier": q.group(1) if q else None,
                    "condition": cond.group(0).strip(" .") if cond else None,
                    "comparator": cmp,
                    "value": m.group("val"),
                    "unit": m.group("unit"),
                    "quote": m.group(0),
                }
            )
    return out


# ------------------------------------------------------------------ LLM extractor

EXTRACT_PROMPT = """Extract every explicit numeric limit from the rule clause below.
Return only JSON: {"limits": [ ... ]}. Each limit has these fields:
- "parameter": short generic name of the measured quantity, e.g. "corridor clear width", "stair inclination angle", \
"fire door fire integrity rating", "fire door closing time", "handrail height", "travel distance to stairway enclosure"
- "subject": what the limit applies to, as stated in the text
- "qualifier": if the limit applies only to one kind of space or item (e.g. "crew accommodation", "cabin doors", \
"stairway enclosures", "main vertical zone bulkheads"), that kind; otherwise null
- "condition": any other condition that must hold for the limit to apply, copied from the text \
(e.g. "the corridor serves not more than 50 persons", "subject to the approval of the Administration"); otherwise null
- "comparator": ">=" for a minimum (not less than, at least), "<=" for a maximum (not more than, not exceeding), ">" or "<" if strict
- "value": the number exactly as written
- "unit": the unit as written (mm, m, degrees, min, s, N, m2, ...)
- "quote": the exact words from the text that state the limit, e.g. "not less than 1200 mm"
Rules: include only limits stated with a number. A number that only says when a rule applies (e.g. "more than 36 \
passengers") is not a limit by itself; put it in "condition" of the limit it restricts. For a table, give one limit \
per row and use the row label as the qualifier. If there are no limits, return {"limits": []}.

Clause {citation} {title}:
{text}"""


def _parse_json(text: str) -> list[dict]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    limits = data.get("limits", []) if isinstance(data, dict) else []
    return [x for x in limits if isinstance(x, dict)]


def extract_llm(c: Clause, llm) -> list[dict]:
    prompt = EXTRACT_PROMPT.replace("{citation}", c.citation).replace("{title}", c.title).replace("{text}", c.text)
    raw = llm.complete([{"role": "user", "content": prompt}], max_tokens=1500)
    return _parse_json(raw)


# ------------------------------------------------------------------ build


def build_rule_table(
    clauses: list[Clause],
    llm=None,
    method: Literal["auto", "llm", "regex"] = "auto",
    previous: RuleTable | None = None,
    workers: int = 4,
) -> RuleTable:
    """Extract limits from every candidate clause. Unchanged clauses are reused from ``previous``."""
    cands = [c for c in clauses if is_candidate(c)]
    prev_ok = {}
    if previous is not None:
        for c in cands:
            if previous.clause_hashes.get(c.uid) == _hash(c):
                prev_ok[c.uid] = [l for l in previous.limits if l.clause_uid == c.uid]

    def work(c: Clause) -> tuple[list[Limit], list[dict]]:
        if c.uid in prev_ok:
            return prev_ok[c.uid], []
        limits, rejected = [], []
        proposals: list[tuple[dict, str]] = []
        if method in ("auto", "llm") and llm is not None:
            try:
                proposals = [(p, "llm") for p in extract_llm(c, llm)]
            except Exception as e:  # LLM down: fall back below
                rejected.append({"clause": c.uid, "reason": f"LLM error: {str(e)[:120]}"})
        for p, how in proposals:
            lim, why = validate(p, c, len(limits), how)
            if lim:
                limits.append(lim)
            else:
                rejected.append({"clause": c.uid, "proposal": p, "reason": why})
        if not limits and method in ("auto", "regex"):
            for p in extract_regex(c):
                lim, why = validate(p, c, len(limits), "regex")
                if lim:
                    limits.append(lim)
                else:
                    rejected.append({"clause": c.uid, "proposal": p, "reason": why})
        return limits, rejected

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(work, cands))

    table = RuleTable(model=getattr(llm, "label", "") if llm else "regex")
    for c, (lims, rej) in zip(cands, results):
        table.limits.extend(lims)
        table.rejected.extend(rej)
        table.clause_hashes[c.uid] = _hash(c)
    return table


def save_rule_table(t: RuleTable, path=LIMITS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(t.model_dump_json(indent=1), encoding="utf-8")


def load_rule_table(path=LIMITS_FILE) -> RuleTable | None:
    if not path.exists():
        return None
    return RuleTable.model_validate_json(path.read_text(encoding="utf-8"))
