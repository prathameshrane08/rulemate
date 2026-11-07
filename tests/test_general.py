"""General answers: every source the model names is checked in code; nothing is called verified."""
from rulemate.general import _parse, bot_provider, check_references
from rulemate.retrieval import get_retriever


def test_sources_are_checked():
    r = get_retriever()
    refs = [{"source": "ADA 404.2.3", "supports": "door clear width 32 inches"},
            {"source": "ADA 404.2.3", "supports": "door clear width 30 inches"},
            {"source": "SOLAS Chapter II-2, Regulation 13", "supports": "means of escape", "url": "https://www.imo.org/x"},
            {"source": "Some blog", "supports": "x", "url": "https://blog.example.com/a"}]
    out, unverified = check_references("Doors need 32 inches; corridors 1200 mm.", refs, r)
    assert out[0]["status"] == "loaded clause: read the sentence" and "32 inches" in out[0]["why"]
    assert out[1]["status"] == "number NOT in this clause"
    assert out[2]["status"] == "named source, not loaded" and out[2]["url"] == "https://www.imo.org/x"
    assert out[3]["status"] == "not identified" and out[3]["url"] == "" and out[3]["url_dropped"]
    assert unverified == ["1200 mm"]


def test_bot_never_uses_gemini(monkeypatch):
    monkeypatch.setenv("COPILOT_LLM_PROVIDER", "gemini,groq,ollama")
    assert bot_provider() == "groq,ollama"


def test_plain_text_reply_still_shown_without_sources():
    d = _parse("Just some text, no JSON.")
    assert d["answer"].startswith("Just") and d["references"] == []


def test_a_subject_the_rules_never_mention_stays_not_found():
    from rulemate.answer import unknown_terms

    from types import SimpleNamespace as NS

    r = NS(clauses=[NS(title="Means of escape", text="Crew corridors shall be not less than 700 mm wide; passenger "
                                                      "corridors narrow to 900 mm. Travel distance through a lobby "
                                                      "route shall not be long. Door clear width shall be 32 inches for "
                                                      "accessible doors.")])
    assert unknown_terms("What is the minimum size of a helicopter landing area?", r) == ["helicopter", "landing"]
    for q in ["Can crew corridors be narrower than passenger corridors?",
              "Can the travel distance be longer if the escape route goes through a lobby?",
              "What clear width must an accessible door have?"]:
        assert unknown_terms(q, r) == [], q


def test_numbers_left_out_by_the_model_are_quoted_from_the_cited_clause():
    from rulemate.answer import with_key_values

    r = get_retriever()
    c = r.by_uid["36CFR1191AppD::404.2.3"]
    text, uids = with_key_values("Door openings shall provide a clear width of 32 inches (815 mm) minimum "
                                 "[36CFR1191AppD § 404.2.3].", [c], [])
    assert "quoted word for word" in text and "36 inches (915 mm) minimum" in text and uids
    assert not text.rstrip().endswith("2.")
    full, none = with_key_values(text, [c], [])  # nothing missing any more -> unchanged
    assert none == [] or full.count("quoted word for word") == 1


def test_table_units_and_unusual_hyphens_do_not_reject_a_correct_answer():
    from rulemate.guardrails import check_answer
    from rulemate.models import Clause

    t = Clause(uid="S::II-2 Table 13.1", doc="S", clause_id="II-2 Table 13.1", title="Minimum clear widths",
               text="| Escape route element | Minimum clear width (mm) |\n| Crew corridor | 900 |\n| Passenger corridor | 1200 |",
               kind="table", path=[], refs=[])
    ok = check_answer("Crew corridors need a minimum clear width of 900 mm [S § II-2 Table 13.1].", [t])
    assert ok.ok, ok.violations
    bad = check_answer("Crew corridors need a minimum clear width of 900 m [S § II-2 Table 13.1].", [t])
    assert not bad.ok  # a wrong unit is still caught
    c = Clause(uid="S::II-2/9.3.4", doc="S", clause_id="II-2/9.3.4", title="Fire doors",
               text="After release, the closing requirements of 3.3 apply.", kind="clause", path=[], refs=[])
    r = check_answer("After release, the closing requirements of 3.3 (= II‑2/9.3.3) apply [S § II‑2/9.3.4].", [c])
    assert not any("number 2" in str(v) for v in r.violations)


def test_mlc_sources_in_general_answers_are_matched_to_the_loaded_text():
    r = get_retriever()
    if "MLC2006::A3.1/6(a)" not in r.by_uid:
        import pytest

        pytest.skip("MLC 2006 not downloaded (scripts/fetch_mlc.py)")
    out, _ = check_references("x", [{"source": "MLC 2006, Standard A3.1, paragraph 6(a)", "supports": "203 centimetres"},
                                    {"source": "MLC 2006, Article 2", "supports": "definitions"}], r)
    assert out[0]["uid"] == "MLC2006::A3.1/6(a)" and out[0]["status"] == "loaded clause: read the sentence"
    assert out[1]["uid"] == "MLC2006::Art.II"
