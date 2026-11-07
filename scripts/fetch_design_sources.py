"""Download the public design documents used by the examples into data/designs/sources/ (not kept in git).

    python scripts/fetch_design_sources.py

Sources are the links in Meyer's challenge brief. The RCRV GA drawing and design summary are on Box and must be
downloaded in a browser from https://ceoas.oregonstate.edu/regional-class-research-vessel-ship-design and saved as
    data/designs/sources/RCRV_GA_6096-070-001_RevJ.pdf               ("6096-070-001-(J) General Arrangement.pdf")
    data/designs/sources/RCRV_design_summary_12100-000-01_RevA.pdf   ("12100-000-01_design_summary_report_rev_a.pdf")
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_cfr import _ssl_context  # noqa: E402

SOURCES = {
    "NOAA_SWATH_research_ship_1990.pdf": "https://repository.library.noaa.gov/view/noaa/30507/noaa_30507_DS1.pdf",
    "RCRV_particulars.pdf": "https://ceoas.oregonstate.edu/sites/ceoas.oregonstate.edu/files/2024-07/rcrv-particulars.pdf",
    "RCRV_development_of_design.pdf":
        "https://ceoas.oregonstate.edu/sites/ceoas.oregonstate.edu/files/2024-07/development_of_rcrv_design.pdf",
    "GO_SARS_general_arrangement_RevH.pdf": "https://www.hi.no/resources/04650-Rev.H-General-Arrangement-GO-SARS.pdf",
}


def main() -> None:
    out = ROOT / "data" / "designs" / "sources"
    out.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        dest = out / name
        if dest.exists():
            print(f"have  {name}")
            continue
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (rulemate-fetch)"})
        with urllib.request.urlopen(req, timeout=120, context=_ssl_context()) as r:
            data = r.read()
        if not data.startswith(b"%PDF"):
            print(f"FAIL  {name}: not a PDF (site changed?) - download {url} in a browser")
            continue
        dest.write_bytes(data)
        print(f"saved {name} ({len(data) // 1024} KB)")


if __name__ == "__main__":
    main()
