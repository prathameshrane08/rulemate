"""Extract checkable design values from design documents: GA drawings (OCR) and report text.

Same principle as the rule side: code reads the document and every value keeps its evidence (file, page, drawing
number, the exact label and where it sits on the sheet), so a verdict can be traced back to the drawing.

GA drawings
    Scanned GA sheets have no text layer, so each page is rendered and read with OCR (RapidOCR, runs locally).
    Words are grouped into room labels: a stateroom on a GA is labelled with the occupant role and the number of
    berths, e.g. "SENIOR / SCIENTIST / (2)". Labels whose markers are stacked inside one room ("MESSMAN (1)" over
    "CHIEF STEWARD (1)") are added up to persons per room.

Report text
    Stated facts with a fixed wording (total complement, mess room seating, stateroom counts) are read with
    patterns and kept with their page and the exact sentence. They are used for consistency checks between the
    drawing and the text, not as guesses.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..config import ROOT

OCR_CACHE = ROOT / "data" / "cache" / "ocr"
DPI = 200
_PT = 72 / DPI  # pixels -> PDF points

# symbols on GA drawings that are not part of a room label
_NOT_LABEL = {"T/S", "T/s", "LKR", "VT", "UP", "DN", "VENT", "WT", "TR", "S/1", "s/1"}
_OCC = re.compile(r"^\(([0-9lI]{1,2})\)$")
_ROLE = re.compile(r"\b(SCIENTIST|TECH\w*|ENGINEER|OFFICER|SEAMAN|WIPER|OILER|COOK|MESSMAN|STEWARD|BOATSWAIN|"
                   r"MASTER|MATE|CAPTAIN|CREW|CADET|STUDENT|ELECTRICIAN)\b")
_SCIENCE = re.compile(r"\b(SCIENTIST|TECH|TECHNICIAN|RESEARCHER|STUDENT)\b")


@dataclass
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    score: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def h(self) -> float:
        return self.y1 - self.y0


@dataclass
class RoomLabel:
    roles: list[str]  # "SENIOR SCIENTIST", one per stacked occupancy marker
    counts: list[int]
    bbox: tuple[float, float, float, float]  # PDF points, top-left origin
    raw: str
    score: float = 1.0  # lowest OCR confidence of its words

    @property
    def persons(self) -> int:
        return sum(self.counts)

    @property
    def group(self) -> str:
        sci = [bool(_SCIENCE.search(r)) for r in self.roles]
        return "scientific personnel" if all(sci) else "crew" if not any(sci) else "crew and scientific personnel"


@dataclass
class Fact:
    """A design value read from a document, with its evidence."""

    item_id: str
    space: str
    parameter: str
    value: float
    unit: str
    source: str
    notes: str = ""
    source_file: str = ""
    source_page: int = 0
    source_bbox: str = ""  # "x0,y0,x1,y1" in PDF points
    checkable: bool = True  # False: context / consistency facts, not compared against a rule


@dataclass
class Extraction:
    file: str
    doc_label: str
    facts: list[Fact] = field(default_factory=list)
    drawings: list[dict] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)  # consistency notes for an engineer


# ------------------------------------------------------------------ OCR


def _file_hash(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


TILE = 2000  # pixels; OCR shrinks large images, so big sheets are also read in overlapping tiles
OVERLAP = 500
SINGLE_PASS_MAX = 3600


def ocr_page(path: Path, page_no: int) -> list[Word]:
    """OCR one page (1-based). Cached per file content and page. Positions are in PDF points."""
    cache = OCR_CACHE / f"{_file_hash(path)}_p{page_no}_{DPI}_v3.json"
    if cache.exists():
        return [Word(**w) for w in json.loads(cache.read_text())]
    import numpy as np
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        img = np.array(pdf.pages[page_no - 1].to_image(resolution=DPI).original.convert("RGB"))
    H, W = img.shape[:2]

    def run(arr, ox: int, oy: int) -> list[Word]:
        res = _engine()(arr)
        out = []
        for box, txt, sc in zip(res.boxes if res.boxes is not None else [], res.txts or [], res.scores or []):
            xs, ys = [float(q[0]) + ox for q in box], [float(q[1]) + oy for q in box]
            out.append(Word(txt.strip(), min(xs) * _PT, min(ys) * _PT, max(xs) * _PT, max(ys) * _PT,
                            round(float(sc), 3)))
        return out

    words = run(img, 0, 0)  # whole page: titles and large text
    if max(H, W) > SINGLE_PASS_MAX:  # big sheet: small labels need tiles; keep whole-page words where they overlap
        tiled: list[Word] = []
        step = TILE - OVERLAP
        for ty in range(0, max(1, H - OVERLAP), step):
            for tx in range(0, max(1, W - OVERLAP), step):
                for w in run(img[ty : ty + TILE, tx : tx + TILE], tx, ty):
                    dup = next((i for i, o in enumerate(tiled) if _same(w, o)), None)
                    if dup is None:
                        tiled.append(w)
                    elif len(w.text) > len(tiled[dup].text):  # a word cut at a tile edge loses to the full one
                        tiled[dup] = w
        words += [w for w in tiled if not any(_same(w, o) for o in words)]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps([asdict(w) for w in words]))
    return words


def _same(a: Word, b: Word) -> bool:
    ix = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    iy = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    inter = ix * iy
    small = min((a.x1 - a.x0) * (a.y1 - a.y0), (b.x1 - b.x0) * (b.y1 - b.y0)) or 1.0
    return inter / small > 0.5


_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr import RapidOCR

        _ENGINE = RapidOCR()
    return _ENGINE


# ------------------------------------------------------------------ GA drawings


def drawing_meta(words: list[Word]) -> dict:
    text = [w.text for w in words]
    joined = " | ".join(text)
    dwg = re.search(r"DWG\.?\s*No\.?\s*([0-9A-Z][0-9A-Z\-./]+)", joined, re.I)
    scale = re.search(r"SCALE:?\s*([^|]+)", joined, re.I)
    is_ga = "GENERAL ARRANGEMENT" in joined.upper()
    title = ""
    for i, t in enumerate(text):
        if t.upper() == "GENERAL ARRANGEMENT" and i + 1 < len(text):
            title = text[i + 1].strip()
            break
    plan = next((t for t in text if re.match(r"^PLAN AT ", t, re.I)), "")
    deck = plan[8:].strip().title() if plan else title.title()
    return {"drawing": dwg.group(1) if dwg else "", "title": title, "deck": deck, "is_ga": is_ga,
            "scale": scale.group(1).strip() if scale else ""}


def room_labels(words: list[Word]) -> list[RoomLabel]:
    """Group OCR words into berth labels: "SENIOR / SCIENTIST / (2)".

    Every text word belongs to the nearest occupancy marker directly below it (within three label lines, in the
    same column), so a word is never used by two labels. Stacked labels such as "MESSMAN (1)" over
    "CHIEF STEWARD (1)" stay separate: a GA does not show reliably whether they share one room.
    """
    if not words:
        return []
    occ = [w for w in words if _OCC.match(w.text)]
    lh = statistics.median(w.h for w in occ) if occ else 10.0  # height of a label line
    texty = [w for w in words if not _OCC.match(w.text) and w.text not in _NOT_LABEL
             and re.search(r"[A-Za-z]{2,}", w.text)]

    owner: dict[int, list[Word]] = {id(m): [] for m in occ}
    for w in texty:
        best, best_d = None, None
        for m in occ:
            d = m.y0 - w.y0
            if 0 < d <= 2.4 * lh and abs(w.cx - m.cx) <= (w.x1 - w.x0) / 2 + 0.6 * lh:
                if best_d is None or d < best_d:
                    best, best_d = m, d
        if best is not None:
            owner[id(best)].append(w)

    owned = {id(w) for ws in owner.values() for w in ws}
    room_labels.unlabelled = [  # type: ignore[attr-defined]  role text with no berth count under it
        w for w in texty if id(w) not in owned and _ROLE.search(w.text.upper())]

    out = []
    for m in occ:
        ws = owner[id(m)]
        if not ws:
            continue
        lines: list[list[Word]] = []
        for w in sorted(ws, key=lambda w: w.y0):
            if lines and abs(lines[-1][0].y0 - w.y0) < 0.4 * lh:
                lines[-1].append(w)
            else:
                lines.append([w])
        role = " ".join(" ".join(x.text for x in sorted(l, key=lambda x: x.x0)) for l in lines).upper()
        count = int(_OCC.match(m.text).group(1).replace("l", "1").replace("I", "1"))
        allw = ws + [m]
        bbox = (min(w.x0 for w in allw), min(w.y0 for w in allw), max(w.x1 for w in allw), max(w.y1 for w in allw))
        out.append(RoomLabel(roles=[role], counts=[count], bbox=tuple(round(v, 1) for v in bbox),
                             raw=f"{role} ({count})", score=min(w.score for w in allw)))
    return sorted(out, key=lambda r: (r.bbox[1], r.bbox[0]))


# ------------------------------------------------------------------ report text

_TEXT_FACTS = [
    # (pattern, space, parameter, unit) - fixed wordings seen in technical reports and particulars sheets
    (r"Marine Crew\s+(\d+)", "Ship", "crew", "persons"),
    (r"\bCrew number\s+(\d+)", "Ship", "crew", "persons"),
    (r"Science \+ Mar Techs number\s+(\d+)", "Ship", "scientific personnel berths", "persons"),
    (r"Total without Berthing Van number\s+(\d+)", "Ship", "total complement", "persons"),
    (r"Endurance days\s+(\d+)", "Ship", "endurance", "days"),
    (r"operations for a\s+minimum of (\d+) days", "Ship", "endurance", "days"),
    (r"Length \(overall\) ft\s+([\d.]+)", "Ship", "length overall", "ft"),
    (r"Total Complement\s+(\d+)", "Ship", "total complement", "persons"),
    (r"mess room can\s+accommodate up to (\d+)\s+persons", "Mess room", "messroom seats", "persons"),
    (r"accommodations are provided for\s+(\d+)\s+persons", "Ship", "persons accommodated", "persons"),
    (r"(\d+)\s+single and\s+\d+\s+double staterooms", "Accommodation", "single staterooms", "rooms"),
    (r"\d+\s+single and\s+(\d+)\s+double staterooms", "Accommodation", "double staterooms", "rooms"),
]


def text_facts(pages: list[str]) -> list[tuple[str, str, str, float, str, int, str]]:
    out, seen = [], set()
    for n, t in enumerate(pages, start=1):
        flat = re.sub(r"\s+", " ", t)
        for pat, space, param, unit in _TEXT_FACTS:
            for m in re.finditer(pat, flat, re.I):
                if param in seen:
                    continue
                seen.add(param)
                start = max(0, flat.rfind(". ", 0, m.start()) + 2)
                end = flat.find(". ", m.end())
                sentence = flat[start : end + 1 if end > 0 else len(flat)].strip()
                quote = sentence if len(sentence) <= 200 else flat[max(0, m.start() - 60) : m.end() + 20]
                out.append((space, param, unit, float(m.group(1)), "", n, quote.strip()))
    return out


# ------------------------------------------------------------------ document


def extract(path: Path, pages: list[int] | None = None, doc_label: str | None = None,
            progress=None) -> Extraction:
    import pdfplumber

    path = Path(path)
    label = doc_label or path.stem
    ex = Extraction(file=str(path), doc_label=label)
    with pdfplumber.open(path) as pdf:
        texts = [(p.extract_text() or "") for p in pdf.pages]
    rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)

    # 1. stated facts from the text
    for i, (space, param, unit, value, _, page, sentence) in enumerate(text_facts(texts), start=1):
        ex.facts.append(Fact(item_id=f"T{i:02d}", space=space, parameter=param, value=value, unit=unit,
                             source=f"{label}, p.{page}: \"{sentence}\"", source_file=rel, source_page=page,
                             checkable=False))

    # 2. GA drawings: pages with little text (scans) or a GA title block
    cand = pages or [i + 1 for i, t in enumerate(texts) if "GENERAL ARRANGEMENT" in t.upper() or len(t.strip()) < 40]
    n = 0
    for page in cand:
        if progress:
            progress(page)
        words = ocr_page(path, page)
        meta = drawing_meta(words)
        if not meta["is_ga"]:
            continue
        rooms = room_labels(words)
        loose = getattr(room_labels, "unlabelled", [])
        ex.drawings.append({"page": page, **meta, "rooms": len(rooms), "berths": sum(r.persons for r in rooms),
                            "roles_without_count": sorted({w.text for w in loose}),
                            "words": [w.text for w in words]})
        if loose:
            ex.findings.append(f"p.{page} Dwg {meta['drawing']}: role label(s) without a berth count: "
                               f"{', '.join(sorted({w.text for w in loose}))} - those berths are not counted.")
        for r in rooms:
            n += 1
            where = f"Dwg {meta['drawing']} " if meta["drawing"] else ""
            ex.facts.append(Fact(
                item_id=f"G{n:02d}",
                space=f"{meta['deck']} sleeping room ({r.group}): {' + '.join(r.roles).title()}",
                parameter="persons berthed per sleeping room",
                value=float(r.persons),
                unit="persons",
                source=f"{label}, p.{page}, {where}{meta['title'].title()}: label \"{r.raw}\" (OCR)",
                notes=r.group + ("; low OCR confidence - verify on the drawing" if r.score < 0.85 else ""),
                source_file=rel,
                source_page=page,
                source_bbox=",".join(f"{v:g}" for v in r.bbox),
            ))

    # 3. consistency between drawing and text (for an engineer to look at, not a rule verdict)
    berths = sum(d["berths"] for d in ex.drawings)
    stated = {f.parameter: f for f in ex.facts if f.item_id.startswith("T")}
    if ex.drawings and "total complement" in stated:
        c = stated["total complement"]
        if berths != c.value:
            ex.findings.append(
                f"Berths labelled on the GA drawings: {berths}; total complement in the text: {c.value:g} "
                f"(p.{c.source_page}). " + (
                    "Rooms labelled without a berth count (see above) may account for the difference."
                    if berths < c.value and any(d["roles_without_count"] for d in ex.drawings)
                    else "Fewer berths than persons: check vans or temporary berths." if berths < c.value
                    else "More berths than persons."))
        else:
            ex.findings.append(f"Berths on the GA drawings ({berths}) match the stated complement ({c.value:g}).")
    if "single staterooms" in stated and "double staterooms" in stated and ex.drawings:
        s, d = stated["single staterooms"].value, stated["double staterooms"].value
        rooms = [f for f in ex.facts if f.item_id.startswith("G")]
        got_s, got_d = sum(f.value == 1 for f in rooms), sum(f.value == 2 for f in rooms)
        ex.findings.append(f"Text: {s:g} single and {d:g} double staterooms; read from the drawings: {got_s} single, "
                           f"{got_d} double{'' if (got_s, got_d) == (s, d) else ' - check the OCR result and the drawing'}.")
    from .findings import rule_findings

    ex.findings += rule_findings(ex)
    return ex


def facts_to_csv(facts: list[Fact], checkable_only: bool = True) -> str:
    import csv
    import io

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["item_id", "space", "parameter", "value", "unit", "source", "notes", "source_file", "source_page",
                "source_bbox"])
    for f in facts:
        if checkable_only and not f.checkable:
            continue
        w.writerow([f.item_id, f.space, f.parameter, f"{f.value:g}", f.unit, f.source, f.notes, f.source_file,
                    f.source_page or "", f.source_bbox])
    return out.getvalue()
