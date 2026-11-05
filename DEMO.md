# RuleMate demo (3 minutes)

> Numbers marked **[update]** come from the run with local llama3.2 on the synthetic sample. Rerun
> `python eval/run.py --provider groq` (and again on the real Meyer documents) and copy in the new numbers.

## Before going on stage

```bash
source .venv/bin/activate
python -m rulemate ingest && python -m rulemate index     # only if the rule files changed
python scripts/warm_demo.py --provider groq,ollama         # caches every demo answer and explanation
uvicorn rulemate.api:app --port 8000                       # terminal 1
streamlit run ui/app.py                                    # terminal 2 -> http://localhost:8501
```

- In the sidebar: provider **groq,ollama**, **Use answer cache** on (same provider as the warm-up, or the cache misses).
- Clear the chat. Open the Compliance tab once so it loads.
- No Wi-Fi: set `LLM_PROVIDER=ollama` in `.env` and rerun the warm-up with `--provider ollama`.
- If an answer comes back as **excerpts only**, that is the safety net working; say so and move on.
- Backup: screenshots of each step in case the laptop or projector fails.
- If the demo still runs on the synthetic sample, say so in the first sentence. The UI shows the banner anyway.

## Script

| Time | Do | Say |
|---|---|---|
| 0:00-0:20 | UI open on *Ask the rules* | "Ship designers at Meyer check every space against thousands of pages of rules. A normal chatbot will happily invent a clause number. RuleMate has one rule: every answer is traceable to a clause, or it says *not found in the rules*." |
| 0:20-0:55 | **Demo 1, cited answer.** Sidebar: *What is the minimum corridor width?* Click the 📄 citation. | "Green badge: verified. Every sentence carries a clause citation, and code checked each one after the model wrote it: the cited clause was retrieved, every number and unit is in that clause, no guessing words. Click the citation: here is the exact clause, page 3, with its place in the document." |
| 0:55-1:30 | **Demo 2, cross-reference.** Sidebar: *How is the corridor width calculated when many people use it?* Point at the Sources panel, then open 13.3.1.4 and click *Refers to: II-2/13.4.2*. | "Clause 13.3.1.4 only says *calculated in accordance with 4.2*. RuleMate followed that reference in code; you can see it in Sources: *xref ← 13.3.1.4*. So the answer includes the 10 mm per person rule from 4.2, and both clauses are cited." (Groq; the small local model often stops at "in accordance with 4.2": then use the clause dialog, see below.) |
| 1:30-1:55 | **Demo 3, refusal.** Sidebar: *What is the required size of a helicopter landing area?* | "Our rules don't cover helidecks. Instead of guessing, RuleMate says *Not found in the provided rules* and shows the closest clauses so you can check for yourself. That decision was made in code, from the retrieval score, before any model was called." |
| 1:55-2:40 | **Demo 4, compliance FAIL.** Compliance tab, *Run check*. Click row **D02**, then **D03**. | "Fifteen design values from a CSV. D02: a passenger corridor of 1.1 metres. Code converted it to 1100 mm, compared it with the 1200 mm minimum in 13.3.1.1: **FAIL**. The model did not decide this; it only explains it, and its explanation is checked as well. D03 is a crew corridor of 950 mm: it passes only under the crew relaxation, *if it serves no more than 50 persons*. Code cannot verify that, so it says **NEEDS REVIEW** instead of guessing." |
| 2:40-3:00 | Show the eval table (slide 4) or `eval/results/latest.md` | "We measure it: 100% retrieval hit@5, 100% correct refusals, 0 unchecked drafts shown **[update]**. And when the real Meyer documents arrive, you drop them in a folder and rerun one command." |

### If something goes wrong

| Problem | Do |
|---|---|
| Demo 2 answer does not mention 4.2's content | Open the 13.3.1.4 clause dialog and click *Refers to*. The cross-reference is shown by code whatever the model writes. |
| API is down | The UI falls back to in-process calls by itself; carry on. |
| LLM slow or down | Cached answers return instantly; uncached ones show excerpts after the timeout (25 s). |

---

# Pitch outline (5 slides)

## 1. Problem
- Designing a cruise ship means meeting SOLAS, class rules, flag-state rules and owner specifications: thousands of pages that refer to each other ("see 4.2", "Table 13.1").
- Designers lose hours looking up and cross-checking clauses; a missed relaxation or a wrong unit shows up late, where it is expensive.
- Generic AI assistants are not usable here: they make up clause numbers and values, and you cannot tell when.

## 2. Solution: RuleMate
- **Ask the rules**: plain-language questions, answers with exact clause citations, one click to the clause text and page.
- **Check the design**: upload design values (CSV), get PASS / FAIL / NEEDS REVIEW per item with the clause and the computed comparison.
- How it works: rules are split by their own numbering (Reg. II-2/13.3.1.1, Pt.3 Ch.2 Sec.4 [2.1.3]) and tables are kept whole → hybrid search (BM25 + embeddings) + exact clause-ID lookup + cross-references followed → the LLM writes the text → code checks it.
- Runs on Groq, any OpenAI-compatible endpoint, or fully offline with Ollama.

## 3. How trust is guaranteed
- **Code finds and computes the facts; the LLM only explains them.**
- Every answer is checked after generation, in code: each sentence cited, each cited clause actually retrieved, every number and unit present in the cited clause, quotes word for word, no guessing words. Fails twice → the user sees the clause excerpts, labelled as excerpts.
- "Not found in the provided rules" when nothing relevant is retrieved, and a named clause is never answered "not found".
- Compliance: limits extracted to a rule table and validated against the clause text; pint converts units; **code decides the verdict**; an explanation that contradicts the computed result, or states an unchecked condition as fact, is rejected.
- Every answer carries a badge: *verified*, *excerpts only* or *not found*. The rule table can be reviewed and edited by an engineer.

## 4. Evaluation **[update with Groq + real documents]**

| Metric | Result |
|---|---|
| Retrieval hit@5 | 100% (MRR 0.97) |
| Correct "not found" on unanswerable questions | 100% (5) |
| Answerable questions wrongly refused | 0% |
| Answers verified by all guardrails | 96% |
| Citation precision | 100% |
| Drafts that failed a guardrail shown to the user | 0 (by construction) |
| Answer latency p50 / p95 | 1.8 s / 2.8 s (local llama3.2 on a laptop) |
| Compliance verdicts correct (15 items) | 100% |

30 questions: 20 answerable, 5 asking for a specific clause, 5 unanswerable. Caveat to say out loud: synthetic sample written by the team; real documents will score lower, and we will show those numbers too.

## 5. Next steps for Meyer
- Load Meyer's real rule set: SOLAS, class rules, flag-state requirements, owner specifications. Check the parsers on each numbering style and rerun the eval with Meyer's own questions.
- Read design values straight from the design tools (space and parameter exports) instead of CSV.
- Engineer sign-off: reviewed rule table, accepted NEEDS REVIEW items and an audit trail of which clause version a decision used.
- Track rule changes: when a new edition arrives, list the design items whose limits changed.
- Run on-premises with a local model for confidential design data (the Ollama path already works).
