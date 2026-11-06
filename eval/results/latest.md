## RuleMate evaluation

38 questions (32 answerable incl. 7 clause-ID, 6 unanswerable) · LLM: ollama:llama3.2 · retrieval: hybrid · 2026-11-06 21:20

| Metric | Result |
|---|---|
| Retrieval hit@5 | **100%** (MRR 0.96) |
| Correct "not found" on unanswerable questions | **100%** (6 questions) |
| Answerable questions wrongly refused | 0% |
| Answers verified (all guardrails passed) | **81%** |
| Answers shown as excerpts only | 19% |
| Verified answers containing the key numbers | 78% (23 checked) |
| Citation precision (overlap check) | **93%** (30 citations) |
| LLM drafts rejected by guardrails | 27% of 45 drafts (22% of questions) |
| Drafts that failed a guardrail shown to the user | **0** (by construction) |
| Answer latency p50 / p95 | 3.4 s / 7.3 s |
| Retrieval latency p50 | 10 ms |
| Compliance verdicts correct (research vessel, 46 CFR 190) | **100%** (14 items: 7 PASS, 6 FAIL, 1 REVIEW) |
| Planted defects caught (research vessel, 46 CFR 190) | **100%** of 7 (7 FAIL, 0 REVIEW) |
| False FAIL with the value exactly at the limit (research vessel, 46 CFR 190) | **0%** of 7 |
| Compliance verdicts correct (cruise-ship sample, synthetic rules) | **100%** (15 items: 7 PASS, 6 FAIL, 2 REVIEW) |
| Planted defects caught (cruise-ship sample, synthetic rules) | **100%** of 7 (6 FAIL, 1 REVIEW) |
| False FAIL with the value exactly at the limit (cruise-ship sample, synthetic rules) | **0%** of 7 |

_Caveats: the questions and design values are synthetic and were written by the team (46 CFR 190 is the real regulation text; the cruise-ship rules are synthetic), and thresholds were tuned on them; expect lower numbers on real design data. Planted defects: every passing value moved 3 % past the limit that decided it, and set exactly at that limit._

Threshold calibration (current: low=0.6, high=0.7; answerable = non-ID questions)

| low threshold | unanswerable refused by retrieval | answerable wrongly refused |
|---|---|---|
| 0.55 | 0/6 | 0/25 |
| 0.58 | 0/6 | 0/25 |
| 0.60 | 1/6 | 0/25 |
| 0.62 | 2/6 | 0/25 |
| 0.64 | 2/6 | 0/25 |
| 0.66 | 3/6 | 0/25 |
| 0.68 | 5/6 | 0/25 |
| 0.70 | 6/6 | 0/25 |
