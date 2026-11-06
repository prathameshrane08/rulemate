"""Requirements that a design document triggers, checked against what the document shows.

Some rules are not a limit on a measured value but a requirement that applies when facts about the ship hold:
"each vessel which makes voyages of more than 3 days ... and which carries a crew of 12 or more, must be provided
with a hospital space" (46 CFR 190.20-35(a)). Each trigger below names the clause it comes from; it is only used
when that clause is in the loaded rules, and every finding quotes the facts and the page it used. Findings are for
an engineer to confirm, never a PASS/FAIL verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..ingest.pipeline import load_index


@dataclass
class Trigger:
    doc: str
    clause_id: str
    needs: tuple[str, ...]  # fact parameters required
    applies: Callable[[dict], bool]
    check: Callable[[dict, list[dict]], tuple[str, str]]  # -> (status, message); status: met | not shown | review


def _hospital(f: dict, drawings: list[dict]) -> tuple[str, str]:
    if not drawings:
        return "not shown", "no GA drawing was read - confirm a hospital space on the GA"
    hits = [d for d in drawings if any("HOSPITAL" in w.upper() for w in d.get("words", []))]
    if hits:
        d = hits[0]
        return "met", f"\"HOSPITAL\" is labelled on p.{d['page']} (Dwg {d['drawing']}, {d['title'].title()})"
    return "not shown", "no space labelled HOSPITAL on the drawings read - confirm on the GA"


def _mess(f: dict, drawings: list[dict]) -> tuple[str, str]:
    return "review", (f"the mess room seats {f['messroom seats']:g} of {f['total complement']:g} persons at one sitting; "
                      "confirm how many eat at one time (sittings / watches)")


TRIGGERS = [
    Trigger("46CFR190", "190.20-35(a)", ("crew", "endurance"),
            lambda f: f["crew"] >= 12 and f["endurance"] > 3, _hospital),
    Trigger("46CFR190", "190.20-30(b)", ("messroom seats", "total complement"),
            lambda f: f["messroom seats"] < f["total complement"], _mess),
]


def rule_findings(ex) -> list[str]:
    facts = {}
    for x in ex.facts:
        if not x.item_id.startswith("G"):
            facts.setdefault(x.parameter, x)
    try:
        loaded = {(c.doc, c.clause_id) for c in load_index().clauses}
    except FileNotFoundError:
        loaded = set()
    out = []
    for t in TRIGGERS:
        if (t.doc, t.clause_id) not in loaded or not all(n in facts for n in t.needs):
            continue
        vals = {n: facts[n].value for n in t.needs}
        if not t.applies(vals):
            continue
        status, msg = t.check(vals, ex.drawings)
        basis = ", ".join(f"{n} {facts[n].value:g} {facts[n].unit} (p.{facts[n].source_page})" for n in t.needs)
        out.append(f"[{t.doc} § {t.clause_id}] applies ({basis}): {msg}. Status: {status}.")
    return out
