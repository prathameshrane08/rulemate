# RuleMate

Answers questions about ship design rules with exact clause citations, and checks design values against rule limits.
Every answer is traceable to a clause, or it says "not found in the rules".

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
| `decimal` | `4.2.1 ...` | `4.2.1` |
| `fallback` | headings only | `S3`, `S3.1` |

The style is detected per document; force one with `data/rules/styles.json`, e.g. `{"my_rules_file": "class"}`.

```bash
python -m rulemate list                 # every parsed clause
python -m rulemate show "Reg. II-2/13.3.2.1"
python -m rulemate show 13.3.1.4        # suffix match, shows cross-refs
pytest -q
```

## Using the real challenge data

1. Delete `data/rules/SAMPLE_SYNTHETIC_rules.md` and `data/designs/sample_design.csv`.
2. Copy the rule documents into `data/rules/`.
3. Run `python -m rulemate ingest` and check the style column and the `unres.` (unresolved references) count.

The synthetic sample is invented data for development only and is flagged `synthetic: true` on every clause.
