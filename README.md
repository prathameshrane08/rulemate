# RuleMate

Answers questions about ship design rules with exact clause citations, and checks design values against rule limits.
Every answer is traceable to a clause, or it says "not found in the rules".

Rule documents loaded today:

| Document | What it is | Used with |
|---|---|---|
| `46CFR190` | **Real regulation text**: US 46 CFR Part 190, construction and arrangement of oceanographic research vessels (means of escape, accommodation, rails), fetched from eCFR with `scripts/fetch_cfr.py`. Public domain. | the research-vessel example design (Meyer's challenge vessel, the OSU Regional Class Research Vessel, is a US research vessel) |
| `SAMPLE_SYNTHETIC_rules` | **Invented** SOLAS-style cruise-ship rules for development, labelled synthetic everywhere | the cruise-ship sample design |

Each check and each question can be scoped to the rule sets that apply to the vessel (`--rules`, or the selector in
the UI), so a research-vessel stairway is never judged by cruise-ship rules.

## Setup (3 commands)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && cp .env.example .env   # then add your API key to .env
python -m rulemate ingest
```

## Ingestion

`python -m rulemate ingest` reads every PDF, DOCX, HTML, TXT and MD file in `data/rules/` and splits it by the
document's own numbering into clauses (`data/index/clauses.json`). Each clause keeps document, clause ID, title,
page, text, parent, breadcrumb path and resolved cross-references. Tables are kept whole as one clause.

| Style | Recognised headings | Example clause ID |
|---|---|---|
| `solas` | `Chapter II-2`, `Regulation 13`, `3.1.1 ...` | `II-2/13.3.1.1` |
| `class` | `Pt.3 Ch.2`, `Section 4`, `[2.1.3] ...` | `Pt.3 Ch.2 Sec.4 [2.1.3]` |
| `cfr` | `Subpart 190.10`, `§ 190.10-25`, `(b) ...` | `190.10-25(b)` |
| `decimal` | `4.2.1 ...` | `4.2.1` |
| `fallback` | headings only | `S3`, `S3.1` |

The style is detected per document; force one with `data/rules/styles.json`, e.g. `{"my_rules_file": "class"}`.

```bash
python -m rulemate list                 # every parsed clause
python -m rulemate show "Reg. II-2/13.3.2.1"
python -m rulemate show 13.3.1.4        # suffix match, shows cross-refs
pytest -q
```

## Retrieval

`python -m rulemate search "<question>"` runs, in order:

1. **Clause-ID lookup**: IDs in the question ("13.3.1", "Reg. II-2/9.3.3", "[2.1.3]", "Table 13.1") are looked up
   directly. A heading brings its sub-clauses with it. A question that is only an ID skips fuzzy search.
2. **Hybrid search**: BM25 (`rank_bm25`) and `BAAI/bge-small-en-v1.5` embeddings, combined with reciprocal rank fusion (k=60).
   Embeddings are cached in `data/index/embeddings.npy` and rebuilt only when the clauses change.
   Without the model (offline), it falls back to BM25 only.
3. **Cross-references**: the ID matches and the top 3 hits pull in the clauses they reference ("see 4.2" brings 4.2 and its children), capped at 8.
4. **Confidence**: best cosine ≥ 0.70 is `high`, ≥ 0.60 is `low` (the LLM must confirm the clauses answer it, or say not found),
   and below that is `none` ("Not found in the provided rules", no LLM call). Tune with `RULEMATE_HIGH_SCORE` / `RULEMATE_LOW_SCORE`.

```bash
python -m rulemate index                                   # build the embedding cache (first run downloads ~130 MB)
python -m rulemate search "What is the minimum corridor width?" --text
python -m rulemate search "what does 13.3.1.4 say"         # ID lookup + cross-ref to 4.2
python -m rulemate search "helicopter landing area size"   # confidence=none
python -m rulemate search "stair angle" --bm25             # without embeddings
```

## Answers with citations

`python -m rulemate ask "<question>"` retrieves clauses, asks the LLM to answer **only** from them with a
`[doc § clause]` citation on every sentence, then checks the draft in code (`rulemate/guardrails.py`):

| Check | Rejects |
|---|---|
| citation | a sentence without a citation (lead-ins ending in ":" and "not specified" statements without numbers are exempt) |
| retrieved | a citation of a clause that was not retrieved for this question |
| number | a number, or number + unit, that does not appear in the clause cited by that sentence (no unit conversion) |
| quote | quoted text that is not word for word in a cited clause |
| hedge | "probably", "typically", "usually", ... unless the cited clause uses the word |

If a check fails, the LLM gets one retry with the list of violations. If that fails too, the user gets the matching
clause text labelled **excerpts only**. Retrieval confidence `none`, or a `NOT_FOUND` reply from the LLM, gives
"Not found in the provided rules." plus the closest clauses. The LLM never decides what is shown.

| Badge | Meaning |
|---|---|
| verified | generated answer passed every check |
| excerpts only | clause text only (checks failed twice, or LLM unavailable / too slow) |
| not found | nothing in the rules answers the question |

Providers (`rulemate/llm.py`): Groq (`GROQ_MODEL`, default `openai/gpt-oss-120b`), any OpenAI-compatible endpoint, and
Ollama (`llama3.2`) for offline use. `LLM_PROVIDER=groq,ollama` falls through to the next provider on error or
timeout (`LLM_TIMEOUT`). Verified and not-found answers are cached in `data/cache/answers.json`, keyed by question, model and index version.

```bash
python -m rulemate ask "What is the minimum corridor width?"
python -m rulemate ask "what does 13.3.1.4 say" -v          # -v shows guardrail violations of rejected drafts
python -m rulemate ask "helicopter landing area size"       # not found
python -m rulemate ask "maximum stair angle" --provider ollama --no-cache
```

## API and UI

```bash
uvicorn rulemate.api:app --port 8000      # terminal 1: backend (http://localhost:8000/docs)
streamlit run ui/app.py                   # terminal 2: UI (http://localhost:8501)
```

| Endpoint | |
|---|---|
| `GET /health` | documents, clause count, retrieval mode, LLM |
| `POST /ask` | `{"question": "...", "provider": "groq,ollama", "use_cache": true}` returns an answer with status, citations and sources |
| `GET /search?q=` | raw retrieval result with scores |
| `GET /clause/{id}` | clause by ID, e.g. `/clause/II-2/13.3.1.4` or `/clause/Reg.%20II-2%2F9.3.3` |

The UI uses the API when it is running, otherwise it calls the code in-process (so the demo survives a dead API).

- **Ask the rules**: chat with a badge per answer (verified / excerpts only / not found); citation buttons open the clause
  with its page, breadcrumb and clickable "refers to" / "referenced by" links.
- **Sources** panel: every retrieved clause with how it was found (ID, search, cross-reference), fused score, cosine, BM25 and dense rank.
- **Browse clauses**: the whole parsed index, filterable.
- **Compliance check**: sample or uploaded CSV (or values typed into a form), colour-coded results, how each verdict
  was reached, CSV export, and the editable rule table.

## Real rules: 46 CFR Part 190

```bash
python scripts/fetch_cfr.py              # 46 CFR 190 -> data/rules/46CFR190.md (verbatim text, eCFR, latest issue)
python scripts/fetch_cfr.py --part 72    # another part, e.g. passenger vessels
python -m rulemate ingest && python -m rulemate index && python -m rulemate limits --force
python -m rulemate ask "How high must guard rails be on a research vessel?" --rules 46CFR190
```

Sections ending in `-90` apply only to vessels contracted before 1968 and are left out (`--keep-old` keeps them), so
superseded limits do not enter the rule table of a new design. The US text brings real-world wording that the
extractor handles: inches and feet, mixed fractions ("39 1/2 inches"), the same limit stated twice
("190 centimeters (75 inches)", kept once with the other value noted), prohibitions ("dead end corridors more than
40 feet in length shall not be permitted" means `<= 40 ft`), and per-person quantities ("2.78 square meters ... for
each person") that are not room limits.

## Design interpretation: reading design documents

```bash
python scripts/fetch_design_sources.py     # public documents from Meyer's brief -> data/designs/sources/
python -m rulemate design data/designs/sources/NOAA_SWATH_research_ship_1990.pdf --pages 41-43 \
    --label "NOAA SWATH research ship conceptual design (BSM 1990)" --out data/designs/noaa_swath_from_ga.csv
python -m rulemate check data/designs/noaa_swath_from_ga.csv --rules 46CFR190
```

`rulemate design` (`rulemate/design/`) reads design values out of design documents, with the same principle as the
rule side: code reads, and every value keeps its evidence.

- **GA drawings.** Scanned sheets have no text layer, so each page is rendered and read with OCR (RapidOCR, runs
  locally; large sheets in overlapping tiles). Words are grouped into berth labels: each word belongs to the nearest
  occupancy marker directly below it, e.g. `SENIOR / SCIENTIST / (2)`. Each label becomes a design value
  (persons berthed per sleeping room) with its file, page, drawing number, label text and position on the sheet.
  The UI shows that part of the drawing, boxed, next to the verdict. Role labels without a count (`WIPER & OILER`)
  are reported, not guessed.
- **Report text and particulars sheets.** Stated facts with a fixed wording (complement, crew, endurance, mess
  seating, stateroom counts) are kept with page and sentence.
- **Findings** (`rulemate/design/findings.py`): consistency between drawing and text (58 berths drawn vs 60 persons
  stated), and requirements the facts trigger, each tied to a clause, e.g. crew 13 and 21 days endurance means
  46 CFR 190.20-35(a) requires a hospital space, which is then looked for on the drawings. Findings are for an
  engineer to confirm, never a verdict.

On the NOAA second-deck GA (a real 1990 design, the "study" link in Meyer's brief), OCR found 34 of 34 berth labels
and 58 of 58 berths compared with a reading by eye (`eval/noaa_ga_truth.json`); 2 role names have OCR typos.
Limits: room sizes, corridor and stair widths are not measured from drawings yet (the scans have no reliable scale),
and the G.O. Sars GA labels rooms by number, not occupancy. The RCRV GA and 3D model are on Box and must be
downloaded in a browser; the RCRV particulars sheet gives crew, berths and endurance (`data/designs/rcrv_particulars.findings.json`).

## Compliance check

```bash
python -m rulemate limits                     # build / show the rule table (data/index/limits.json)
python -m rulemate check data/designs/rcrv_example_design.csv --rules 46CFR190
python -m rulemate check data/designs/sample_design.csv --rules SAMPLE_SYNTHETIC_rules --out results.csv
python -m rulemate check data/designs/sample_design.csv --explain   # + guardrailed LLM explanations
python -m rulemate check new.csv --baseline old.csv --rules 46CFR190 # change impact: which items changed verdict
```

**Design values.** CSV columns `item_id, space, parameter, value, unit, source, notes`. `source` records where the
value comes from (drawing, sheet, model element, measured or stated) and is shown next to every verdict, so a FAIL
can be traced to the drawing as well as to the clause. Values may be written the way US drawings write them:
`2'-6"`, `3 ft 6 in`, `39 1/2` (unit `in`), or with the unit in the cell (`40 ft`). The research-vessel example
(`data/designs/rcrv_example_design.csv`) uses SYNTHETIC values with planted defects; replace them with values
measured on the RCRV general arrangement and keep the `source` column.

**Change impact.** `--baseline old.csv` checks both versions and lists only the items whose verdict changed (new
FAILs first), new and removed items, and value changes that kept their verdict: what to look at after a late
design change such as an added cabin.

**1. Rule table.** Numeric limits are extracted from every clause that states one (`rulemate/compliance/limits.py`).
The LLM proposes `{parameter, subject, qualifier, condition, comparator, value, unit, quote}` as JSON; code keeps a
proposal only if the value appears in the clause with that unit, pint understands the unit, and the comparator is
valid. Code also corrects the comparator from the wording ("not less than" means `>=`), rejects per-unit rates
("10 mm per person") given as plain values, and drops qualifiers and quotes that are not in the text. A regex
extractor is the default (`auto`): on the two labelled example designs an LLM-built table (Groq gpt-oss-120b) got
79 % / 87 % of verdicts right against 100 % / 100 % for the regex table, because it dropped conditions and added
relaxations. `--method llm` keeps LLM extraction available to propose limits for review. Engineers can review and edit the
table in the UI; edited rows are marked `manual`.

**2. Verdict, in code only** (`rulemate/compliance/check.py`). For each design row:
candidate limits with a compatible unit (pint) → semantic match on parameter → qualifier filter ("crew
accommodation" only applies to crew spaces; a matching specific limit supersedes the general one) → limits whose
sentence refers to a matched clause are added ("the travel distance **in 3.3.1** may be increased to 50 m") →
value converted to the limit unit and compared.

| Verdict | When |
|---|---|
| PASS | every applicable unconditional limit is met, and no conditional limit fails |
| FAIL | an unconditional limit fails and no conditional relaxation is met |
| NEEDS REVIEW | it passes only under a condition code cannot verify, only conditional limits apply, the value or unit is unusable, or no limit covers the parameter |

**3. Explanation.** Optional: the LLM explains the verdict it is given. The explanation goes through the answer
guardrails plus two compliance checks: it may not contradict a computed comparison ("950 mm does not meet 900 mm"
when code says it does) or state an unverified condition as fact. If it fails twice, only the code result is shown.

API: `POST /check` (JSON rows), `POST /check/csv` (upload), `GET /limits`, `PUT /limits`.

## Evaluation

```bash
python eval/run.py --retrieval-only     # seconds: hit@5, MRR, threshold calibration, compliance accuracy
python eval/run.py                      # full: every question answered with the configured LLM, cache off
python eval/run.py --provider groq      # compare providers
```

`eval/questions.jsonl` has 38 questions: 25 answerable (with expected clause IDs and the key numbers a correct
answer must contain), 7 asking for a specific clause ID, and 6 that the rules cannot answer; 8 of them are about
the real 46 CFR 190 text. `eval/rcrv_expected.json` and `eval/compliance_expected.json` label the two example designs.

**Planted defects** (`python eval/seeded.py`, also part of `eval/run.py`): every value the checker passes is moved
3 % past the limit that decided it (must not PASS) and set exactly at that limit (must not FAIL). This measures
the two things that matter for trust: missed violations and false alarms at the boundary, including unit
conversion (a 1.0 m bulwark is 39.37 in, below the 39 1/2 in minimum). The script prints a Markdown table (also saved to
`eval/results/latest.md`) with retrieval hit@5 and MRR, correct "not found" rate, wrongly refused rate, verified /
excerpts share, key-number recall, citation precision (sentence-clause word overlap plus number check), guardrail
rejection rate, answer latency p50/p95, compliance accuracy and planted-defect results per design, followed by a
threshold calibration table.

When the real documents arrive, replace the questions with ones about them (keep the four types) and rerun.

## Deployment

See `DEPLOYMENT.md`: install, configuration, offline / own-server / hosted LLM modes and what data
leaves the machine in each, running as services, access control, updating rules, backups and troubleshooting.

## Demo

See `DEMO.md` for the 3-minute script and the pitch outline. Before presenting, run
`python scripts/warm_demo.py --refresh` to cache every demo answer and explanation and to see exactly what will be shown.

## Using the real challenge data

Meyer provides a public design (the OSU Regional Class Research Vessel: GA drawings, technical documents, a
Navisworks model) rather than rule documents, and a small curated rule set is explicitly fine.

1. Measure or read the values from the RCRV drawings into a CSV like `data/designs/rcrv_example_design.csv`,
   filling `source` with the drawing and sheet. Keep US notation if that is what the drawing says.
2. Add rule documents to `data/rules/` (PDF, DOCX, HTML, TXT, MD), e.g. more CFR parts with `scripts/fetch_cfr.py`,
   DNV rules (free access) or PVAG / ADA. Then `python -m rulemate ingest && python -m rulemate index &&
   python -m rulemate limits --force`, and check the style column and the `unres.` (unresolved references) count.
3. Review the rule table in the UI (Compliance tab), then `python -m rulemate check your.csv --rules <docs>`.
4. To drop the synthetic data: delete `data/rules/SAMPLE_SYNTHETIC_rules.md` and `data/designs/sample_design.csv`.

The synthetic sample is invented data for development only and is flagged `synthetic: true` on every clause.
