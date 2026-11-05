from pathlib import Path

import pytest

from rulemate.config import ROOT
from rulemate.ingest.loaders import Block, load_blocks
from rulemate.ingest.parsers import detect_style, plausible_next
from rulemate.ingest.pipeline import ancestors, ingest_file
from rulemate.lookup import find_clause

SAMPLE = ROOT / "data" / "rules" / "SAMPLE_SYNTHETIC_rules.md"


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _ids(clauses):
    return {c.clause_id: c for c in clauses}


SOLAS_TXT = """Chapter II-2 - Construction
Regulation 13 - Means of escape
3 Escape routes
3.1 Corridors
3.1.1 The clear width of corridors shall be not less than 1200 mm.
This sentence wraps onto a second line
40 persons is a value at line start, not a clause.
3.1.2 Corridor widths shall be calculated as in 4.2 and inclined up to 3.5 degrees.
4 Calculation
4.2 The width shall be not less than 10 mm per person (see regulation 9.2).
Regulation 9 - Containment of fire
2 Zones
2.1 Zones shall not exceed 48 m (see II-2/13.3.1.1).
"""


def test_solas_ids_titles_and_continuations(tmp_path):
    info, clauses = ingest_file(_write(tmp_path, "solas.txt", SOLAS_TXT))
    assert info.style == "solas"
    c = _ids(clauses)
    assert {"II-2", "II-2/13", "II-2/13.3", "II-2/13.3.1", "II-2/13.3.1.1", "II-2/13.4.2", "II-2/9.2.1"} <= set(c)
    first = c["II-2/13.3.1.1"]
    assert first.title == "Corridors"  # inherited from heading 3.1
    assert "second line" in first.text and "40 persons" in first.text  # not split on "40"
    assert first.parent_id == "II-2/13.3.1"
    assert first.path[0].startswith("II-2 ")


def test_solas_cross_references(tmp_path):
    _, clauses = ingest_file(_write(tmp_path, "solas.txt", SOLAS_TXT))
    c = _ids(clauses)
    assert c["II-2/13.3.1.2"].refs == ["II-2/13.4.2"]  # "3.5 degrees" is a value, not a ref
    assert c["II-2/13.4.2"].refs == ["II-2/9.2"]  # regulation 9.2 -> II-2/9.2 (heading)
    assert c["II-2/9.2.1"].refs == ["II-2/13.3.1.1"]  # absolute reference


CLASS_TXT = """RULES FOR CLASSIFICATION Pt.3 Ch.2
Section 4 Hull girder strength
1 General
1.1 Application
[1.1.1] These requirements apply to all ships. See [2.1.3] and Sec.5 [1.2].
2 Plating
2.1 Thickness
2.1.3 The thickness shall be not less than 6.5 mm.
Section 5 Openings
1 General
1.2 Openings shall be rounded.
"""


def test_class_society_style(tmp_path):
    info, clauses = ingest_file(_write(tmp_path, "class.txt", CLASS_TXT))
    assert info.style == "class"
    c = _ids(clauses)
    assert "Pt.3 Ch.2 Sec.4 [2.1.3]" in c
    assert "Pt.3 Ch.2 Sec.5 [1.2]" in c
    assert c["Pt.3 Ch.2 Sec.4 [1.1.1]"].refs == ["Pt.3 Ch.2 Sec.5 [1.2]", "Pt.3 Ch.2 Sec.4 [2.1.3]"]


def test_decimal_and_fallback_styles(tmp_path):
    dec = "\n".join(f"{i}.1 Requirement number {i} shall apply." for i in range(1, 7))
    info, clauses = ingest_file(_write(tmp_path, "dec.txt", dec))
    assert info.style == "decimal"
    assert "4.1" in _ids(clauses)

    md = "# Guidance\nSome free text.\n## Ventilation\nVentilation text here.\n"
    info, clauses = ingest_file(_write(tmp_path, "free.md", md))
    assert info.style == "fallback"
    assert [c.title for c in clauses] == ["Guidance", "Ventilation"]


def test_plausible_next_rejects_values_and_page_numbers():
    assert plausible_next((3, 1, 1), (3, 1, 2))
    assert plausible_next((3, 1, 2), (4,))
    assert plausible_next((3,), (3, 1))
    assert not plausible_next((3, 1, 2), (40,))
    assert not plausible_next((3, 1, 2), (3, 1))  # going back to an ancestor
    assert not plausible_next((3, 1, 2), (2024,))


