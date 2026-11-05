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

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
