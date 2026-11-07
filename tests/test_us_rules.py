"""US regulations (46 CFR) and US design units: CFR parsing, feet/inches, equivalent values, change impact."""

from pathlib import Path

import pytest

from rulemate.compliance.check import DesignRow, Matcher, RowResult, diff_results, evaluate_row, read_design_csv
from rulemate.compliance.limits import build_rule_table
from rulemate.compliance.units import convert, parse_value
from rulemate.guardrails import extract_numbers
from rulemate.ingest.parsers import detect_style
from rulemate.ingest.pipeline import ancestors, ingest_file
from rulemate.ingest.loaders import load_blocks
from rulemate.lookup import find_clause, normalize_id
from rulemate.retrieval import extract_clause_ids

CFR_MD = """# 46 CFR PART 190—CONSTRUCTION AND ARRANGEMENT

## Subpart 190.10—Means of Escape

### § 190.10-20 No means for locking doors.

(a) No means shall be provided for locking door giving access to either of the two required means of escape.

### § 190.10-25 Stairway size.

(a) Stairways shall be of sufficient width having in mind the number of persons having access to such stairs.

(b) All interior stairways, other than those within the machinery spaces, shall have minimum width of 28 inches. The angle of inclination with the horizontal of such stairways shall not exceed 50°.

(c) Special consideration for relief may be given if it is shown to be impracticable to meet paragraph (b) of this section.

### § 190.10-30 Dead end corridors.

(a) Dead end corridors, or the equivalent, more than 40 feet in length shall not be permitted.

## Subpart 190.20—Accommodations

### § 190.20-15 Construction.

All crew spaces are to be constructed and arranged in a manner suitable to the purpose. See § 190.10-25.

### § 190.20-20 Sleeping accommodations.

(c) Each room must be of such size that there are at least 2.78 square meters (30 square feet) of deck area for each person accommodated. The clear head room must be not less than 190 centimeters (75 inches).

## Subpart 190.25—Rails and Guards

### § 190.25-5 Where rails required.

(a) The height of rails or bulwarks shall be at least 39 1/2 inches from the deck. The opening below the lowest course shall not be more than 9 inches.
"""


@pytest.fixture(scope="module")
def cfr(tmp_path_factory):
    p = tmp_path_factory.mktemp("rules") / "46CFR190.md"
    p.write_text(CFR_MD, encoding="utf-8")
    info, clauses = ingest_file(p)
    return p, info, clauses


# ---------------------------------------------------------------- parsing


def test_cfr_style_detected(cfr):
    p, info, _ = cfr
    assert detect_style(load_blocks(p)) == "cfr"
    assert info.style == "cfr"


def test_cfr_ids_and_hierarchy(cfr):
    _, _, clauses = cfr
    by = {c.clause_id: c for c in clauses}
    assert by["190.10"].kind == "heading" and by["190.10"].title == "Means of Escape"
    assert by["190.10-25"].kind == "heading" and by["190.10-25"].parent_id == "190.10"
    assert by["190.10-25(b)"].parent_id == "190.10-25"
    assert "28 inches" in by["190.10-25(b)"].text
    assert by["190.20-15"].kind == "clause"  # section without lettered paragraphs is itself the clause


def test_cfr_cross_references(cfr):
    _, _, clauses = cfr
    by = {c.clause_id: c for c in clauses}
    assert "190.10-25(b)" in by["190.10-25(c)"].refs  # "paragraph (b) of this section"
    assert "190.10-25" in by["190.20-15"].refs  # "See § 190.10-25"


def test_cfr_lookup_forms(cfr):
    _, _, clauses = cfr
    for q in ["190.10-25(b)", "§ 190.10-25(b)", "46 CFR 190.10-25(b)"]:
        assert [c.clause_id for c in find_clause(clauses, q)] == ["190.10-25(b)"], q
    assert extract_clause_ids("what does 46 CFR 190.10-30(a) say about 40 feet?") == ["190.10-30(a)"]
    assert normalize_id("(13.3.1)") == "13.3.1"
    assert ancestors("190.10-25(b)") == ["190.10-25", "190.10", "190"]


# ---------------------------------------------------------------- units


@pytest.mark.parametrize(
    "raw,unit,expected",
    [("3'-6\"", "", (42.0, "in")), ("3 ft 6 in", "", (42.0, "in")), ("39 1/2", "in", (39.5, "in")),
     ("1,25", "m", (1.25, "m")), ("40 ft", "", (40.0, "ft")), ("1250", "mm", (1250.0, "mm")),
     ("wide", "mm", (None, "mm"))],
)
def test_parse_design_values(raw, unit, expected):
    assert parse_value(raw, unit) == expected


def test_us_unit_conversion():
    assert convert(28, "inches", "mm") == pytest.approx(711.2)
    assert convert(40, "feet", "m") == pytest.approx(12.192)
    assert convert(300, "square feet", "m2") == pytest.approx(27.87, abs=0.01)


def test_numbers_with_fractions_and_us_units():
    nums = extract_numbers("at least 39 1/2 inches, 190 centimeters (75 inches), 40 feet, 300 square feet")
    assert nums == [(39.5, "in"), (190.0, "cm"), (75.0, "in"), (40.0, "ft"), (300.0, "ft2")]


# ---------------------------------------------------------------- limits


@pytest.fixture(scope="module")
def table(cfr):
    return build_rule_table(cfr[2], method="regex")


def _limits(table, cid):
    return sorted((l.comparator, l.value, l.unit) for l in table.limits if l.clause_id == cid)


