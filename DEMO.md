# RuleMate demo (3 minutes)

Meyer judges three things: **accuracy** (compliant vs non-compliant, no misleading findings), **design
interpretation** (understands the design, shows *why* something fails) and **quality & usability** (a solid
foundation an engineer can use). The demo shows each one, on the vessel type Meyer gave us: a US research vessel,
checked against the real US regulation for it, 46 CFR Part 190.

> Numbers come from `python eval/run.py --provider groq` (gpt-oss-120b, 6 Nov 2026). Design values in the
> research-vessel example are SYNTHETIC placeholders until they are measured on the RCRV drawings; say so.

## Before going on stage

```bash
source .venv/bin/activate
python scripts/fetch_cfr.py                                  # only once: real 46 CFR 190 text into data/rules/
python -m rulemate ingest && python -m rulemate index && python -m rulemate limits --force   # if rules changed
python scripts/warm_demo.py --provider groq,ollama           # caches every demo answer and explanation
uvicorn rulemate.api:app --port 8000                         # terminal 1
streamlit run ui/app.py                                      # terminal 2 -> http://localhost:8501
```

- Groq's free tier is rate-limited: run the warm-up at least a minute before going on stage, and don't run the eval right before.
- Sidebar: provider **groq,ollama**, **Use answer cache** on (same provider as the warm-up, or the cache misses).
- `python scripts/fetch_design_sources.py` once (the NOAA PDF is needed to show the drawing evidence).
- Clear the chat. Open the Compliance tab once so it loads; leave *NOAA research ship* selected.
- No Wi-Fi: set `LLM_PROVIDER=ollama` in `.env` and rerun the warm-up with `--provider ollama`. Everything runs on
  the laptop; that is also the answer to "can it run on our own servers?".
- If an answer comes back as **excerpts only**, that is the safety net working; say so and move on.
- Backup: screenshots of each step in case the laptop or projector fails.

## Script

| Time | Do | Say |
|---|---|---|
| 0:00-0:15 | UI open on *Compliance check* | "You told us: the earlier a compliance defect is found, the cheaper. RuleMate reads the design, checks it against the rules in code, and every finding is traceable to a clause and to the place in the drawing it came from." |
| 0:15-0:55 | **Demo 1, reading a real drawing.** Select *NOAA research ship – read from its GA drawing*, open the *Read from…* box, *Run check*, click any row (e.g. **G02**). | "This is the NOAA research-ship study from your brief: a 1990 scanned GA, no text layer. RuleMate read it with OCR on this laptop: 34 berth labels, 58 berths, each with drawing number and position. Here is the part of the drawing this value came from, boxed. Every room meets 46 CFR 190.20-20(b), at most four persons per room. And it reads across documents: crew 21 and 60 days endurance mean a hospital is required, and there it is on page 42. Mess room seats 32 of 60: that is flagged for review, not guessed. Against our reading by eye: 34 of 34 labels." |
| 0:55-1:35 | **Demo 2, non-compliant design.** Select *Research vessel example – 46 CFR 190*, *Run check*, click **R12**, then **R14**. | "Now a design with planted defects, values in US notation. R12: a 1.0 m bulwark against 39 and a half **inches**: 39.37 inches, **FAIL**, computed by code. R14: two-tier berths, the limit only applies *where two tiers are fitted*: code cannot confirm that, so **NEEDS REVIEW**, never a guess." |
| 1:35-2:00 | **Demo 3, cited answer.** *Ask the rules* tab, sidebar: *How high must guard rails be on a research vessel?* Click the 📄 citation. | "The same rules answer questions. Verified: every sentence cited, and code checked that the cited clause supports it and that every number and unit is in it." |
| 2:00-2:20 | **Demo 4, cross-reference.** Sidebar: *How is the corridor width calculated when many people use it?* Point at Sources. | "Rules point at each other. This clause says *in accordance with 4.2*; RuleMate followed the reference in code, and the answer gives 4.2's actual requirement. (Synthetic cruise-ship sample, marked as such.)" |
| 2:20-2:35 | **Demo 5, refusal.** Sidebar: *What is the required size of a helicopter landing area?* | "Part 190 does not cover helidecks: *Not found in the provided rules*, with the closest clauses. Decided in code before any model was called." |
| 2:35-3:00 | Eval table (slide 5) or `eval/results/latest.md` | "We measure it: 34 of 34 drawing labels read, every planted defect caught, 0 false FAILs at the exact limit, 100 % correct refusals, 91 % of answers verified and the rest shown as excerpts, never unchecked. It runs fully offline, so your designs can stay on your servers." |

