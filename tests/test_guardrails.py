"""Guardrails: good answers pass, bad answers are rejected with a useful reason."""

import pytest

from rulemate.answer import answer_question
from rulemate.config import ROOT
from rulemate.guardrails import check_answer, extract_numbers, split_sentences
from rulemate.ingest.pipeline import ingest_file
from rulemate.llm import LLMError
from rulemate.models import Clause
from rulemate.retrieval import Retriever

D = "SAMPLE_SYNTHETIC_rules"


def C(cid, text, doc=D):
    return Clause(uid=f"{doc}::{cid}", doc=doc, clause_id=cid, text=text)


CORRIDOR = C("II-2/13.3.1.1", "The clear width of corridors serving as escape routes shall be not less than 1200 mm.")
CREW = C("II-2/13.3.1.2", "In crew accommodation, the clear width of corridors may be reduced to not less than 900 mm, "
         "provided that the corridor serves not more than 50 persons.")
STAIR = C("II-2/13.3.2.1", "Stairways serving as escape routes shall have an angle of inclination not exceeding 45 degrees to the horizontal.")
DOORS = C("II-2/13.5.1", "Doors in escape routes shall in general open in the direction of escape.")
CLASS = C("Pt.3 Ch.2 Sec.4 [2.1.3]", "The thickness shall be not less than 6.5 mm.", doc="DNV_Pt3Ch2")
UNRETRIEVED = C("II-2/9.3.2", "Fire doors in stairway enclosures shall have a fire integrity rating of not less than 30 min.")
RETRIEVED = [CORRIDOR, CREW, STAIR, DOORS, CLASS]


def kinds(answer, retrieved=RETRIEVED):
    return [v.kind for v in check_answer(answer, retrieved).violations]


# ---------------------------------------------------------------- good answers pass


@pytest.mark.parametrize(
    "answer",
    [
        f"Escape corridors must be at least 1200 mm wide [{D} § II-2/13.3.1.1].",
        # citation after the full stop, two sentences, condition kept
        f"Escape corridors must be at least 1200 mm wide. [{D} § II-2/13.3.1.1] In crew accommodation this may be "
        f"reduced to 900 mm if the corridor serves not more than 50 persons [{D} § II-2/13.3.1.2].",
        # bullets with a lead-in line
        f"The limits are:\n- corridors: not less than 1200 mm [{D} § II-2/13.3.1.1]\n"
        f"- stair angle: not exceeding 45 degrees [{D} § II-2/13.3.2.1]",
        # exact quote, unit alias (degrees -> °)
        f'Stairs must have "an angle of inclination not exceeding 45 degrees" [{D} § II-2/13.3.2.1].',
        f"The maximum stair angle is 45° [{D} § II-2/13.3.2.1].",
        # hedge word allowed because the source uses it
        f"Doors in escape routes shall in general open in the direction of escape [{D} § II-2/13.5.1].",
        # class-society ID with nested brackets
        "Plating must be at least 6.5 mm thick [DNV_Pt3Ch2 § Pt.3 Ch.2 Sec.4 [2.1.3]].",
        # absence statement without numbers needs no citation
        f"Corridors must be at least 1200 mm wide [{D} § II-2/13.3.1.1]. The rules do not specify a maximum width.",
        # mentioning a clause number in prose is not a numeric claim
        f"Regulation 13.3.1.1 sets the corridor width at 1200 mm [{D} § II-2/13.3.1.1].",
    ],
)
def test_good_answers_pass(answer):
    res = check_answer(answer, RETRIEVED)
    assert res.ok, res.violations


# ---------------------------------------------------------------- bad answers are rejected


def test_rejects_missing_citation():
    assert "citation" in kinds("Corridors must be at least 1200 mm wide.")
    assert "citation" in kinds(
        f"Corridors must be at least 1200 mm wide [{D} § II-2/13.3.1.1]. Stairs must be steep enough for safe use."
    )


def test_rejects_citation_of_unretrieved_clause():
    k = kinds(f"Stair doors need 30 min fire integrity [{D} § II-2/9.3.2].")
    assert "retrieved" in k


def test_rejects_invented_clause_id():
    assert "retrieved" in kinds(f"Corridors must be 1200 mm wide [{D} § II-2/13.9.9].")


def test_rejects_number_not_in_source():
    assert "number" in kinds(f"Corridors must be at least 1100 mm wide [{D} § II-2/13.3.1.1].")


def test_rejects_converted_unit():
    assert "number" in kinds(f"Corridors must be at least 1.2 m wide [{D} § II-2/13.3.1.1].")
    assert "number" in kinds(f"Corridors must be at least 1200 m wide [{D} § II-2/13.3.1.1].")


