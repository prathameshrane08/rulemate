"""Compliance: unit conversion, limit validation, verdict logic (code only), explanation checks."""

import pytest

from rulemate.compliance.check import (
    DesignRow, LimitResult, Matcher, RowResult, claim_violations, evaluate_row, explain_row,
    read_design_csv, results_to_csv, run_check, verdict_violations,
)
from rulemate.compliance.limits import build_rule_table, extract_regex, validate, Limit
from rulemate.compliance.units import UnitError, compatible, convert
from rulemate.config import ROOT
from rulemate.ingest.pipeline import ingest_file
from rulemate.models import Clause

D = "SAMPLE_SYNTHETIC_rules"
SAMPLE = ROOT / "data" / "rules" / "SAMPLE_SYNTHETIC_rules.md"


# ---------------------------------------------------------------- units


@pytest.mark.parametrize(
    "v,src,dst,expected",
    [(1.1, "m", "mm", 1100), (21, "cm", "mm", 210), (0.9, "m", "mm", 900), (1, "min", "s", 60),
     (45, "degrees", "deg", 45), (150, "m2", "m²", 150), (2, "kN", "N", 2000)],
)
def test_convert(v, src, dst, expected):
    assert convert(v, src, dst) == pytest.approx(expected)


def test_incompatible_units():
    assert not compatible("mm", "min")
    assert not compatible("degree", "%")  # pint calls both dimensionless; we keep angles apart
    assert compatible("mm", "m")
    with pytest.raises(UnitError):
        convert(1, "mm", "s")
    assert not compatible("furlongs-ish", "mm")


# ---------------------------------------------------------------- limit validation


def C(cid, text, refs=()):
    return Clause(uid=f"{D}::{cid}", doc=D, clause_id=cid, text=text, title="T", refs=list(refs))


WIDTH = C("II-2/13.3.1.1", "The clear width of corridors serving as escape routes shall be not less than 1200 mm.")


def prop(**kw):
    base = {"parameter": "corridor clear width", "comparator": ">=", "value": 1200, "unit": "mm"}
    return {**base, **kw}


def test_validate_accepts_good_proposal():
    lim, why = validate(prop(quote="not less than 1200 mm"), WIDTH, 0, "llm")
    assert lim and not why and lim.quote == "not less than 1200 mm"
    assert lim.context.startswith("The clear width of corridors")


@pytest.mark.parametrize(
    "bad,reason",
    [({"value": 1100}, "does not appear"), ({"unit": "s"}, "not found"), ({"unit": "bananas"}, "unknown unit"),
     ({"comparator": "about"}, "comparator"), ({"parameter": ""}, "parameter")],
)
def test_validate_rejects(bad, reason):
    lim, why = validate(prop(**bad), WIDTH, 0, "llm")
    assert lim is None and reason in why


def test_validate_corrects_comparator_from_text():
    lim, _ = validate(prop(comparator="<="), WIDTH, 0, "llm")
    assert lim.comparator == ">=" and "corrected" in lim.notes[0]


def test_validate_rejects_per_person_rate():
    c = C("II-2/13.4.2.1", "The clear width shall be not less than 10 mm per person served.")
    lim, why = validate(prop(value=10), c, 0, "llm")
    assert lim is None and "rate" in why


def test_validate_drops_junk_qualifier_and_bad_quote():
    lim, _ = validate(prop(qualifier="table", quote="at least 1200 mm"), WIDTH, 0, "llm")
    assert lim.qualifier is None and lim.quote is None


def test_regex_extractor_on_sample():
    clauses = ingest_file(SAMPLE)[1]
    t = build_rule_table(clauses, method="regex")
    by = {}
    for l in t.limits:
        by.setdefault(l.clause_id, []).append(l)
    assert [(l.comparator, l.value) for l in by["II-2/9.3.3"]] == [("<=", 40), (">=", 10)]
    relax = by["II-2/13.3.3.2"][0]
    assert (relax.comparator, relax.value, relax.unit) == ("<=", 50, "m") and relax.condition
    assert by["II-2/13.3.1.2"][0].qualifier == "crew accommodation"
    riser, tread = by["II-2/13.3.2.5"]
    assert "riser" in riser.context and "tread" in tread.context and "tread" not in riser.context
    assert "II-2/13.4.2.1" not in by  # "10 mm per person" is a rate, not a plain limit