Optional if there is time, in a terminal (change impact after a late design change):

```bash
python -m rulemate check new_design.csv --baseline data/designs/rcrv_example_design.csv --rules 46CFR190
```

"After a change, it lists only the items whose verdict changed, new FAILs first: what to recheck."

### If something goes wrong

| Problem | Do |
|---|---|
| Demo 4 answer does not mention 4.2's content | Open the 13.3.1.4 clause dialog and click *Refers to*. The cross-reference is shown by code whatever the model writes. |
| API is down | The UI falls back to in-process calls by itself; carry on. |
| LLM slow or down | Cached answers return instantly; uncached ones show excerpts after the timeout (25 s). Compliance verdicts never need the LLM. |
| A question comes back with cruise-ship clauses | Set *Rule sets for questions* in the sidebar to 46CFR190 (the demo buttons do this). |

---

# Pitch outline (5 slides)

## 1. Problem (in Meyer's words)
- A complex regulatory landscape: SOLAS, MARPOL, class rules (DNV, Lloyd's), flag-state rules, PVAG/ADA; overlapping, cross-referenced, and often vague.
- Checking is manual and needs senior engineers who know the rules and the design.
- Late findings are expensive: a door found in design is an hour; found in production it is a rework job.
- Generic AI is not usable here: it invents clause numbers and values, and you cannot tell when.

## 2. Solution: RuleMate
- **Read the design**: GA drawings read with OCR on the laptop (a real 1990 NOAA GA: 34 of 34 berth labels), report text and particulars sheets; every value keeps its page, drawing number and position, shown boxed next to the verdict.
- **Check the design**: design values (as the drawing writes them, e.g. `2'-6"`, with their source drawing) checked against the rule sets that apply to the vessel; PASS / FAIL / NEEDS REVIEW per item with the clause, the computed comparison and an explanation.
- **Ask the rules**: plain-language questions, answers with exact clause citations, one click to the clause text.
- **After a change**: re-check and list only what changed verdict.
- Works on the real US regulation for Meyer's challenge vessel (46 CFR Part 190, research vessels) plus any PDF/DOCX/HTML/TXT rule set, split by its own numbering.

## 3. How trust is guaranteed
- **Code finds and computes the facts; the LLM only explains them.**
- Limits are extracted into a rule table an engineer can review; each one is validated against the clause text. pint converts units; code compares and decides. Conditions code cannot verify become NEEDS REVIEW, never a guess.
- Every answer is checked after generation: each sentence cited, each cited clause retrieved *and* supporting the sentence, every number and unit present, quotes word for word, no guessing words. Fails twice: clause excerpts, labelled.
- Traceable both ways: the clause that sets the limit and the drawing the value came from.

## 4. Evaluation (Groq gpt-oss-120b; `eval/results/latest.md`)

| Metric (Meyer criterion) | Result |
|---|---|
| GA drawing labels read by OCR, real NOAA drawing (interpretation) | 34 of 34 labels, 58 of 58 berths |
| Planted defects caught (accuracy) | 100 % of 14 across both designs |
| False FAIL with values exactly at the limit (accuracy) | 0 % of 14 |
| Compliance verdicts correct, research vessel / cruise sample | 100 % of 14 / 100 % of 15 |
| Retrieval hit@5 (interpretation) | 100 % (MRR 0.96) |
| Correct "not found" on unanswerable questions | 100 % of 6 |
| Answers verified by every guardrail | 91 % (rest shown as labelled excerpts; 81 % with the offline 3B model) |
| Citation precision (each citation supports its sentence) | 93 % |
| Verified answers containing the key numbers | 89 % |
| Drafts that failed a guardrail shown to the user | 0 (by construction) |

38 questions (8 on the real 46 CFR 190 text). Caveat to say out loud: the questions and design values were written by the team; real design data will score lower and we will show those numbers too.

## 5. Next steps for Meyer
- Read more from drawings: room areas, corridor and stair widths from vector GAs with a known scale; the RCRV GA and 3D model (Navisworks export of spaces and properties).
- More rule sets per vessel type: SOLAS, DNV class rules, PVAG/ADA, plus interpretations (IACS unified interpretations) that say how a vague rule is applied.
- Change impact in the design tool: "you added a cabin: these items must be rechecked".
- Engineer sign-off: reviewed rule table, accepted review items, an audit trail of which clause version a decision used; role-based access.
- Runs fully on-premises or in an EU data centre with a local model (the offline path already works on a 32 GB laptop).
