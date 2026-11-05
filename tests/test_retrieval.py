import pytest

from rulemate.config import ROOT
from rulemate.ingest.pipeline import ingest_file
from rulemate.retrieval import Retriever, extract_clause_ids, tokenize

SAMPLE = ROOT / "data" / "rules" / "SAMPLE_SYNTHETIC_rules.md"


@pytest.fixture(scope="module")
def clauses():
    return ingest_file(SAMPLE)[1]


@pytest.fixture(scope="module")
def bm25(clauses):
    return Retriever(clauses, use_dense=False)


def ids(res, source=None):
    return [h.clause.clause_id for h in res.hits if source is None or h.source == source]


def test_extract_clause_ids():
    assert extract_clause_ids("what does 13.3.1 say") == ["13.3.1"]
    assert extract_clause_ids("Reg. II-2/9.3.3 please") == ["II-2/9.3.3"]
    assert extract_clause_ids("see Pt.3 Ch.2 Sec.4 [2.1.3]") == ["Pt.3 Ch.2 Sec.4 [2.1.3]"]
    assert extract_clause_ids("explain Table 13.1") == ["Table 13.1"]
    # values with units are not clause IDs
    assert extract_clause_ids("is a 3.5 m rise ok with 1.2 mm plate") == []


def test_tokenize_plurals_and_ids():
    assert tokenize("Corridors and stairways") == ["corridor", "stairway"]
    assert "ii-2/13.3.1" in tokenize("Reg II-2/13.3.1")


def test_id_lookup_expands_heading_children_without_search(bm25):
    res = bm25.search("what does 13.3.1 say")
    assert ids(res, "id") == ["II-2/13.3.1"]
    assert ids(res, "child")[:4] == ["II-2/13.3.1.1", "II-2/13.3.1.2", "II-2/13.3.1.3", "II-2/13.3.1.4"]
    assert ids(res, "search") == []  # pure ID question: no fuzzy search noise
    assert res.found


def test_cross_reference_followed(bm25):
    res = bm25.search("what does 13.3.1.4 say")
    xref = ids(res, "xref")
    assert "II-2/13.4.2" in xref and "II-2/13.4.2.1" in xref  # "see 4.2" pulls in 4.2 and its children
    via = {h.clause.clause_id: h.via for h in res.hits if h.source == "xref"}
    assert via["II-2/13.4.2"] == "II-2/13.3.1.4"


def test_bm25_ranking(bm25):
    assert ids(bm25.search("fire door rating stairway enclosure"), "search")[0] == "II-2/9.3.2"
    assert ids(bm25.search("dead-end corridor length"), "search")[0] == "II-2/13.3.1.3"


def test_unknown_id_not_found(bm25):
    res = bm25.search("what does 99.9.9 say")
    assert not res.found and res.hits == []


def test_xref_disabled(bm25):
    assert ids(bm25.search("what does 13.3.1.4 say", follow_refs=False), "xref") == []


@pytest.fixture(scope="module")
def hybrid(clauses):
    r = Retriever(clauses, use_dense=True)
    if r.mode != "hybrid":
        pytest.skip("embedding model not available")
    return r


@pytest.mark.parametrize(
    "q,expected",
    [
        ("What is the minimum corridor width?", "II-2/13.3.1.1"),
        ("maximum stair angle", "II-2/13.3.2.1"),
        ("how far may a passenger walk from a cabin to the stairs", "II-2/13.3.3.1"),
        ("fire door rating for stairway enclosures", "II-2/9.3.2"),
    ],
)
def test_hybrid_hit_at_5(hybrid, q, expected):
    res = hybrid.search(q)
    assert res.found
    assert expected in ids(res, "search")[:5]


def test_hybrid_confidence_bands(hybrid):
    assert hybrid.search("What is the minimum corridor width?").confidence == "high"
    assert hybrid.search("can the travel distance be longer through a big atrium").confidence == "low"
    assert hybrid.search("What is the maximum noise level in cabins?").confidence != "high"
    off_topic = hybrid.search("helicopter landing area size")
    assert off_topic.confidence == "none" and not off_topic.found
