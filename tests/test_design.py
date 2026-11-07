"""Design interpretation: grouping OCR words of a GA drawing into berth labels, stated facts, rule findings.

Word positions mimic the OCR output of the NOAA GA (second deck): about 8 pt between label lines, the occupancy
marker "(n)" right under the role text.
"""

from rulemate.design.extract import Extraction, Fact, Word, drawing_meta, room_labels, text_facts
from rulemate.design.findings import rule_findings


def W(text, x0, y0, x1=None, y1=None):
    return Word(text, x0, y0, x1 if x1 is not None else x0 + 6 * len(text), y1 if y1 is not None else y0 + 10.0, 0.99)


def test_label_lines_and_marker_grouped():
    words = [W("SENIOR", 230, 193), W("SCIENTIST", 226, 202), W("(2)", 237, 210, 252, 222)]
    [r] = room_labels(words)
    assert r.raw == "SENIOR SCIENTIST (2)" and r.persons == 2 and r.group == "scientific personnel"


def test_stacked_labels_do_not_steal_words():
    # "CHIEF / SCIENTIST / (1) / SENIOR / SCIENTIST / (1)": each word belongs to the nearest marker below it
    words = [W("CHIEF", 226, 104), W("SCIENTIST", 217, 110), W("(1)", 230, 119, 244, 130),
             W("SENIOR", 222, 129), W("SCIENTIST", 218, 137), W("(1)", 230, 145, 244, 158)]
    labels = room_labels(words)
    assert [l.raw for l in labels] == ["CHIEF SCIENTIST (1)", "SENIOR SCIENTIST (1)"]


def test_callouts_and_symbols_are_not_label_text():
    words = [W("CRANE FOUNDATION", 562, 162), W("MESSMAN", 564, 185), W("(1)", 574, 194, 589, 205),
             W("T/S", 552, 183), W("LKR", 600, 186)]
    [r] = room_labels(words)
    assert r.raw == "MESSMAN (1)" and r.group == "crew"


def test_role_without_count_is_reported():
    words = [W("WIPER", 700, 300), W("OILER", 700, 320), W("COOK", 400, 300), W("(2)", 405, 309, 420, 320)]
    labels = room_labels(words)
    assert [l.raw for l in labels] == ["COOK (2)"]
    assert sorted(w.text for w in room_labels.unlabelled) == ["OILER", "WIPER"]


def test_drawing_title_block():
    words = [W("GENERAL ARRANGEMENT", 2921, 1940), W("SECOND DECK", 2993, 1970), W("PLAN AT SECOND DECK", 1318, 1765),
             W("DWG. No. 2175-000-05", 2791, 2106), W("SCALE: 1/8\"=1'-0\"", 3222, 2065)]
    m = drawing_meta(words)
    assert m["is_ga"] and m["drawing"] == "2175-000-05" and m["title"] == "SECOND DECK" and m["deck"] == "Second Deck"


def test_stated_facts_keep_page_and_sentence():
    pages = ["intro", "Galley and storage spaces permit operations for a minimum of 60 days without replenishment. "
                      "The mess room can accommodate up to 32 persons at one seating."]
    facts = {f[1]: f for f in text_facts(pages)}
    assert facts["endurance"][3] == 60 and facts["endurance"][5] == 2
    assert facts["messroom seats"][3] == 32 and "32 persons at one seating" in facts["messroom seats"][6]


def _ex(**vals):
    ex = Extraction(file="x.pdf", doc_label="X")
    for i, (k, v) in enumerate(vals.items()):
        ex.facts.append(Fact(f"T{i}", "Ship", k.replace("_", " "), v, "persons", "src", source_page=3))
    return ex


def test_hospital_trigger_uses_drawings():
    ex = _ex(crew=13, endurance=21)
    [f] = rule_findings(ex)
    assert "190.20-35(a)" in f and "not shown" in f  # required, no drawing read
    ex.drawings = [{"page": 2, "drawing": "6096-070-001", "title": "", "view": "", "rooms": 0, "words": ["HOSPITAL"]}]
    [f] = rule_findings(ex)
    assert "Status: review" in f  # only mentioned (e.g. revision list), not on a plan view
    ex.drawings.append({"page": 10, "drawing": "6096-070-001", "title": "", "view": "PLAN 8-4C", "rooms": 0,
                        "words": ["HOSPNAL"]})  # CAD-font OCR
    [f] = rule_findings(ex)
    assert "Status: met" in f and "p.10" in f


def test_trigger_does_not_apply_below_threshold():
    assert rule_findings(_ex(crew=11, endurance=21)) == []
    assert rule_findings(_ex(crew=13, endurance=2)) == []


# ---------------------------------------------------------------- stair angle from vector lines

from rulemate.design.measure import flights_from_lines  # noqa: E402


def test_stair_flight_angle_from_stringers():
    # RCRV inboard profile: two stringers of one flight at 49.97 and 50.02 degrees (PDF coordinate rounding)
    lines = [(49.97, 46.1, (699, 415, 729, 450)), (50.02, 46.1, (700, 416, 730, 451)),
             (74.97, 38.6, (770, 300, 780, 337))]  # mast line: no stair label nearby
    words = [W("STAIRWAY", 690, 395), W("1-25-0", 695, 404)]
    [f] = flights_from_lines(lines, words)
    assert f.angle == 50.0 and f.stringers == 2 and f.label == "STAIRWAY" and f.room_no == "1-25-0"
    assert not f.machinery


def test_stair_in_machinery_space_is_marked():
    lines = [(49.99, 57.3, (391, 453, 428, 497))]
    words = [W("STAIR", 380, 440), W("ENGINE ROOM", 420, 500)]
    [f] = flights_from_lines(lines, words)
    assert f.machinery