def test_markdown_table_kept_intact(tmp_path):
    md = (
        "Regulation 1 - Tables\n1 Scope\n1.1 Widths are in Table 1.1.\n"
        "Table 1.1 - Widths\n| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n1.2 Next clause.\n"
    )
    _, clauses = ingest_file(_write(tmp_path, "t.md", md))
    c = _ids(clauses)
    t = c["Table 1.1"]
    assert t.kind == "table"
    assert "| 3 | 4 |" in t.text and t.text.count("\n") >= 4
    assert c["Reg.1.1.1"].refs == ["Table 1.1"]
    assert c["Reg.1.1.2"].text == "Next clause."


def test_sample_document():
    info, clauses = ingest_file(SAMPLE)
    assert info.synthetic and all(c.synthetic for c in clauses)
    assert info.n_tables == 2
    assert sum(c.kind == "clause" for c in clauses) >= 35
    c = _ids(clauses)
    assert c["II-2/13.3.2.1"].page == 3
    assert "45 degrees" in c["II-2/13.3.2.1"].text
    assert c["II-2/13.3.1.4"].refs == ["II-2/13.4.2"]
    assert not any(cl.unresolved_refs for cl in clauses)


def test_lookup_variants():
    _, clauses = ingest_file(SAMPLE)
    assert [c.clause_id for c in find_clause(clauses, "Reg. II-2/13.3.2.1")] == ["II-2/13.3.2.1"]
    assert [c.clause_id for c in find_clause(clauses, "13.3.2.1")] == ["II-2/13.3.2.1"]
    assert [c.clause_id for c in find_clause(clauses, "table 13.1")] == ["II-2 Table 13.1"]
    assert find_clause(clauses, "99.9") == []


def test_ancestors():
    assert ancestors("II-2/13.4.2.1") == ["II-2/13.4.2", "II-2/13.4", "II-2/13"]
    assert ancestors("Pt.3 Ch.2 Sec.4 [2.1]") == ["Pt.3 Ch.2 Sec.4 [2]", "Pt.3 Ch.2 Sec.4"]


# ---- format loaders -------------------------------------------------------


def test_docx_loader(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_heading("Regulation 13 - Means of escape", level=2)
    d.add_paragraph("3 Corridors")
    d.add_paragraph("3.1 The clear width shall be not less than 1200 mm.")
    d.add_paragraph("3.2 Dead ends shall not exceed 7 m.")
    d.add_paragraph("Table 13.1 - Widths")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Element", "Width"
    t.cell(1, 0).text, t.cell(1, 1).text = "Corridor", "1200"
    p = tmp_path / "r.docx"
    d.save(p)
    info, clauses = ingest_file(p)
    c = _ids(clauses)
    assert info.style == "solas"
    assert "1200 mm" in c["Reg.13.3.1"].text
    assert "| Corridor | 1200 |" in c["Table 13.1"].text


def test_html_loader(tmp_path):
    html = """<html><body><nav>menu</nav><h2>Regulation 13 - Means of escape</h2>
    <p>3 Corridors</p><p>3.1 The clear width shall be not less than 1200 mm.</p>
    <p>3.2 See 3.1 for widths.</p>
    <table><caption>Table 13.1 - Widths</caption><tr><th>Element</th><th>Width</th></tr>
    <tr><td>Corridor</td><td>1200</td></tr></table></body></html>"""
    blocks = load_blocks(_write(tmp_path, "r.html", html))
    assert not any(b.text == "menu" for b in blocks)
    assert any(b.kind == "table" for b in blocks)
    _, clauses = ingest_file(tmp_path / "r.html")
    c = _ids(clauses)
    assert c["Reg.13.3.2"].refs == ["Reg.13.3.1"]
    assert "| Corridor | 1200 |" in c["Table 13.1"].text


def test_pdf_loader_pages_and_table(tmp_path):
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet

    ss = getSampleStyleSheet()["Normal"]
    path = tmp_path / "r.pdf"
    story = [
        Paragraph("Regulation 13 - Means of escape", ss),
        Paragraph("3 Corridors", ss),
        Paragraph("3.1 The clear width shall be not less than 1200 mm.", ss),
        PageBreak(),
        Paragraph("3.2 Dead-end corridors shall not exceed 7 m.", ss),
        Paragraph("Table 13.1 - Widths", ss),
        Table([["Element", "Width"], ["Corridor", "1200"]], style=TableStyle([("GRID", (0, 0), (-1, -1), 0.5, "black")])),
    ]
    SimpleDocTemplate(str(path), pagesize=A4).build(story)
    _, clauses = ingest_file(path)
    c = _ids(clauses)
    assert c["Reg.13.3.1"].page == 1
    assert c["Reg.13.3.2"].page == 2
    assert "| Corridor | 1200 |" in c["Table 13.1"].text


def test_detect_style_on_blocks():
    blocks = [Block("Regulation 5 - X"), Block("1 A"), Block("1.1 B shall."), Block("1.2 C shall.")]
    assert detect_style(blocks) == "solas"