def test_cfr_limits_extracted(table):
    assert _limits(table, "190.10-25(b)") == [("<=", 50.0, "°"), (">=", 28.0, "inches")]
    assert _limits(table, "190.10-30(a)") == [("<=", 40.0, "feet")]  # "more than 40 feet ... not permitted"
    assert _limits(table, "190.25-5(a)") == [("<=", 9.0, "inches"), (">=", 39.5, "inches")]


def test_per_person_quantities_are_not_room_limits(table):
    # "2.78 square meters ... for each person" must not become a per-room minimum
    assert ("m2" not in {l.unit for l in table.limits}) and all(l.value != 2.78 for l in table.limits)
    assert any("per-person" in r["reason"] for r in table.rejected)


def test_equivalent_values_are_one_limit(cfr):
    clause = next(c for c in cfr[2] if c.clause_id == "190.20-20(c)")
    llm_like = [  # an LLM tends to return both numbers of "190 centimeters (75 inches)"
        {"parameter": "clear head room", "comparator": ">=", "value": 75, "unit": "inches"},
        {"parameter": "clear head room", "comparator": ">=", "value": 190, "unit": "centimeters"},
    ]

    class FakeLLM:
        label = "fake"

        def complete(self, *a, **k):
            import json
            return json.dumps({"limits": llm_like})

    t = build_rule_table([clause], llm=FakeLLM(), method="llm")
    assert [(l.value, l.unit) for l in t.limits] == [(190.0, "centimeters")]  # the value written first
    assert "75 inches" in t.limits[0].notes[-1]


def test_us_design_values_checked_against_us_rules(table):
    m = Matcher(table.limits)
    csv = (
        "item_id,space,parameter,value,unit,source\n"
        "S1,Interior stairway 01 Deck,stairway width,2'-4\",,GA sheet 2 (measured)\n"
        "S2,Interior stairway 02 Deck,stairway width,26,in,GA sheet 2 (measured)\n"
        "S3,Interior stairway 01 Deck,stairway angle of inclination,52,degree,Profile\n"
    )
    rows = read_design_csv(csv)
    assert rows[0].value == 28.0 and rows[0].unit == "in" and rows[0].source == "GA sheet 2 (measured)"
    verdicts = [evaluate_row(r, m).verdict for r in rows]
    assert verdicts == ["PASS", "FAIL", "FAIL"]


# ---------------------------------------------------------------- change impact


def _res(i, v, verdict):
    return RowResult(row=DesignRow(item_id=i, parameter="p", value=v, unit="mm", raw_value=str(v)), verdict=verdict,
                     reason="")


def test_change_impact():
    before = [_res("A", 1200, "PASS"), _res("B", 900, "PASS"), _res("C", 5, "FAIL"), _res("D", 1, "PASS")]
    after = [_res("A", 1100, "FAIL"), _res("B", 950, "PASS"), _res("C", 5, "FAIL"), _res("E", 2, "PASS")]
    ch = diff_results(before, after)
    assert [(c.item_id, c.kind) for c in ch] == [("A", "verdict"), ("E", "new"), ("D", "removed"), ("B", "value")]
    assert "PASS -> FAIL" in ch[0].summary


def test_fraction_with_unicode_space():
    # hosted models write "39\u202f1/2 inches" (narrow no-break space)
    assert extract_numbers("at least 39\u202f1/2 inches") == [(39.5, "in")]
    assert extract_numbers("at least 39\u00a01/2 inches") == [(39.5, "in")]


def test_unrelated_limits_do_not_match():
    # read from a real trawler GA: none of these is limited by an accessibility or accommodation rule
    from rulemate.compliance.check import _plausible
    from rulemate.compliance.limits import Limit

    berth = Limit(id="b", clause_uid="d::190.20-20(d)", doc="d", clause_id="190.20-20(d)",
                  parameter="Sleeping accommodations The overall size of a berth", comparator=">=", value=68,
                  unit="centimeters", method="regex")
    grab = Limit(id="g", clause_uid="d::609.3", doc="d", clause_id="609.3", parameter="Spacing The space between the grab bar",
                 comparator=">=", value=1.5, unit="inches", method="regex")
    row = lambda p, v, u: DesignRow(item_id="x", parameter=p, value=v, unit=u, raw_value=str(v))  # noqa: E731
    assert not _plausible(row("length overall", 60, "m"), berth)  # 88 times the limit
    assert not _plausible(row("frame spacing", 2, "in"), grab)  # no specific word in common
    assert _plausible(row("berth width", 30, "in"), berth)
    assert _plausible(row("grab bar spacing", 2, "in"), grab)



def test_no_rule_is_not_needs_review():
    from rulemate.compliance.check import RowResult

    r = RowResult(row=DesignRow(item_id="x", parameter="frame spacing", value=600, unit="mm"), verdict="NEEDS REVIEW",
                  reason="No limit in the rules matches 'frame spacing' (none measures this kind of value).")
    assert r.no_rule and r.shown_verdict == "NO RULE"
    c = RowResult(row=DesignRow(item_id="y", parameter="p", value=1, unit="mm"), verdict="NEEDS REVIEW",
                  reason="Only conditional limits apply; confirm the condition.")
    assert not c.no_rule and c.shown_verdict == "NEEDS REVIEW"


def test_large_sheets_are_read_in_tiles():
    from rulemate.design.vision import tile_grid

    assert len(tile_grid(1224, 792)) == 1  # A3/B sheet: one request
    a0 = tile_grid(2384, 3370, max_tiles=4)
    assert len(a0) == 4 and all(x1 > x0 and y1 > y0 for x0, y0, x1, y1 in a0)
    xs = sorted({round(t[0]) for t in a0})
    assert xs[0] == 0 and a0[0][2] > a0[1][0]  # neighbouring tiles overlap
