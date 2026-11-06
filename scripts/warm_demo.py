"""Warm the caches before a demo so every demo step returns instantly.

    python scripts/warm_demo.py                 # uses LLM_PROVIDER from .env (same default as the UI)
    python scripts/warm_demo.py --provider groq,ollama

Asks the demo questions (answer cache), builds the rule table, and runs the sample compliance check with
explanations (explanation cache). Prints what will be shown so you can check it before going on stage.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rulemate.answer import answer_question  # noqa: E402
from rulemate.compliance.check import read_design_csv  # noqa: E402
from rulemate.compliance.service import check_rows, get_rule_table  # noqa: E402
from rulemate.llm import get_llm  # noqa: E402
from rulemate.retrieval import get_retriever  # noqa: E402

from rulemate.config import DEMO_QUESTIONS  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="groq,ollama", help="must match the provider selected in the UI")
    ap.add_argument("--refresh", action="store_true", help="clear cached answers and explanations first")
    args = ap.parse_args()

    if args.refresh:
        for f in (ROOT / "data" / "cache").glob("*.json"):
            f.unlink()
    r = get_retriever()
    for q, docs in DEMO_QUESTIONS:
        a = answer_question(q, retriever=r, llm=get_llm(args.provider), use_cache=True, docs=docs)
        stored = a.cached or a.status != "excerpts"  # verified and not-found answers are cached
        print(f"\n[{a.status.upper()}] {q}  ({a.model or 'no LLM'}, {a.latency_ms / 1000:.1f}s, "
              f"{'from cache' if a.cached else 'cached for the demo' if stored else 'NOT cached'})")
        print("  " + a.text.replace("\n", "\n  ")[:600])
        if a.status == "excerpts":
            print("  !! excerpts only - check the LLM provider before the demo")

    t = get_rule_table(provider=args.provider)
    print(f"\nRule table: {len(t.limits)} limits ({t.model})")
    for fname, docs in (("rcrv_example_design.csv", ["46CFR190"]), ("sample_design.csv", ["SAMPLE_SYNTHETIC_rules"])):
        rows = read_design_csv((ROOT / "data" / "designs" / fname).read_bytes())
        results = check_rows(rows, explain=True, provider=args.provider, docs=docs)
        print(f"\n{fname}:")
        for res in results:
            if res.verdict != "PASS":
                print(f"  {res.verdict:12} {res.row.item_id} {res.row.parameter}: explanation {res.explanation_status}")
    print("\nDone. In the UI keep 'Use answer cache' on and select the same provider.")


if __name__ == "__main__":
    main()
