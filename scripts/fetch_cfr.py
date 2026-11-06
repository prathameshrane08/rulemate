"""Download a part of the US Code of Federal Regulations from eCFR into data/rules/ as Markdown.

    python scripts/fetch_cfr.py                 # 46 CFR Part 190 (oceanographic research vessels:
                                                #   construction & arrangement, means of escape, accommodation, rails)
    python scripts/fetch_cfr.py --part 72       # 46 CFR Part 72 (passenger vessels: construction & arrangement)

US federal regulations are public domain. The text is copied verbatim; only the layout changes
(subpart / section headings, one paragraph per line) so the CFR parser can split it into clauses.

Sections ending in -90 apply only to vessels contracted before 1968/69 and are left out by default:
they would add superseded limits to the rule table of a new design (use --keep-old to include them).
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://www.ecfr.gov/api/versioner/v1"


def _ssl_context():
    import ssl

    try:
        import certifi  # python.org builds on macOS ship without CA certificates

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": "rulemate-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            import gzip

            data = gzip.decompress(data)
    return data


def text_of(fragment: str) -> str:
    t = re.sub(r"<[^>]+>", " ", fragment)
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"\s+([,.;:)])", r"\1", t).replace("( ", "(")


def table_md(fragment: str) -> str:
    rows = []
    for row in re.findall(r"<(?:ROW|BOXHD)[^>]*>(.*?)</(?:ROW|BOXHD)>", fragment, re.S):
        cells = [text_of(c) for c in re.findall(r"<(?:ENT|CHED)[^>]*>(.*?)</(?:ENT|CHED)>", row, re.S)]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def convert(xml: str, title: int, part: int, date: str, keep_old: bool) -> tuple[str, int, int]:
    part_head = text_of(re.search(r"<DIV5[^>]*>\s*<HEAD>(.*?)</HEAD>", xml, re.S).group(1))
    lines = [
        f"<!-- SOURCE: {title} CFR Part {part}, eCFR (https://www.ecfr.gov), current as of {date}. "
        "US federal regulation, public domain. Text verbatim; layout converted by scripts/fetch_cfr.py. -->",
        f"# {title} CFR {part_head}",
        "",
    ]
    kept = skipped = 0
    for sub in re.finditer(r"<DIV6[^>]*>(.*?)</DIV6>", xml, re.S):
        body = sub.group(1)
        lines += [f"## {text_of(re.search(r'<HEAD>(.*?)</HEAD>', body, re.S).group(1))}", ""]
        for sec in re.finditer(r'<DIV8 N="([^"]+)"[^>]*>(.*?)</DIV8>', body, re.S):
            n, sbody = sec.groups()
            if n.endswith("-90") and not keep_old:
                skipped += 1
                continue
            kept += 1
            lines += [f"### {text_of(re.search(r'<HEAD>(.*?)</HEAD>', sbody, re.S).group(1))}", ""]
            for el in re.finditer(r"<(P|FP|GPOTABLE)\b[^>]*>(.*?)</\1>", sbody, re.S):
                t = table_md(el.group(2)) if el.group(1) == "GPOTABLE" else text_of(el.group(2))
                if t:
                    lines += [t, ""]
    if skipped:
        lines.insert(2, f"<!-- {skipped} section(s) for vessels contracted before 1968/69 (-90) omitted. -->")
    return "\n".join(lines).rstrip() + "\n", kept, skipped


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--title", type=int, default=46)
    ap.add_argument("--part", type=int, default=190)
    ap.add_argument("--date", help="issue date YYYY-MM-DD (default: latest)")
    ap.add_argument("--out", help="output file (default: data/rules/<title>CFR<part>.md)")
    ap.add_argument("--keep-old", action="store_true", help="keep -90 sections for pre-1968 vessels")
    args = ap.parse_args(argv)

    date = args.date
    if not date:
        titles = json.loads(get(f"{API}/titles.json"))["titles"]
        date = next(t["latest_issue_date"] for t in titles if t["number"] == args.title)
    xml = get(f"{API}/full/{date}/title-{args.title}.xml?part={args.part}").decode("utf-8")
    if "<DIV5" not in xml:
        sys.exit(f"eCFR returned no part text: {xml[:300]}")
    md, kept, skipped = convert(xml, args.title, args.part, date, args.keep_old)
    out = Path(args.out) if args.out else ROOT / "data" / "rules" / f"{args.title}CFR{args.part}.md"
    out.write_text(md, encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}: {kept} sections"
          f"{f', {skipped} pre-1968 sections omitted' if skipped else ''} (eCFR {date})")
    print("next: python -m rulemate ingest && python -m rulemate index && python -m rulemate limits --force")


if __name__ == "__main__":
    main()
