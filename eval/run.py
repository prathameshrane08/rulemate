"""RuleMate evaluation.

    python eval/run.py                      # full run with the configured LLM (no answer cache)
    python eval/run.py --provider ollama    # pick the LLM
    python eval/run.py --retrieval-only     # fast: retrieval metrics + threshold calibration, no LLM

Metrics
- retrieval hit@5     answerable + clause-ID questions: an expected clause is among the first 5 retrieved
                      (ID matches, their sub-clauses, then search hits; cross-references excluded)
- MRR                 mean reciprocal rank of the first expected clause
- verified / excerpts / not found   how answers ended
- fact recall         verified answers that contain every key number of the question
- citation precision  (sentence, cited clause) pairs where the clause supports the sentence:
                      >= 50% of the sentence's content words, and all its numbers, appear in the clause
- guardrail rejections  share of LLM drafts rejected by the guardrails; questions with >= 1 rejection
- correct "not found" on unanswerable questions; false "not found" on answerable ones
- latency p50 / p95   end-to-end answer time (retrieval + LLM + checks), cache off
- compliance accuracy  verdicts on the sample design vs. eval/compliance_expected.json

Results: printed as Markdown and written to eval/results/<timestamp>.json and eval/results/latest.md
"""

from __future__ import annotations

import argparse
import re
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rulemate.answer import answer_question  # noqa: E402
from rulemate.guardrails import _PH_RE, _PLACEHOLDER, CITATION_RE, extract_numbers, split_sentences  # noqa: E402
from rulemate.llm import get_llm  # noqa: E402
from rulemate.retrieval import HIGH_SCORE, LOW_SCORE, get_retriever, tokenize  # noqa: E402

EVAL_DIR = ROOT / "eval"
RESULTS_DIR = EVAL_DIR / "results"


