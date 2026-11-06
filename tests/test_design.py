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
    ex.drawings = [{"page": 42, "drawing": "2175-000-05", "title": "SECOND DECK", "words": ["HOSPITAL", "AND"]}]
    [f] = rule_findings(ex)
    assert "Status: met" in f and "p.42" in f


def test_trigger_does_not_apply_below_threshold():
    assert rule_findings(_ex(crew=11, endurance=21)) == []
    assert rule_findings(_ex(crew=13, endurance=2)) == []
