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
