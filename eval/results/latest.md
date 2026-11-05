## RuleMate evaluation

30 questions (25 answerable incl. 5 clause-ID, 5 unanswerable) · LLM: ollama:llama3.2 · retrieval: hybrid · 2026-11-05 20:14

| Metric | Result |
|---|---|
| Retrieval hit@5 | **100%** (MRR 0.97) |
| Correct "not found" on unanswerable questions | **100%** (5 questions) |
| Answerable questions wrongly refused | 0% |
| Answers verified (all guardrails passed) | **92%** |
| Answers shown as excerpts only | 8% |
| Verified answers containing the key numbers | 90% (21 checked) |
| Citation precision (overlap check) | **100%** (26 citations) |
| LLM drafts rejected by guardrails | 10% of 29 drafts (7% of questions) |
| Drafts that failed a guardrail shown to the user | **0** (by construction) |
| Answer latency p50 / p95 | 1.2 s / 2.4 s |
| Retrieval latency p50 | 6 ms |
| Compliance verdicts correct (sample design) | **100%** (15 items: 7 PASS, 6 FAIL, 2 REVIEW) |

_Caveats: the rules, questions and design values are synthetic and were written by the team, and thresholds were tuned on them; expect lower numbers on the real documents._

Threshold calibration (current: low=0.6, high=0.7; answerable = non-ID questions)

| low threshold | unanswerable refused by retrieval | answerable wrongly refused |
|---|---|---|
| 0.55 | 0/5 | 0/20 |
| 0.58 | 1/5 | 0/20 |
| 0.60 | 3/5 | 0/20 |
| 0.62 | 3/5 | 0/20 |
| 0.64 | 4/5 | 0/20 |
| 0.66 | 4/5 | 0/20 |
| 0.68 | 5/5 | 0/20 |
| 0.70 | 5/5 | 0/20 |
