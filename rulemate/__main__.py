"""Command line: python -m rulemate <command>"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from .config import CLAUSES_FILE, RULES_DIR


def cmd_ingest(args) -> None:
    from .ingest import ingest_dir

    res = ingest_dir(Path(args.rules_dir))
    if not res.documents:
        print(f"No rule documents found in {args.rules_dir}")
        return
    print(f"{'document':40} {'style':9} {'clauses':>7} {'tables':>6} {'refs':>5} {'unres.':>6}  synthetic")
    for d in res.documents:
        cl = [c for c in res.clauses if c.doc == d.doc]
        refs = sum(len(c.refs) for c in cl)
        unres = sum(len(c.unresolved_refs) for c in cl)
        flag = "YES - dev only" if d.synthetic else ""
        print(f"{d.doc[:40]:40} {d.style:9} {d.n_clauses:>7} {d.n_tables:>6} {refs:>5} {unres:>6}  {flag}")
    print(f"\n{len(res.clauses)} clauses written to {CLAUSES_FILE}")


def _load():
    from .ingest import load_index

    if not CLAUSES_FILE.exists():
        sys.exit("No index yet. Run: python -m rulemate ingest")
    return load_index()


def cmd_show(args) -> None:
    from .lookup import find_clause

    res = _load()
    hits = find_clause(res.clauses, args.clause_id, args.doc)
    if not hits:
        print(f"No clause matching '{args.clause_id}'.")
        return
    for c in hits:
        print("=" * 80)
        if c.synthetic:
            print("[SYNTHETIC SAMPLE - not a real rule]")
        print(c.display())
        if c.path:
            print(f"  path: {' > '.join(c.path)}")
        if c.refs:
            print(f"  refers to: {', '.join(c.refs)}")
        if c.unresolved_refs:
            print(f"  unresolved refs: {', '.join(c.unresolved_refs)}")


def cmd_list(args) -> None:
    res = _load()
    for c in res.clauses:
        if args.doc and c.doc != args.doc:
            continue
        preview = c.text.replace("\n", " ")[:70]
        print(f"{c.clause_id:28} {c.kind:8} p.{c.page or '-':<3} {c.title[:30]:30} | {preview}")
    print(f"\n{Counter(c.kind for c in res.clauses)}")


def cmd_index(args) -> None:
    import time

    from .retrieval import Retriever

    _load()
    t = time.perf_counter()
    r = Retriever(_load().clauses, use_dense=True)
    print(f"mode={r.mode}  searchable={len(r.searchable)}  built in {time.perf_counter() - t:.1f}s")


def cmd_search(args) -> None:
    import time

    from .retrieval import get_retriever

    _load()
    r = get_retriever(use_dense=not args.bm25)
    t = time.perf_counter()
    res = r.search(args.query, k=args.k, follow_refs=not args.no_xref)
    ms = (time.perf_counter() - t) * 1000
    verdict = {"high": "RELEVANT", "low": "WEAK MATCH (LLM must confirm or say not found)",
               "none": "NOTHING RELEVANT -> 'Not found in the provided rules'"}[res.confidence]
    print(f"mode={res.mode}  top_score={res.top_score}  confidence={res.confidence}: {verdict}  ({ms:.0f} ms)")
    if res.id_queries:
        print(f"clause IDs in query: {res.id_queries}")
    print(f"{'source':7} {'score':>6} {'cos':>6} {'bm25':>4} {'dense':>5}  clause")
    for h in res.hits:
        via = f"  (via {h.via})" if h.via else ""
        cos = f"{h.cosine:.3f}" if h.cosine is not None else "-"
        bmr = "-" if h.bm25_rank is None else h.bm25_rank + 1
        dr = "-" if h.dense_rank is None else h.dense_rank + 1
        print(f"{h.source:7} {h.score:6.3f} {cos:>6} {bmr!s:>4} {dr!s:>5}  {h.clause.clause_id}{via}")
        if args.text:
            print("        " + h.clause.text.replace("\n", "\n        ")[:400])


def cmd_ask(args) -> None:
    from .answer import answer_question
    from .llm import get_llm
    from .retrieval import get_retriever

    _load()
    ans = answer_question(args.question, retriever=get_retriever(), llm=get_llm(args.provider), use_cache=not args.no_cache)
    badge = {"verified": "VERIFIED", "excerpts": "EXCERPTS ONLY", "not_found": "NOT FOUND"}[ans.status]
    extra = " (cached)" if ans.cached else ""
    print(f"[{badge}]{extra}  confidence={ans.confidence} top_score={ans.top_score}  "
          f"attempts={ans.attempts} rejected={ans.rejected_attempts}  {ans.model}  {ans.latency_ms:.0f} ms")
    if ans.synthetic:
        print("[SYNTHETIC SAMPLE DATA - not a real rule]")
    print("-" * 80)
    print(ans.text)
    print("-" * 80)
    if ans.citations:
        print("cited: " + ", ".join(f"{c.clause_id} (p.{c.page})" for c in ans.citations))
    if ans.note:
        print(f"note: {ans.note}")
    if ans.violations and args.verbose:
        print("guardrail violations on last rejected draft:")
        for v in ans.violations:
            print(f"  - {v}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="rulemate")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="parse rule documents into clauses")
    p.add_argument("--rules-dir", default=str(RULES_DIR))
    p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("show", help="show one clause by ID, e.g. 'II-2/13.3.1' or '13.3.1'")
    p.add_argument("clause_id")
    p.add_argument("--doc")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("list", help="list all parsed clauses")
    p.add_argument("--doc")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("index", help="build / refresh the embedding cache")
    p.set_defaults(fn=cmd_index)

    p = sub.add_parser("search", help="hybrid search over clauses")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=5)
    p.add_argument("--text", action="store_true", help="print clause text")
    p.add_argument("--no-xref", action="store_true", help="do not follow cross-references")
    p.add_argument("--bm25", action="store_true", help="BM25 + ID lookup only (no embeddings)")
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("ask", help="answer a question with verified citations")
    p.add_argument("question")
    p.add_argument("--provider", help="e.g. groq | openai | ollama | groq,ollama (default: LLM_PROVIDER)")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true", help="show guardrail violations")
    p.set_defaults(fn=cmd_ask)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
