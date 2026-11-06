"""Planted-defect test for the compliance check: can it tell compliant from non-compliant, without false alarms?

For every design value the checker passes, two variants are made from the limit that decided it:
  * violating  - 3 % beyond the limit (e.g. stair width 28 in -> 27.16 in)        expected: FAIL
                 (NEEDS REVIEW also counts as caught when a conditional relaxation could make it compliant;
                  a violating value that PASSES is a miss)
  * at limit   - exactly the limit, converted to the design's own unit            expected: PASS
The first measures detection, the second false alarms at the boundary (>= / <= and unit conversion).

    python eval/seeded.py                                  # both example designs
    python eval/seeded.py data/designs/my.csv --rules 46CFR190
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rulemate.compliance.check import DesignRow, RowResult  # noqa: E402
from rulemate.compliance.units import convert  # noqa: E402

STEP = 0.03


def _binding(r: RowResult):
    """The applied limit with the smallest margin: the one a small change would break first."""
    best, margin = None, None
    for lr in r.limits:
        if lr.role != "applied" or lr.outcome != "pass" or lr.value_in_limit_unit is None or not lr.limit.value:
            continue
        m = abs(lr.value_in_limit_unit - lr.limit.value) / abs(lr.limit.value)
        if margin is None or m < margin:
            best, margin = lr, m
    return best


def variants(results: list[RowResult]) -> list[tuple[DesignRow, str, str]]:
    """(row, expected verdict, label) for every PASS row."""
    out = []
    for r in results:
        if r.verdict != "PASS":
            continue
        lr = _binding(r)
        if lr is None:
            continue
        lim = lr.limit
        at = convert(lim.value, lim.unit, r.row.unit)
        if lim.comparator in (">=", ">"):
            bad = at * (1 - STEP)
        else:
            bad = at * (1 + STEP)
        for value, expected, label in ((bad, "FAIL", "violating"), (at, "PASS" if lim.comparator in (">=", "<=") else "FAIL", "at limit")):
            row = r.row.model_copy(update={"item_id": f"{r.row.item_id}~{label}", "value": value,
                                           "raw_value": f"{value:.6g}"})
            out.append((row, expected, f"{label}: {value:.6g} {r.row.unit} vs {lim.describe()} [{lim.clause_id}]"))
    return out


def seeded_metrics(rows: list[DesignRow], docs: list[str] | None) -> dict:
    from rulemate.compliance.service import check_rows

    base = check_rows(rows, docs=docs)
    cases = variants(base)
    if not cases:
        return {"n_violating": 0, "n_at_limit": 0}
    got = check_rows([c[0] for c in cases], docs=docs)
    rows_out = [{"case": label, "expected": exp, "got": g.verdict} for (_, exp, label), g in zip(cases, got)]
    viol = [x for x in rows_out if x["case"].startswith("violating")]
    at = [x for x in rows_out if x["case"].startswith("at limit")]
    return {
        "n_violating": len(viol),
        "caught": sum(x["got"] != "PASS" for x in viol) / len(viol),
        "violating_fail": sum(x["got"] == "FAIL" for x in viol),
        "violating_review": sum(x["got"] == "NEEDS REVIEW" for x in viol),
        "n_at_limit": len(at),
        "false_fail_at_limit": sum(x["got"] == "FAIL" for x in at) / len(at) if at else 0.0,
        "wrong": [x for x in rows_out if (x["got"] == "PASS") != (x["expected"] == "PASS")],
        "review": [x for x in rows_out if x["got"] == "NEEDS REVIEW"],
    }


def main() -> None:
    from rulemate.compliance.check import read_design_csv

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?")
    ap.add_argument("--rules", help="rule documents that apply, comma-separated")
    args = ap.parse_args()
    sets = ([(args.csv, args.rules.split(",") if args.rules else None)] if args.csv else
            [(str(ROOT / "data/designs/rcrv_example_design.csv"), ["46CFR190"]),
             (str(ROOT / "data/designs/sample_design.csv"), ["SAMPLE_SYNTHETIC_rules"])])
    for path, docs in sets:
        m = seeded_metrics(read_design_csv(Path(path).read_bytes()), docs)
        print(f"\n{Path(path).name} ({', '.join(docs or ['all rules'])})")
        if not m["n_violating"]:
            print("  no PASS rows to plant defects in")
            continue
        print(f"  planted defects caught: {m['caught']:.0%} of {m['n_violating']} "
              f"({m['violating_fail']} FAIL, {m['violating_review']} NEEDS REVIEW)")
        print(f"  false FAIL at the exact limit: {m['false_fail_at_limit']:.0%} of {m['n_at_limit']}")
        for w in m["wrong"]:
            print(f"  ! expected {w['expected']}, got {w['got']}: {w['case']}")
        for w in m["review"]:
            print(f"  ? sent to review: {w['case']}")


if __name__ == "__main__":
    main()