# ---------------------------------------------------------------- verdict logic (no LLM, lexical matching)


def L(cid, parameter, cmp, value, unit, qualifier=None, condition=None, context="", refs=()):
    return Limit(id=f"{D}::{cid}#0", clause_uid=f"{D}::{cid}", doc=D, clause_id=cid, parameter=parameter,
                 comparator=cmp, value=value, unit=unit, qualifier=qualifier, condition=condition,
                 context=context, refs=list(refs), method="manual")


LIMITS = [
    L("II-2/13.3.1.1", "corridor clear width", ">=", 1200, "mm"),
    L("II-2/13.3.1.2", "corridor clear width", ">=", 900, "mm", qualifier="crew accommodation",
      condition="the corridor serves not more than 50 persons"),
    L("II-2/13.5.2", "door clear width", ">=", 800, "mm"),
    L("II-2/13.5.2b", "door clear width", ">=", 700, "mm", qualifier="cabin doors"),
    L("II-2/13.3.3.1", "travel distance", "<=", 40, "m"),
    L("II-2/13.3.3.2", "public space route length", "<=", 50, "m", condition="route passes through a public space",
      context="the travel distance in 3.3.1 may be increased to 50 m", refs=["II-2/13.3.3.1"]),
    L("II-2/13.3.2.4", "handrail height", ">=", 850, "mm"),
    L("II-2/13.3.2.4", "handrail height", "<=", 1000, "mm"),
]
M = Matcher(LIMITS)  # no encoder -> lexical similarity


def verdict(param, value, unit, space=""):
    return evaluate_row(DesignRow(parameter=param, value=value, unit=unit, space=space), M)


@pytest.mark.parametrize(
    "param,value,unit,space,expected",
    [
        ("corridor clear width", 1250, "mm", "passenger corridor", "PASS"),
        ("corridor clear width", 1.1, "m", "passenger corridor", "FAIL"),  # unit conversion, crew rule n/a
        ("corridor clear width", 950, "mm", "crew corridor", "NEEDS REVIEW"),  # only via the crew relaxation
        ("corridor clear width", 850, "mm", "crew corridor", "FAIL"),  # fails even the relaxation
        ("door clear width", 760, "mm", "cabin door 8012", "PASS"),  # cabin rule supersedes general 800 mm
        ("door clear width", 760, "mm", "escape route door", "FAIL"),
        ("travel distance", 38, "m", "", "PASS"),
        ("travel distance", 46.5, "m", "", "NEEDS REVIEW"),  # relaxation found through the reference to 3.3.1
        ("travel distance", 55, "m", "", "FAIL"),
        ("handrail height", 0.9, "m", "", "PASS"),
        ("handrail height", 1.1, "m", "", "FAIL"),  # max side of a min/max pair
    ],
)
def test_verdicts(param, value, unit, space, expected):
    assert verdict(param, value, unit, space).verdict == expected


def test_needs_review_cases():
    assert "not a number" in evaluate_row(DesignRow(parameter="corridor clear width", raw_value="wide", unit="mm"), M).reason
    assert verdict("corridor clear width", 1200, "s").verdict == "NEEDS REVIEW"  # incompatible unit
    assert "matches" in verdict("ceiling paint colour code", 5, "mm").reason  # nothing covers it


def test_reason_cites_clauses_and_shows_conversion():
    r = verdict("corridor clear width", 1.1, "m", "passenger corridor")
    assert "1.1 m (= 1100 mm) does not meet >= 1200 mm" in r.reason
    assert f"[{D} § II-2/13.3.1.1]" in r.reason


# ---------------------------------------------------------------- explanation checks


