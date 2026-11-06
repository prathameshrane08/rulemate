# Deploying RuleMate

RuleMate is two Python processes and a folder of files. There is no database and no other service to run.

| Part | What it is | Port |
|---|---|---|
| API | FastAPI app `rulemate.api:app`, served by uvicorn: `/ask`, `/check`, `/clause/{id}`, `/limits`, `/health` | 8000 |
| UI | Streamlit app `ui/app.py`. It calls the API, and if the API is unreachable it runs the same code in-process | 8501 |
| `data/rules/` | rule documents (PDF, DOCX, HTML, TXT, MD): **input** | |
| `data/index/` | generated: `clauses.json`, embeddings, `limits.json` (the rule table, **including engineer edits**) | |
| `data/cache/` | generated: cached answers and explanations; safe to delete | |
| LLM | Groq, any OpenAI-compatible endpoint, or a local Ollama model; set in `.env` | |

Compliance verdicts never need the LLM. It is used to write answers and explanations, which code then checks.

Tested on macOS 15 (Apple silicon) with Python 3.14 and on the stack in `requirements.txt`. The Linux service setup
below uses the same commands; adapt paths to your server.

## 1. Requirements

- Python 3.12 or newer, about 2 GB disk (PyTorch for the embedding model, which is about 130 MB).
- 4 GB RAM for RuleMate itself. For the offline LLM, add Ollama with `llama3.2` (about 2 GB download, 8 GB RAM).
- Internet only for the first install and model download, and while a hosted LLM is used.

## 2. Install and build the index

```bash
git clone <repo> rulemate && cd rulemate
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && cp .env.example .env      # then edit .env (section 3)

python scripts/fetch_cfr.py          # optional: real 46 CFR Part 190 text into data/rules/
python -m rulemate ingest            # split rule documents into clauses
python -m rulemate index             # embeddings (downloads BAAI/bge-small-en-v1.5 once)
python -m rulemate limits --force    # rule table of numeric limits
python scripts/fetch_design_sources.py   # optional: public design documents for the drawing examples
pytest -q                            # 120 tests, about 10 s
```

## 3. Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `groq,ollama` | Providers in order; the next one is used if one fails, times out or is rate-limited |
| `GROQ_API_KEY`, `GROQ_MODEL` | -, `openai/gpt-oss-120b` | Groq (console.groq.com) |
| `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL` | OpenAI | Any OpenAI-compatible endpoint, e.g. a self-hosted vLLM or an EU-hosted service |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | `http://localhost:11434`, `llama3.2` | Local model |
| `LLM_TIMEOUT` | `25` | Seconds per LLM call before falling back |
| `LLM_REASONING_EFFORT` | `low` | For gpt-oss models |
| `LLM_RATE_LIMIT_WAIT` | `30` | Maximum total seconds to wait on HTTP 429 before falling back |
| `RULES_DIR`, `INDEX_DIR`, `EMBED_MODEL` | `data/rules`, `data/index`, `BAAI/bge-small-en-v1.5` | Paths and embedding model |
| `RULEMATE_API_URL` | `http://localhost:8000` | Where the UI finds the API |
| `RULEMATE_LOW_SCORE`, `RULEMATE_HIGH_SCORE` | `0.60`, `0.70` | Retrieval confidence thresholds (recalibrate with `eval/run.py` on new rules) |

`.env` holds API keys: it is git-ignored and must not be copied into images or shared folders.

## 4. Where data goes: pick a mode

| Mode | Set | What leaves the machine |
|---|---|---|
| **Fully offline / on-premises** | `LLM_PROVIDER=ollama` | Nothing. Parsing, drawing OCR, embeddings, checks and the LLM all run locally. |
| **Own or EU-hosted model** | `LLM_PROVIDER=openai`, `OPENAI_BASE_URL=https://<your endpoint>/v1` | The question and the retrieved clause text go to that endpoint, nothing else. |
| **Hosted (demo)** | `LLM_PROVIDER=groq,ollama` | The question and retrieved clause text go to Groq (US). Fine for public rule texts; not for confidential designs. |

