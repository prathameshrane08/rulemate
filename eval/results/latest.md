## RuleMate evaluation

38 questions (32 answerable incl. 7 clause-ID, 6 unanswerable) · LLM: none · retrieval: hybrid · 2026-11-07 17:49

| Metric | Result |
|---|---|
| Retrieval hit@5 | **100%** (MRR 0.92) |
| Retrieval latency p50 | 11 ms |
| Compliance verdicts correct (research vessel, 46 CFR 190) | **100%** (14 items: 7 PASS, 6 FAIL, 1 REVIEW) |
| Planted defects caught (research vessel, 46 CFR 190) | **100%** of 7 (7 FAIL, 0 REVIEW) |
| False FAIL with the value exactly at the limit (research vessel, 46 CFR 190) | **0%** of 7 |
| Compliance verdicts correct (accessible stateroom, ADA 36 CFR 1191) | **100%** (9 items: 5 PASS, 4 FAIL, 0 REVIEW) |
| Planted defects caught (accessible stateroom, ADA 36 CFR 1191) | **100%** of 5 (5 FAIL, 0 REVIEW) |
| False FAIL with the value exactly at the limit (accessible stateroom, ADA 36 CFR 1191) | **0%** of 5 |
| Compliance verdicts correct (cruise-ship sample, synthetic rules) | **100%** (15 items: 7 PASS, 6 FAIL, 2 REVIEW) |
| Planted defects caught (cruise-ship sample, synthetic rules) | **100%** of 7 (6 FAIL, 1 REVIEW) |
| False FAIL with the value exactly at the limit (cruise-ship sample, synthetic rules) | **0%** of 7 |
| GA drawing read by OCR (NOAA, second deck): berth labels found | **34 of 34**, 58 of 58 berths, role text exact for 32 |
| Same NOAA drawing read by Gemini (gemini-3.5-flash), readings confirmed in code | **33 of 34** role and berth count exact, 34 of 34 confirmed on the sheet (`eval/gemini_drawing.py`, 2026-11-07 13:37) |
| RCRV GA (vector), stair flights measured on the inboard profile | **3 of 3**, angle 50 deg, room number read for 3 |

_Caveats: the questions and the example design values were written by the team, and thresholds were tuned on them; 46 CFR 190 and the NOAA GA drawing are real documents, the cruise-ship rules are synthetic. Expect lower numbers on other real design data. Planted defects: every passing value moved 3 % past the limit that decided it, and set exactly at that limit._

Threshold calibration (current: low=0.6, high=0.7; answerable = non-ID questions)

| low threshold | unanswerable refused by retrieval | answerable wrongly refused |
|---|---|---|
| 0.55 | 0/6 | 0/25 |
| 0.58 | 0/6 | 0/25 |
| 0.60 | 0/6 | 0/25 |
| 0.62 | 0/6 | 0/25 |
| 0.64 | 1/6 | 0/25 |
| 0.66 | 2/6 | 0/25 |
| 0.68 | 3/6 | 0/25 |
| 0.70 | 5/6 | 0/25 |