def load_questions(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


# ------------------------------------------------------------------ retrieval


def ranked_ids(res) -> list[str]:
    return [h.clause.clause_id for h in res.hits if h.source != "xref"]


def retrieval_metrics(questions: list[dict], retriever) -> tuple[dict, list[dict]]:
    rows = []
    for q in questions:
        t = time.perf_counter()
        res = retriever.search(q["question"])
        ms = (time.perf_counter() - t) * 1000
        ids = ranked_ids(res)
        rank = next((i + 1 for i, cid in enumerate(ids) if cid in q["expected"]), None)
        rows.append({"id": q["id"], "type": q["type"], "top_score": res.top_score, "confidence": res.confidence,
                     "rank": rank, "hit5": rank is not None and rank <= 5, "ms": ms,
                     "xref_ids": [h.clause.clause_id for h in res.hits if h.source == "xref"]})
    answerable = [r for r in rows if r["type"] != "unanswerable"]
    m = {
        "hit@5": sum(r["hit5"] for r in answerable) / len(answerable),
        "mrr": sum(1 / r["rank"] for r in answerable if r["rank"]) / len(answerable),
        "retrieval_p50_ms": percentile([r["ms"] for r in rows], 0.5),
        "n_answerable": len(answerable),
    }
    return m, rows


def calibrate(rows: list[dict]) -> list[dict]:
    """How many unanswerable questions each LOW threshold would refuse, vs. answerable ones wrongly refused.
    Clause-ID questions are excluded: an exact ID match is always 'high'."""
    ans = [r["top_score"] for r in rows if r["type"] == "answerable"]
    una = [r["top_score"] for r in rows if r["type"] == "unanswerable"]
    out = []
    for t in [0.55, 0.58, 0.60, 0.62, 0.64, 0.66, 0.68, 0.70]:
        out.append({"low": t, "unanswerable_refused": sum(s < t for s in una), "n_unanswerable": len(una),
                    "answerable_refused": sum(s < t for s in ans), "n_answerable": len(ans)})
    return out


# ------------------------------------------------------------------ answers


def supports(sentence: str, clause_text: str) -> bool:
    words = {w for w in tokenize(sentence) if not w.replace(".", "").isdigit()}
    cw = set(tokenize(clause_text))
    overlap = len(words & cw) / max(1, len(words))
    nums_ok = {v for v, _ in extract_numbers(sentence)} <= {v for v, _ in extract_numbers(clause_text)}
    return overlap >= 0.5 and nums_ok


def citation_pairs(answer) -> list[bool]:
    """Pair every citation with the sentence it belongs to (same splitting as the guardrails, so a citation
    placed after the full stop counts for the sentence before it)."""
    by_id = {c.clause_id: c for c in (h.clause for h in answer.sources)}
    found: list[str] = []

    def ph(m):
        found.append(m.group(2).strip())
        return _PLACEHOLDER.format(len(found) - 1)

    body = CITATION_RE.sub(ph, answer.text)
    pairs = []
    for sent in split_sentences(body):
        cites = [found[int(i)] for i in _PH_RE.findall(sent)]
        plain = _PH_RE.sub("", sent)
        for cid in cites:
            c = by_id.get(cid)
            pairs.append(bool(c) and supports(plain, c.text))
    return pairs


_NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"]


def answer_metrics(questions: list[dict], retriever, llm) -> tuple[dict, list[dict]]:
    rows = []
    for i, q in enumerate(questions, 1):
        a = answer_question(q["question"], retriever=retriever, llm=llm, use_cache=False)
        pairs = citation_pairs(a) if a.status == "verified" else []
        facts_ok = None
        if a.status == "verified" and q.get("facts"):
            plain = CITATION_RE.sub("", a.text)
            nums = {v for v, _ in extract_numbers(plain)} | {
                float(n) for n, w in enumerate(_NUMBER_WORDS) if re.search(rf"\b{w}\b", plain, re.I)}  # "four" = 4
            facts_ok = all(float(f) in nums for f in q["facts"])
        cited = [c.clause_id for c in a.citations]
        rows.append({
            "id": q["id"], "type": q["type"], "question": q["question"], "status": a.status,
            "attempts": a.attempts, "rejected": a.rejected_attempts, "latency_ms": a.latency_ms,
            "cited": cited, "expected": q["expected"], "supported_pairs": sum(pairs), "pairs": len(pairs),
            "facts_ok": facts_ok, "answer": a.text, "violations": a.violations, "confidence": a.confidence,
            "used_llm": a.attempts > 0,
        })
        print(f"  [{i:2}/{len(questions)}] {q['id']} {a.status:9} rej={a.rejected_attempts} "
              f"{a.latency_ms / 1000:5.1f}s  {q['question'][:60]}", flush=True)

    answerable = [r for r in rows if r["type"] != "unanswerable"]
    unanswerable = [r for r in rows if r["type"] == "unanswerable"]
    verified = [r for r in answerable if r["status"] == "verified"]
    with_facts = [r for r in verified if r["facts_ok"] is not None]
    drafts = sum(r["attempts"] for r in rows)
    llm_rows = [r for r in rows if r["used_llm"]]
    lat = [r["latency_ms"] for r in rows]
    m = {
        "verified": len(verified) / len(answerable),
        "excerpts": sum(r["status"] == "excerpts" for r in answerable) / len(answerable),
        "false_not_found": sum(r["status"] == "not_found" for r in answerable) / len(answerable),
        "fact_recall": (sum(r["facts_ok"] for r in with_facts) / len(with_facts)) if with_facts else None,
        "n_fact_checked": len(with_facts),
        "citation_precision": (sum(r["supported_pairs"] for r in rows) / max(1, sum(r["pairs"] for r in rows))),
        "n_citation_pairs": sum(r["pairs"] for r in rows),
        "draft_rejection_rate": sum(r["rejected"] for r in rows) / max(1, drafts),
        "n_drafts": drafts,
        "questions_with_rejection": sum(r["rejected"] > 0 for r in llm_rows) / max(1, len(llm_rows)),
        "correct_not_found": sum(r["status"] == "not_found" for r in unanswerable) / max(1, len(unanswerable)),
        "n_unanswerable": len(unanswerable),
        "latency_p50_s": percentile(lat, 0.5) / 1000,
        "latency_p95_s": percentile(lat, 0.95) / 1000,
    }
    return m, rows


# ------------------------------------------------------------------ compliance


# (label, design CSV, expected verdicts, rule documents that apply to that vessel)
DESIGN_SETS = [
    ("research vessel, 46 CFR 190", "rcrv_example_design.csv", "rcrv_expected.json", ["46CFR190"]),
    ("accessible stateroom, ADA 36 CFR 1191", "accessible_stateroom_example.csv", "accessible_expected.json",
     ["36CFR1191AppD"]),
    ("cruise-ship sample, synthetic rules", "sample_design.csv", "compliance_expected.json", ["SAMPLE_SYNTHETIC_rules"]),
]


def compliance_metrics() -> list[dict]:
    from rulemate.compliance.check import read_design_csv
    from rulemate.compliance.service import check_rows, rule_documents
    from seeded import seeded_metrics

    out = []
    have = set(rule_documents())
    for label, csv_name, exp_name, docs in DESIGN_SETS:
        csv_file, exp_file = ROOT / "data" / "designs" / csv_name, EVAL_DIR / exp_name
        if not csv_file.exists() or not exp_file.exists() or not set(docs) <= have:
            continue
        expected = json.loads(exp_file.read_text())
        rows = read_design_csv(csv_file.read_bytes())
        got = {r.row.item_id: r.verdict for r in check_rows(rows, docs=docs)}
        correct = [k for k, v in expected.items() if got.get(k) == v]
        out.append({
            "label": label, "accuracy": len(correct) / len(expected), "n": len(expected),
            "wrong": {k: {"expected": v, "got": got.get(k)} for k, v in expected.items() if got.get(k) != v},
            "counts": {v: sum(x == v for x in got.values()) for v in ("PASS", "FAIL", "NEEDS REVIEW")},
            "seeded": seeded_metrics(rows, docs),
        })
    return out


# ------------------------------------------------------------------ design interpretation


def drawing_metrics() -> dict | None:
    """OCR of a real GA drawing against labels read by eye (eval/noaa_ga_truth.json)."""
    from collections import Counter

    truth_file = EVAL_DIR / "noaa_ga_truth.json"
    if not truth_file.exists():
        return None
    truth = json.loads(truth_file.read_text())
    pdf = ROOT / truth["source_file"]
    if not pdf.exists():
        return None
    from rulemate.design.extract import ocr_page, room_labels

    got = room_labels(ocr_page(pdf, truth["page"]))
    t = Counter((r.upper(), n) for r, n in truth["labels"])
    g = Counter((l.roles[0], l.counts[0]) for l in got)
    exact = sum((t & g).values())
    counts_ok = sum((Counter(n for _, n in truth["labels"]) & Counter(l.counts[0] for l in got)).values())
    stairs = None
    st_file = EVAL_DIR / "rcrv_ga_truth.json"
    if st_file.exists():
        st = json.loads(st_file.read_text())
        st_pdf = ROOT / st["source_file"]
        if st_pdf.exists():
            from rulemate.design.measure import stair_flights

            fl = stair_flights(st_pdf, st["page"], ocr_page(st_pdf, st["page"], 300))
            stairs = {"n": len(st["stairs"]), "found": len(fl), "numbered": sum(f.room_no in st["stairs"] for f in fl),
                      "angles": sorted({f.angle for f in fl})}
    return {"stairs": stairs, "n": len(truth["labels"]), "found": len(got), "exact": exact, "counts_ok": counts_ok,
            "berths_truth": sum(n for _, n in truth["labels"]), "berths_read": sum(l.persons for l in got),
            "uncounted_flagged": sorted({w.text for w in room_labels.unlabelled}) == sorted(truth["roles_without_count"])}


# ------------------------------------------------------------------ report


def report(rm: dict, am: dict | None, cm: dict | None, calib: list[dict], meta: dict, dm: dict | None = None) -> str:
    L = ["## RuleMate evaluation", ""]
    L.append(f"{meta['n_questions']} questions ({meta['n_answerable']} answerable incl. {meta['n_clause_id']} clause-ID, "
             f"{meta['n_unanswerable']} unanswerable) · LLM: {meta['llm']} · retrieval: {meta['retrieval']} · {meta['when']}")
    L.append("")
    L.append("| Metric | Result |")
    L.append("|---|---|")
    L.append(f"| Retrieval hit@5 | **{pct(rm['hit@5'])}** (MRR {rm['mrr']:.2f}) |")
    if am:
        L.append(f"| Correct \"not found\" on unanswerable questions | **{pct(am['correct_not_found'])}** ({am['n_unanswerable']} questions) |")
        L.append(f"| Answerable questions wrongly refused | {pct(am['false_not_found'])} |")
        L.append(f"| Answers verified (all guardrails passed) | **{pct(am['verified'])}** |")
        L.append(f"| Answers shown as excerpts only | {pct(am['excerpts'])} |")
        if am["fact_recall"] is not None:
            L.append(f"| Verified answers containing the key numbers | {pct(am['fact_recall'])} ({am['n_fact_checked']} checked) |")
        L.append(f"| Citation precision (overlap check) | **{pct(am['citation_precision'])}** ({am['n_citation_pairs']} citations) |")
        L.append(f"| LLM drafts rejected by guardrails | {pct(am['draft_rejection_rate'])} of {am['n_drafts']} drafts "
                 f"({pct(am['questions_with_rejection'])} of questions) |")
        L.append("| Drafts that failed a guardrail shown to the user | **0** (by construction) |")
        L.append(f"| Answer latency p50 / p95 | {am['latency_p50_s']:.1f} s / {am['latency_p95_s']:.1f} s |")
    L.append(f"| Retrieval latency p50 | {rm['retrieval_p50_ms']:.0f} ms |")
    for c in cm or []:
        L.append(f"| Compliance verdicts correct ({c['label']}) | **{pct(c['accuracy'])}** ({c['n']} items: "
                 f"{c['counts']['PASS']} PASS, {c['counts']['FAIL']} FAIL, {c['counts']['NEEDS REVIEW']} REVIEW) |")
        sd = c["seeded"]
        if sd.get("n_violating"):
            L.append(f"| Planted defects caught ({c['label']}) | **{pct(sd['caught'])}** of {sd['n_violating']} "
                     f"({sd['violating_fail']} FAIL, {sd['violating_review']} REVIEW) |")
            L.append(f"| False FAIL with the value exactly at the limit ({c['label']}) | **{pct(sd['false_fail_at_limit'])}** "
                     f"of {sd['n_at_limit']} |")
    if dm:
        L.append(f"| GA drawing read by OCR (NOAA, second deck): berth labels found | **{dm['found']} of {dm['n']}**, "
                 f"{dm['berths_read']} of {dm['berths_truth']} berths, role text exact for {dm['exact']} |")
        gf = RESULTS_DIR / "gemini_drawing.json"
        if gf.exists():
            g = json.loads(gf.read_text())
            L.append(f"| Same NOAA drawing read by Gemini ({g['model']}), readings confirmed in code | **{g['correct']} of "
                     f"{g['n_truth']}** role and berth count exact, {g['confirmed']} of {g['readings']} confirmed on the "
                     f"sheet (`eval/gemini_drawing.py`, {g['when']}) |")
        if dm.get("stairs"):
            st = dm["stairs"]
            L.append(f"| RCRV GA (vector), stair flights measured on the inboard profile | **{st['found']} of {st['n']}**, "
                     f"angle {', '.join(f'{a:g}' for a in st['angles'])} deg, room number read for {st['numbered']} |")
    L.append("")
    L.append("_Caveats: the questions and the example design values were written by the team, and thresholds were tuned "
             "on them; 46 CFR 190 and the NOAA GA drawing are real documents, the cruise-ship rules are synthetic. Expect "
             "lower numbers on other real design data. Planted defects: every passing value moved 3 % past the limit that decided it, and "
             "set exactly at that limit._")
    L.append("")
    L.append(f"Threshold calibration (current: low={LOW_SCORE}, high={HIGH_SCORE}; answerable = non-ID questions)")
    L.append("")
    L.append("| low threshold | unanswerable refused by retrieval | answerable wrongly refused |")
    L.append("|---|---|---|")
    for c in calib:
        L.append(f"| {c['low']:.2f} | {c['unanswerable_refused']}/{c['n_unanswerable']} | {c['answerable_refused']}/{c['n_answerable']} |")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=str(EVAL_DIR / "questions.jsonl"))
    ap.add_argument("--provider", help="LLM provider(s), e.g. groq | ollama | groq,ollama")
    ap.add_argument("--retrieval-only", action="store_true")
    args = ap.parse_args()

    questions = load_questions(Path(args.questions))
    retriever = get_retriever()
    retriever.search("warm up")
    print(f"Retrieval ({retriever.mode}) on {len(questions)} questions...")
    rm, rrows = retrieval_metrics(questions, retriever)
    calib = calibrate(rrows)

    am, arows, llm_label = None, [], "none"
    if not args.retrieval_only:
        llm = get_llm(args.provider)
        llm_label = llm.label
        print(f"Answers with {llm_label} (cache off)...")
        am, arows = answer_metrics(questions, retriever, llm)
        llm_label = llm.label

    cm = compliance_metrics()
    meta = {
        "n_questions": len(questions),
        "n_answerable": sum(q["type"] != "unanswerable" for q in questions),
        "n_clause_id": sum(q["type"] == "clause_id" for q in questions),
        "n_unanswerable": sum(q["type"] == "unanswerable" for q in questions),
        "llm": llm_label,
        "retrieval": retriever.mode,
        "when": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    dm = drawing_metrics()
    md = report(rm, am, cm, calib, meta, dm)
    print("\n" + md)

    misses = [r for r in rrows if r["type"] != "unanswerable" and not r["hit5"]]
    if misses:
        print("\nRetrieval misses:", ", ".join(f"{r['id']} (rank {r['rank']})" for r in misses))
    for c in cm or []:
        if c["wrong"]:
            print(f"Compliance mismatches ({c['label']}):", c["wrong"])
        for w in c["seeded"].get("wrong", []):
            print(f"Planted-defect miss ({c['label']}):", w)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (RESULTS_DIR / f"{stamp}.json").write_text(json.dumps(
        {"meta": meta, "retrieval": rm, "answers": am, "compliance": cm, "drawing": dm, "calibration": calib,
         "retrieval_rows": rrows, "answer_rows": arows}, indent=1, default=str))
    (RESULTS_DIR / "latest.md").write_text(md + "\n")
    print(f"\nSaved eval/results/{stamp}.json and eval/results/latest.md")


if __name__ == "__main__":
    main()