Design values are never sent to an LLM for the verdict. With explanations switched on (`--explain`, UI toggle), the
row being explained (space, parameter, value) and its clauses are sent to the configured LLM; use an offline or own
endpoint for confidential designs.

After the first `index`, the embedding model is loaded with `local_files_only=True`, so the API also starts on a
machine without internet. To prepare an offline server, copy `~/.cache/huggingface/hub/models--BAAI--bge-small-en-v1.5`
from a machine where `index` has run. If the model is missing, retrieval falls back to BM25 only (`/health` shows
`retrieval_mode`).

## 5. Run

Laptop or demo:

```bash
uvicorn rulemate.api:app --port 8000          # terminal 1
streamlit run ui/app.py --server.port 8501    # terminal 2 -> http://localhost:8501
curl localhost:8000/health                    # documents, clause counts, retrieval mode
```

Server (Linux, systemd): one unit per process. Bind both to localhost and put a reverse proxy in front.

```ini
# /etc/systemd/system/rulemate-api.service
[Unit]
Description=RuleMate API
After=network.target

[Service]
User=rulemate
WorkingDirectory=/opt/rulemate
ExecStart=/opt/rulemate/.venv/bin/uvicorn rulemate.api:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/rulemate-ui.service
[Unit]
Description=RuleMate UI
After=rulemate-api.service

[Service]
User=rulemate
WorkingDirectory=/opt/rulemate
Environment=RULEMATE_API_URL=http://127.0.0.1:8000
ExecStart=/opt/rulemate/.venv/bin/streamlit run ui/app.py --server.address 127.0.0.1 --server.port 8501
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now rulemate-api rulemate-ui
```

Use one API worker: the embedding model and index are held in memory per process (about 500 MB).

## 6. Access control

RuleMate has **no login of its own** in this prototype. Do not expose ports 8000/8501 directly. Put it behind the
company reverse proxy (nginx, Traefik, an SSO proxy such as oauth2-proxy) and keep the API reachable only from the
UI host. `PUT /limits` changes the rule table for every user: restrict it to engineers who own the rule table
(role-based access is on the roadmap).

## 7. Updating rules

```bash
cp new_rules.pdf data/rules/
python -m rulemate ingest && python -m rulemate index && python -m rulemate limits
```

No restart needed: the API reloads the index when `clauses.json` changes, and reads the rule table on every check.
`limits` without `--force` re-extracts only clauses whose text changed, so engineer edits to unchanged clauses stay.
After a rules update:

1. Check `python -m rulemate ingest` output: the parser style per document and the unresolved-reference count.
2. Review the rule table (UI, Compliance tab, or `python -m rulemate limits`).
3. Run `python eval/run.py --retrieval-only` (seconds): retrieval hit@5, compliance verdicts on the labelled designs
   and the planted-defect test must stay at their previous values.

The rule table is built by the deterministic regex extractor by default. `python -m rulemate limits --force
--method llm` lets an LLM propose limits; on the labelled designs it was less accurate (79 % vs 100 % of verdicts),
so treat its output as proposals to review.

## 8. Back up

`data/rules/` (inputs) and `data/index/limits.json` (the rule table, with engineer edits). Everything else in
`data/index/` and `data/cache/` can be rebuilt with the commands in section 2.

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `CERTIFICATE_VERIFY_FAILED` when fetching rules (python.org Python on macOS) | `scripts/fetch_cfr.py` uses certifi; for other tools run `Install Certificates.command` from the Python folder |
| Answers show *excerpts only* with "HTTP 429" | Groq free-tier rate limit: wait a minute, raise `LLM_RATE_LIMIT_WAIT`, or put `ollama` second in `LLM_PROVIDER` |
| `/health` shows `bm25-only` | Embedding model not downloaded: run `python -m rulemate index` once with internet |
| UI says backend *in-process* | API not reachable at `RULEMATE_API_URL`; the UI still works on its own |
| Ollama model not found | `ollama pull llama3.2` |
