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


# ---------------------------------------------------------------- Gemini readings are confirmed in code

from rulemate.design.vision import verify  # noqa: E402

PAGE_W, PAGE_H = 1224.0, 792.0


def _box(x0, y0, x1, y1):  # PDF points -> Gemini box_2d (0-1000, ymin xmin ymax xmax)
    return [y0 / PAGE_H * 1000, x0 / PAGE_W * 1000, y1 / PAGE_H * 1000, x1 / PAGE_W * 1000]


def test_gemini_reading_confirmed_by_noisy_ocr():
    words = [W("CREW", 600, 400), W("DOUBL:", 600, 409), W("01-34-0", 598, 418)]  # CAD-font OCR
    [r] = verify([{"label": "CREW DOUBLE", "room_number": "01-34-0", "kind": "stateroom", "berths": 2,
                   "box_2d": _box(596, 398, 640, 428)}], words, PAGE_W, PAGE_H)
    assert r.confirmed and r.berths_confirmed and r.berths == 2


def test_gemini_reading_with_nothing_on_the_sheet_is_not_used():
    words = [W("LAUNDRY", 300, 200)]
    [r] = verify([{"label": "CREW DOUBLE", "room_number": "02-99-0", "kind": "stateroom", "berths": 2,
                   "box_2d": _box(800, 500, 840, 520)}], words, PAGE_W, PAGE_H)
    assert not r.confirmed


def test_gemini_berths_must_agree_with_the_label():
    words = [W("CREW", 600, 400), W("DOUBLE", 600, 409)]
    [r] = verify([{"label": "CREW DOUBLE", "room_number": None, "kind": "stateroom", "berths": 3,
                   "box_2d": _box(596, 398, 640, 420)}], words, PAGE_W, PAGE_H)
    assert r.confirmed and not r.berths_confirmed and "label says 2" in r.notes[0]


def test_bad_box_is_skipped():
    assert verify([{"label": "X", "box_2d": None}], [], PAGE_W, PAGE_H) == []


# ---------------------------------------------------------------- picture check: Gemini reads, code confirms

def _png(w=1000, h=500):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_picture_values_confirmed_by_ocr(monkeypatch):
    from rulemate.design import picture

    proposals = [
        {"space": "Bathroom", "parameter": "door clear width", "value_text": '30"', "unit": '"',
         "box_2d": [100, 100, 140, 300]},  # written there
        {"space": "Cabin", "parameter": "turning space diameter", "value_text": "1500", "unit": "mm",
         "box_2d": [600, 600, 650, 800]},  # Gemini claims it, nothing written there
    ]
    monkeypatch.setattr(picture, "ask_gemini", lambda llm, png, **k: proposals)
    words = [('BATH DOOR CLEAR 30"', 90, 45, 320, 75)]  # OCR (text, x0, y0, x1, y1) in pixels
    values, _ = picture.read_picture(_png(), llm=None, words=words)
    assert [v.confirmed for v in values] == [True, False]
    assert values[0].value == 30 and values[0].unit == "in"
    rows = picture.to_rows(values, "x.png")
    assert len(rows) == 1 and rows[0].parameter == "door clear width" and rows[0].source_file == "upload:x.png"


def test_designer_words_map_to_rule_words():
    from rulemate.compliance.check import designer_to_rule_terms

    assert designer_to_rule_terms("desk height") == "desk (work surface) height"
    assert designer_to_rule_terms("WC seat height") == "WC (water closet) seat height"


def test_printed_berth_count_in_label_confirms_berths():
    words = [W("SENIOR", 600, 400), W("SCIENTIST", 600, 409), W("(2)", 610, 418)]
    [r] = verify([{"label": "SENIOR SCIENTIST (2)", "room_number": None, "kind": "stateroom", "berths": 2,
                   "box_2d": _box(596, 398, 650, 430)}], words, PAGE_W, PAGE_H)
    assert r.confirmed and r.berths_confirmed
