"""Gemini drawing reading vs the labels read by eye (eval/noaa_ga_truth.json), next to the OCR result.

    python eval/gemini_drawing.py          # calls Gemini once (about 1-4 min); result cached in eval/results/

Counts a Gemini reading as correct when role and berth count match a label on the drawing, and reports how many
of its readings code could confirm on the sheet. The eval report (eval/run.py) shows the cached result.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "eval" / "results" / "gemini_drawing.json"


def norm_role(s: str) -> str:
    s = re.sub(r"\(\d+\)", "", s.upper())
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def main() -> None:
    from rulemate.design.extract import ocr_page
    from rulemate.design.vision import read_sheet
    from rulemate.llm import make_provider

    truth = json.loads((ROOT / "eval" / "noaa_ga_truth.json").read_text())
    pdf = ROOT / truth["source_file"]
    llm = make_provider("gemini")
    llm.model = os.getenv("GEMINI_VISION_MODEL", llm.model)
    llm.timeout = max(llm.timeout, 300)
    t0 = time.time()
    rooms = read_sheet(pdf, truth["page"], llm, ocr_page(pdf, truth["page"]))
    secs = time.time() - t0
    rooms = [r for r in rooms if r.kind == "stateroom" or r.berths]
    want = Counter((norm_role(r), n) for r, n in truth["labels"])
    got = Counter((norm_role(r.label), r.berths) for r in rooms if r.berths)
    exact = sum((want & got).values())
    res = {
        "model": llm.model, "seconds": round(secs), "n_truth": sum(want.values()), "readings": len(rooms),
        "correct": exact, "confirmed": sum(r.confirmed for r in rooms),
        "berths_read": sum(r.berths or 0 for r in rooms), "berths_truth": sum(n for _, n in truth["labels"]),
        "wrong": [f"{r.label} ({r.berths})" for r in rooms if (norm_role(r.label), r.berths) not in want],
        "when": time.strftime("%Y-%m-%d %H:%M"),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