def _res(outcome="pass", verdict="NEEDS REVIEW"):
    lim = LIMITS[1]
    return RowResult(row=DesignRow(parameter="corridor clear width", value=950, unit="mm", space="crew corridor"),
                     verdict=verdict, reason="x",
                     limits=[LimitResult(limit=lim, similarity=1, value_in_limit_unit=950, outcome=outcome, role="conditional")])


def test_claim_contradicting_code_is_rejected():
    v = claim_violations("The value of 950 mm does not meet the minimum of 900 mm.", _res())
    assert any("[claim]" in x for x in v)


def test_condition_stated_as_fact_is_rejected():
    assert any("[condition]" in x for x in claim_violations("The corridor serves more than 50 persons.", _res()))
    assert not claim_violations("This applies only if the corridor serves not more than 50 persons.", _res())


def test_verdict_contradiction_is_rejected():
    assert verdict_violations("The corridor complies with the rule.", "FAIL")
    assert verdict_violations("The design fails the requirement.", "PASS")
    assert not verdict_violations("The design does not meet the minimum width.", "FAIL")


class FakeLLM:
    label = "fake"

    def __init__(self, replies):
        self.replies = list(replies)

    def complete(self, messages, **kw):
        return self.replies.pop(0)


def test_explain_row_retry_then_verified():
    clause = C("II-2/13.3.1.2", "In crew accommodation, the clear width of corridors may be reduced to not less "
               "than 900 mm, provided that the corridor serves not more than 50 persons.")
    bad = f"950 mm does not meet 900 mm [{D} § II-2/13.3.1.2]."
    good = (f"The value of 950 mm is above 900 mm, which is allowed only if the corridor serves not more than "
            f"50 persons, so this must be confirmed [{D} § II-2/13.3.1.2].")
    r = explain_row(_res(), {clause.uid: clause}, FakeLLM([bad, good]))
    assert r.explanation_status == "verified" and "confirmed" in r.explanation


def test_explain_row_rejected_twice_keeps_code_reason():
    clause = C("II-2/13.3.1.2", "... not less than 900 mm, provided that the corridor serves not more than 50 persons.")
    r = explain_row(_res(), {clause.uid: clause}, FakeLLM(["It is probably fine.", "It is probably fine."]))
    assert r.explanation_status == "rejected" and r.explanation == "" and r.reason == "x"


# ---------------------------------------------------------------- CSV in / out


def test_read_design_csv_aliases_and_bad_values():
    rows = read_design_csv("ID,Location,Parameter,Value,Units\nA1,Deck 3,corridor clear width,approx. wide,mm\n")
    assert rows[0].space == "Deck 3" and rows[0].value is None
    with pytest.raises(ValueError):
        read_design_csv("foo,bar\n1,2\n")


def test_results_csv_roundtrip():
    out = results_to_csv([verdict("corridor clear width", 1.1, "m", "passenger corridor")])
    assert "FAIL" in out and "II-2/13.3.1.1" in out


# ---------------------------------------------------------------- the sample design end to end (real embeddings)


EXPECTED = {
    "D01": "PASS", "D02": "FAIL", "D03": "NEEDS REVIEW", "D04": "PASS", "D05": "FAIL", "D06": "PASS",
    "D07": "NEEDS REVIEW", "D08": "PASS", "D09": "FAIL", "D10": "FAIL", "D11": "PASS", "D12": "PASS",
    "D13": "FAIL", "D14": "PASS", "D15": "FAIL",
}


def test_sample_design_end_to_end():
    from rulemate.retrieval import Retriever

    clauses = ingest_file(SAMPLE)[1]
    r = Retriever(clauses, use_dense=True)
    if r.mode != "hybrid":
        pytest.skip("embedding model not available")
    table = build_rule_table(clauses, method="regex")
    rows = read_design_csv((ROOT / "data" / "designs" / "sample_design.csv").read_bytes())
    results = run_check(rows, table, clauses, encoder=r._model_obj())
    assert {x.row.item_id: x.verdict for x in results} == EXPECTED
