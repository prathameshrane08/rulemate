"""Write the Copilot's accuracy.json (Accuracy tab) from eval/results/*.json runs.

    python eval/accuracy_json.py OUT.json run1.json run2.json ...

Each run file is one model on one question set (eval/run.py). The headline per model is the FRESH set: questions
written after the last change to the code and never used to tune it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SETS = {15: "fresh", 20: "held-out", 45: "development"}
SET_NOTE = {"fresh": "15 questions written after the last code change; never used for tuning",
            "held-out": "20 questions; the search fixes of 7 Nov were prompted by misses on this set",
            "development": "45 questions the checks were developed and tuned on"}
NAMES = {"groq:openai/gpt-oss-120b": "gpt-oss-120b (Groq, cloud)", "groq:openai/gpt-oss-20b": "gpt-oss-20b (Groq, cloud)",
         "groq:qwen/qwen3.8-27b": "qwen3.8-27b (Groq, cloud)", "ollama:qwen3:8b": "qwen3:8b (Ollama, this computer)",
         "ollama:llama3.2:3b": "llama3.2:3b (Ollama, this computer)"}


def main() -> int:
    out_path, files = Path(sys.argv[1]), [Path(p) for p in sys.argv[2:]]
    runs = []
    for f in files:
        d = json.loads(f.read_text())
        a, r = d["answers"], d["retrieval"]
        unavailable = sum("LLM unavailable" in (x["answer"] or "") for x in d["answer_rows"])
        runs.append({"id": d["meta"]["llm"], "set": SETS[d["meta"]["n_questions"]], "when": d["meta"]["when"],
                     "verified": a["verified"], "citation_precision": a["citation_precision"],
                     "fact_recall": a["fact_recall"], "correct_not_found": a["correct_not_found"],
                     "false_not_found": a["false_not_found"], "latency_p50_s": round(a["latency_p50_s"], 1),
                     "retrieval_hit5": r["hit@5"], "n_answerable": r["n_answerable"],
                     "n_unanswerable": a["n_unanswerable"], "unavailable": unavailable})
    models = []
    for mid, name in NAMES.items():
        mine = {x["set"]: x for x in runs if x["id"] == mid}
        if not mine:
            continue
        head = mine.get("fresh") or next(iter(mine.values()))
        models.append({"id": mid, "name": name, "local": mid.startswith("ollama"), "headline_set": head["set"],
                       **{k: head[k] for k in ("verified", "citation_precision", "fact_recall", "correct_not_found",
                                               "false_not_found", "latency_p50_s")},
                       "sets": [mine[s] for s in ("fresh", "held-out", "development") if s in mine]})
    acc = json.loads(out_path.read_text()) if out_path.exists() else {}
    acc["models"] = models
    acc["sets"] = SET_NOTE
    acc["measured"] = max(x["when"] for x in runs)[:10]
    out_path.write_text(json.dumps(acc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(models)} models, {len(runs)} runs -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