def test_rejects_number_supported_only_by_other_sentence_clause():
    # 45 is in STAIR, but this sentence cites CORRIDOR
    assert "number" in kinds(f"Corridors are 1200 mm wide and stairs 45 degrees [{D} § II-2/13.3.1.1].")


def test_rejects_misquote():
    assert "quote" in kinds(f'The rule says "corridors shall be at least 1200 mm" [{D} § II-2/13.3.1.1].')


@pytest.mark.parametrize("hedge", ["probably", "typically", "usually", "generally"])
def test_rejects_hedge_words(hedge):
    assert "hedge" in kinds(f"Corridors are {hedge} at least 1200 mm wide [{D} § II-2/13.3.1.1].")


def test_mangled_doc_name_is_rewritten_to_canonical_citation():
    res = check_answer("Corridors must be at least 1200 mm wide [doc § II-2/13.3.1.1].", RETRIEVED)
    assert res.ok
    assert res.text == f"Corridors must be at least 1200 mm wide [{D} § II-2/13.3.1.1]."


def test_short_clause_id_resolved_when_unambiguous():
    res = check_answer("Stairs may not be steeper than 45 degrees [doc § 3.2.1].", RETRIEVED)
    assert res.ok and f"[{D} § II-2/13.3.2.1]" in res.text


def test_violation_messages_are_actionable():
    v = check_answer(f"Corridors must be at least 1.2 m wide [{D} § II-2/13.3.1.1].", RETRIEVED).violations
    assert any("1.2 m" in str(x) for x in v)


# ---------------------------------------------------------------- helpers


def test_extract_numbers_skips_ids():
    assert extract_numbers("see 3.1.1 and Table 13.1 and regulation 9: 1,200 mm, 45 degrees, 3.5 m") == [
        (1200.0, "mm"), (45.0, "deg"), (3.5, "m")
    ]


def test_split_sentences_keeps_decimals_and_abbrev():
    assert len(split_sentences("Rise is 3.5 m max. See Reg. 13 for more.")) == 2


# ---------------------------------------------------------------- full pipeline with a fake LLM


class FakeLLM:
    label = "fake:test"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def complete(self, messages, **kw):
        self.calls += 1
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(scope="module")
def retriever():
    clauses = ingest_file(ROOT / "data" / "rules" / "SAMPLE_SYNTHETIC_rules.md")[1]
    return Retriever(clauses, use_dense=False)


Q = "what does 13.3.1.1 say about corridor width"
GOOD = f"Escape corridors shall be not less than 1200 mm wide [{D} § II-2/13.3.1.1]."
BAD = "Corridors are probably about 1.2 m wide."


def ask(retriever, llm, q=Q):
    return answer_question(q, retriever=retriever, llm=llm, use_cache=False)


def test_pipeline_verified_first_try(retriever):
    a = ask(retriever, FakeLLM([GOOD]))
    assert a.status == "verified" and a.attempts == 1 and a.rejected_attempts == 0
    assert [c.clause_id for c in a.citations] == ["II-2/13.3.1.1"]
    assert a.synthetic


def test_pipeline_retry_then_verified(retriever):
    llm = FakeLLM([BAD, GOOD])
    a = ask(retriever, llm)
    assert a.status == "verified" and a.attempts == 2 and a.rejected_attempts == 1 and llm.calls == 2


def test_pipeline_fails_twice_shows_excerpts(retriever):
    a = ask(retriever, FakeLLM([BAD, BAD]))
    assert a.status == "excerpts" and a.rejected_attempts == 2
    assert "Excerpts" in a.text and "1200 mm" in a.text and BAD not in a.text
    assert a.violations


def test_pipeline_llm_down_shows_excerpts(retriever):
    a = ask(retriever, FakeLLM([LLMError("timeout")]))
    assert a.status == "excerpts" and "LLM unavailable" in a.note


def test_pipeline_model_says_not_found(retriever):
    a = ask(retriever, FakeLLM(["NOT_FOUND"]), "how wide must escape corridors be")
    assert a.status == "not_found" and a.text.startswith("Not found in the provided rules")


def test_pipeline_existing_clause_is_never_not_found(retriever):
    a = ask(retriever, FakeLLM(["NOT_FOUND"]), "Explain regulation II-2/14.2.2")
    assert a.status == "excerpts" and "II-2/14.2.2" in a.text


def test_pipeline_no_retrieval_no_llm_call(retriever):
    llm = FakeLLM([GOOD])
    a = ask(retriever, llm, "what does 99.9.9 say")
    assert a.status == "not_found" and llm.calls == 0
