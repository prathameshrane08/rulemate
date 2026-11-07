"""RuleMate Streamlit UI.

    streamlit run ui/app.py

Uses the FastAPI backend if it is running (uvicorn rulemate.api:app), otherwise calls the code in-process.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from rulemate.answer import Answer  # noqa: E402
from rulemate.compliance.check import RowResult  # noqa: E402
from rulemate.config import CLAUSES_FILE, ROOT  # noqa: E402
from rulemate.guardrails import CITATION_RE  # noqa: E402
from ui.backend import Backend  # noqa: E402

st.set_page_config(page_title="RuleMate", page_icon="⚓", layout="wide")

from rulemate.config import DEMO_QUESTIONS  # noqa: E402  (question, rule documents)
PROVIDERS = ["groq,ollama", "gemini,ollama", "groq", "gemini", "ollama", "openai"]
BADGES = {
    "verified": ("Verified", ":material/verified:", "green"),
    "excerpts": ("Excerpts only", ":material/format_quote:", "orange"),
    "not_found": ("Not found in the rules", ":material/search_off:", "gray"),
}

if not CLAUSES_FILE.exists():
    st.error("No rule index yet. Run `python -m rulemate ingest` first.")
    st.stop()

ss = st.session_state
ss.setdefault("messages", [])  # list of {"role": "user"|"assistant", "content": str | Answer}
ss.setdefault("selected", None)  # index of the answer shown in the Sources panel
ss.setdefault("clause_nav", [])  # clause dialog history (uids)
ss.setdefault("open_dialog", False)
ss.setdefault("pending", None)
ss.setdefault("seen_selection", {})
if "backend" not in ss:
    ss.backend = Backend()
backend: Backend = ss.backend


# ------------------------------------------------------------------ clause dialog


def open_clause(uid: str) -> None:
    ss.clause_nav = [uid]
    ss.open_dialog = True


def _nav(uid: str) -> None:
    ss.clause_nav.append(uid)


def _back() -> None:
    if len(ss.clause_nav) > 1:
        ss.clause_nav.pop()


@st.dialog("Clause", width="large")
def clause_dialog() -> None:
    view = backend.clause(ss.clause_nav[-1])
    if view is None:
        st.error("Clause not found in the current index.")
        return
    c = view.clause
    if len(ss.clause_nav) > 1:
        st.button("← Back", on_click=_back, key="dlg-back")
    if c.synthetic:
        st.warning("SYNTHETIC sample rule, invented for development. Not a real regulation.", icon=":material/science:")
    st.markdown(f"### § {c.clause_id}" + (f" — {c.title}" if c.title else ""))
    crumbs = " › ".join(c.path) if c.path else ""
    st.caption(f"**{c.doc}**" + (f" · page {c.page}" if c.page else "") + (f" · {crumbs}" if crumbs else ""))
    st.markdown(c.text)

    def ref_buttons(label: str, ids: list[str], key: str) -> None:
        if not ids:
            return
        st.markdown(f"**{label}**")
        cols = st.columns(min(len(ids), 4))
        for i, cid in enumerate(ids):
            cols[i % len(cols)].button(cid, key=f"{key}-{i}", on_click=_nav, args=(f"{c.doc}::{cid}",),
                                       width="stretch")

    ref_buttons("Refers to", c.refs, "ref")
    ref_buttons("Sub-clauses", view.children, "child")
    ref_buttons("Referenced by", view.referenced_by, "by")
    if c.unresolved_refs:
        st.caption("Unresolved references: " + ", ".join(c.unresolved_refs))


# ------------------------------------------------------------------ sidebar

health = backend.health()
with st.sidebar:
    st.markdown("## ⚓ RuleMate")
    st.caption("Ship design rules, answered with clause citations.")
    st.markdown("**Rule documents**")
    for d in health["documents"]:
        tag = " · :orange[SYNTHETIC]" if d.get("synthetic") else " · :green[real text]"
        st.markdown(f"- `{d['doc']}`  \n  {d['n_clauses']} clauses · {d['n_tables']} tables · {d['style']}{tag}")
    doc_names = [d["doc"] for d in health["documents"]]
    ask_docs = st.multiselect("Rule sets for questions", doc_names, key="ask_docs",
                              help="The rules that apply to the vessel you are working on. Empty = all.")
    st.divider()
    provider = st.selectbox("LLM provider", PROVIDERS, help="Comma = try in order (fallback on error or timeout)")
    use_cache = st.toggle("Use answer cache", value=True, help="Cached answers return instantly (demo safety)")
    st.caption(f"Retrieval: {health['retrieval_mode']} · Backend: {backend.mode}")
    st.divider()
    st.markdown("**Demo questions**")
    def _demo(q: str, docs: list[str]) -> None:
        ss.pending = q
        ss.ask_docs = [d for d in docs if d in doc_names]

    for q, qdocs in DEMO_QUESTIONS:
        st.button(q, key=f"demo-{q}", width="stretch", on_click=_demo, args=(q, qdocs),
                  help=f"Asked against: {', '.join(qdocs)}")
    if st.button("Clear chat", type="tertiary"):
        ss.messages, ss.selected = [], None

st.markdown("# RuleMate")
st.caption("Every answer is traceable to a clause, or it says *not found in the provided rules*.")
if health.get("synthetic_data"):
    st.warning(
        "Development data: **SAMPLE_SYNTHETIC_rules** is an invented document; anything cited from it is not a real "
        "regulation. Other documents marked *real text* are copied verbatim from the official source.",
        icon=":material/science:",
    )

tab_ask, tab_check, tab_browse = st.tabs(["💬 Ask the rules", "✅ Compliance check", "📚 Browse clauses"])


# ------------------------------------------------------------------ ask tab


def render_text(text: str) -> str:
    """Show citations as compact code chips; the buttons below the answer open them."""
    return CITATION_RE.sub(lambda m: f"`§ {m.group(2).strip()}`", text)


def render_answer(ans: Answer, i: int) -> None:
    label, icon, color = BADGES[ans.status]
    head = st.columns([3, 1])
    with head[0]:
        st.badge(label, icon=icon, color=color)
        if ans.synthetic:
            st.badge("synthetic data", icon=":material/science:", color="orange")
    with head[1]:
        if st.button("Sources →", key=f"src-{i}", type="tertiary"):
            ss.selected = i
    st.markdown(render_text(ans.text))
    if ans.citations:
        cols = st.columns(min(len(ans.citations), 4))
        for j, c in enumerate(ans.citations):
            cols[j % len(cols)].button(
                f"📄 {c.clause_id}", key=f"cite-{i}-{j}", on_click=open_clause, args=(c.uid,),
                help=f"{c.doc} · {c.title}" + (f" · p. {c.page}" if c.page else ""), width="stretch",
            )
    meta = [f"confidence {ans.confidence} ({ans.top_score:.2f})"]
    if ans.model:
        meta.append(ans.model)
    if ans.attempts:
        meta.append(f"{ans.attempts} attempt(s), {ans.rejected_attempts} rejected by guardrails")
    meta.append("cached" if ans.cached else f"{ans.latency_ms / 1000:.1f} s")
    st.caption(" · ".join(meta))
    if ans.note and ans.status != "verified":
        st.caption(f"ℹ️ {ans.note}")
    if ans.violations:
        with st.expander("Why the generated answer was rejected"):
            for v in ans.violations:
                st.markdown(f"- {v}")
    if ans.status == "not_found":  # outside the loaded rules: a general answer, clearly labelled, Groq / Ollama only
        key = f"general-{i}"
        if key not in ss and st.button("Answer from general knowledge", key=f"gbtn-{i}", icon=":material/public:"):
            from rulemate.general import general_answer

            with st.spinner("Asking the bot (Groq / Ollama)…"):
                ss[key] = general_answer(ans.question)
        g = ss.get(key)
        if g:
            st.badge("general knowledge", icon=":material/public:", color="violet")
            st.warning(f"{g['label']}. Not checked against any rule text; accuracy not measured. "
                       "Confirm in the governing rules before using it in a design.")
            st.markdown(g["text"] if g["ok"] else g["error"])
            if g["model"]:
                st.caption(g["model"])


def sources_panel(ans: Answer) -> None:
    st.markdown("#### Sources")
    st.caption(f"Retrieved for: *{ans.question}*")
    if not ans.sources:
        st.info("No clauses retrieved.")
        return
    cited = {c.uid for c in ans.citations}
    rows = [
        {
            "cited": "✓" if h.clause.uid in cited else "",
            "clause": h.clause.clause_id,
            "title": h.clause.title,
            "how": h.source + (f" ← {h.via}" if h.via else ""),
            "score": round(h.score, 3),
            "cosine": h.cosine,
            "bm25 #": None if h.bm25_rank is None else h.bm25_rank + 1,
            "dense #": None if h.dense_rank is None else h.dense_rank + 1,
        }
        for h in ans.sources
    ]
    key = f"srcdf-{ss.selected}"
    ev = st.dataframe(pd.DataFrame(rows), hide_index=True, on_select="rerun", selection_mode="single-row",
                      key=key, width="stretch")
    sel = tuple(ev.selection.rows)
    if sel and ss.seen_selection.get(key) != sel:
        ss.seen_selection[key] = sel
        open_clause(ans.sources[sel[0]].clause.uid)
    st.caption("Click a row to read the clause. how: id = clause ID in question, search = hybrid rank, "
               "xref = pulled in by a cross-reference, child = sub-clause of a matched heading.")


with tab_ask:
    question = st.chat_input("Ask about the rules, e.g. 'What is the maximum stair angle?' or 'what does 13.3.1 say'")
    question = question or ss.pending
    ss.pending = None
    if question:
        ss.messages.append({"role": "user", "content": question})
        with st.spinner("Retrieving clauses and checking the answer..."):
            ans = backend.ask(question, provider, use_cache, ss.get("ask_docs") or None)
        ss.messages.append({"role": "assistant", "content": ans})
        ss.selected = len(ss.messages) - 1

    chat_col, src_col = st.columns([3, 2], gap="large")
    with chat_col:
        if not ss.messages:
            st.info("Ask a question, or pick a demo question in the sidebar.")
        for i, m in enumerate(ss.messages):
            with st.chat_message(m["role"], avatar="🧑‍🔧" if m["role"] == "user" else "⚓"):
                if m["role"] == "user":
                    st.markdown(m["content"])
                else:
                    render_answer(m["content"], i)
    with src_col:
        if ss.selected is not None and ss.selected < len(ss.messages):
            sources_panel(ss.messages[ss.selected]["content"])


# ------------------------------------------------------------------ compliance tab

VERDICT_STYLE = {
    "PASS": "background-color: #d1fadf; color: #05603a; font-weight: 600",
    "FAIL": "background-color: #fee4e2; color: #b42318; font-weight: 600",
    "NEEDS REVIEW": "background-color: #fef0c7; color: #b54708; font-weight: 600",
    "NO RULE": "background-color: #eaecf0; color: #475467; font-weight: 600",
    "CHECK INPUT": "background-color: #eaecf0; color: #475467; font-weight: 600",
}
VERDICT_BADGE = {"PASS": ("PASS", ":material/check_circle:", "green"),
                 "FAIL": ("FAIL", ":material/cancel:", "red"),
                 "NEEDS REVIEW": ("NEEDS REVIEW", ":material/help:", "orange")}


def limit_buttons(res: RowResult, key: str) -> None:
    seen = []
    for lr in res.applied:
        if lr.limit.clause_uid not in seen:
            seen.append(lr.limit.clause_uid)
    if seen:
        cols = st.columns(min(len(seen), 4))
        for j, uid in enumerate(seen):
            cols[j % len(cols)].button(f"📄 {uid.split('::', 1)[1]}", key=f"{key}-{j}", on_click=open_clause,
                                       args=(uid,), width="stretch")


@st.cache_data(show_spinner=False)
def _evidence_png(path: str, page: int, bbox: str) -> bytes | None:
    """The part of the drawing a design value was read from, with the label boxed."""
    import io

    import pdfplumber

    try:
        x0, y0, x1, y1 = (float(v) for v in bbox.split(","))
        with pdfplumber.open(path) as pdf:
            pg = pdf.pages[page - 1]
            m = 70
            box = (max(0, x0 - m), max(0, y0 - m), min(pg.width, x1 + m), min(pg.height, y1 + m))
            im = pg.crop(box).to_image(resolution=170)
            im.draw_rect((x0 - 3, y0 - 3, x1 + 3, y1 + 3), stroke="#d62728", fill=(214, 39, 40, 30), stroke_width=3)
            buf = io.BytesIO()
            im.annotated.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return None


def picture_input() -> list:
    """Interior designer flow: drop a picture, Gemini reads the written values, code confirms and checks them."""
    import os

    st.caption("Drop a screenshot from your design tool, a drawing excerpt, a sketch or a photo with dimensions "
               "written on it. **Gemini** reads each value and what it measures; code confirms the value is written "
               "at that spot (local OCR) and checks it against the rules. Gemini never decides PASS or FAIL.")
    c1, c2 = st.columns([3, 1])
    up = c1.file_uploader("Picture", type=["png", "jpg", "jpeg", "webp"], label_visibility="collapsed")
    sample = ROOT / "data" / "designs" / "pictures" / "SYNTHETIC_accessible_cabin_sketch.png"
    if c2.button("Use sample sketch", help="SYNTHETIC accessible cabin sketch with invented values",
                 disabled=not sample.exists()):
        ss.picture = ("SYNTHETIC_accessible_cabin_sketch.png", sample.read_bytes())
    if up is not None:
        ss.picture = (up.name, up.getvalue())
    pic = ss.get("picture")
    if not pic:
        return []
    if not os.getenv("GEMINI_API_KEY"):
        st.warning("Set GEMINI_API_KEY in .env to read pictures.")
        return []
    name, data = pic
    key = f"pic-{hash(data)}"
    if key not in ss:
        from rulemate.design.picture import read_picture
        from rulemate.llm import make_provider

        llm = make_provider("gemini")
        llm.model = os.getenv("GEMINI_VISION_MODEL", llm.model)
        llm.timeout = max(llm.timeout, 240)
        with st.spinner("Gemini is reading the picture; code is confirming each value..."):
            try:
                ss[key] = read_picture(data, llm)
            except Exception as e:
                st.error(f"Gemini could not read the picture: {str(e)[:200]}")
                return []
    values, png = ss[key]
    ss.picture_png = {name: png}
    i1, i2 = st.columns([2, 3])
    i1.image(png, caption=name, width="stretch")
    i2.markdown(f"**Read by Gemini:** {len(values)} values, **{sum(v.confirmed for v in values)} confirmed** on the "
                "picture and checked; the rest are not used.")
    i2.dataframe(pd.DataFrame([{
        "space": v.space, "measures": v.parameter, "written": v.value_text, "unit": v.unit,
        "status": "confirmed" if v.confirmed else "not found on the picture - not used",
        "note": "; ".join(v.notes),
    } for v in values]), hide_index=True, width="stretch", height=table_height(len(values)))
    from rulemate.design.picture import to_rows

    return to_rows(values, name)


def table_height(n: int, cap: int = 900) -> int:
    """Tall enough to show every row (35 px per row + header), up to ``cap``."""
    return min(cap, 38 + 35 * max(1, n))


def evidence_image(r) -> None:
    if not (r.source_file and r.source_page and r.source_bbox):
        return
    if r.source_file.startswith("upload:"):  # a picture checked in this session
        png = (ss.get("picture_png") or {}).get(r.source_file[7:])
        if png:
            import io

            from PIL import Image, ImageDraw

            x0, y0, x1, y1 = (int(float(v)) for v in r.source_bbox.split(","))
            im = Image.open(io.BytesIO(png)).convert("RGB")
            ImageDraw.Draw(im).rectangle((x0 - 6, y0 - 6, x1 + 6, y1 + 6), outline=(214, 39, 40), width=4)
            m = 160
            st.image(im.crop((max(0, x0 - m), max(0, y0 - m), min(im.width, x1 + m), min(im.height, y1 + m))),
                     caption=f"{r.source_file[7:]}: the value this check used", width=420)
        return
    path = ROOT / r.source_file
    if not path.exists():
        st.caption(f"(source document {r.source_file} not on this machine)")
        return
    png = _evidence_png(str(path), r.source_page, r.source_bbox)
    if png:
        st.image(png, caption=f"{r.source_file}, page {r.source_page}: the label this value was read from", width=420)


def row_detail(res: RowResult, idx: int) -> None:
    label, icon, color = VERDICT_BADGE[res.verdict]
    r = res.row
    st.badge(label, icon=icon, color=color)
    st.markdown(f"**{r.item_id} · {r.space}** — {r.parameter}: **{r.display}**")
    if r.source:
        st.caption(f":material/architecture: Design value from: {r.source}")
    evidence_image(r)
    st.markdown("**Decided by code**")
    st.markdown(render_text(res.reason))
    limit_buttons(res, f"lim-{idx}")
    if res.explanation_status == "verified":
        st.markdown("**Explanation** :green-badge[:material/verified: checked]")
        st.markdown(render_text(res.explanation))
    elif res.explanation_status == "rejected":
        st.caption("The LLM explanation failed the checks and is not shown; the code result above is complete.")
        with st.expander("Why it was rejected"):
            for v in res.explanation_violations:
                st.markdown(f"- {v}")
    if res.limits:
        with st.expander("Limits considered"):
            st.dataframe(pd.DataFrame([{
                "clause": lr.limit.clause_id, "limit": lr.limit.describe(), "role": lr.role,
                "only for": lr.limit.qualifier or "", "condition": lr.limit.condition or "",
                "value in limit unit": lr.value_in_limit_unit, "outcome": lr.outcome or "",
                "match": lr.similarity, "extracted by": lr.limit.method,
            } for lr in res.limits]), hide_index=True, width="stretch")


def rule_table_editor() -> None:
    from rulemate.compliance.limits import Limit
    from rulemate.compliance.units import UnitError, parse_unit

    table = backend.rule_table()
    st.caption(f"{len(table.limits)} limits extracted ({table.model or 'regex'}), "
               f"{len(table.rejected)} proposals rejected by validation. Edit a row and save to override it "
               "(marked as manual). Every limit links back to its clause.")
    cols = ["id", "clause_id", "parameter", "qualifier", "condition", "comparator", "value", "unit", "method"]
    df = pd.DataFrame([{k: getattr(l, k) for k in cols} for l in table.limits], columns=cols)
    edited = st.data_editor(
        df, hide_index=True, width="stretch", key="limits-editor",
        disabled=["id", "clause_id", "method"],
        column_config={
            "id": None,
            "comparator": st.column_config.SelectboxColumn(options=[">=", "<=", ">", "<"], required=True),
            "value": st.column_config.NumberColumn(required=True),
        },
    )
    c1, c2 = st.columns(2)
    if c1.button("Save edits", icon=":material/save:"):
        by_id = {l.id: l for l in table.limits}
        errors, new = [], []
        for rec in edited.to_dict("records"):
            old = by_id[rec["id"]]
            changes = {k: (rec[k] if not (isinstance(rec[k], float) and pd.isna(rec[k])) else None)
                       for k in ("parameter", "qualifier", "condition", "comparator", "value", "unit")}
            if any(changes[k] != getattr(old, k) for k in changes):
                try:
                    parse_unit(changes["unit"] or "")
                except UnitError as e:
                    errors.append(f"{old.clause_id}: {e}")
                    new.append(old)
                    continue
                new.append(Limit(**{**old.model_dump(), **changes, "method": "manual"}))
            else:
                new.append(old)
        table.limits = new
        backend.save_rule_table(table)
        st.success("Saved.") if not errors else st.error("; ".join(errors))
    if c2.button("Re-extract from clauses", icon=":material/refresh:", help="Discards manual edits"):
        with st.spinner("Extracting limits..."):
            backend.rule_table(rebuild=True, provider=provider)
        st.rerun()


with tab_check:
    from rulemate.compliance.check import DesignRow, read_design_csv, results_to_csv

    st.caption("Verdicts are computed in code: limits extracted from the clauses, units converted with pint, "
               "values compared. The LLM only explains a verdict, and its explanation is checked too.")
    ss.setdefault("extra_rows", [])
    ss.setdefault("check_results", None)

    from rulemate.compliance.service import rule_documents

    # example designs and the rule sets that apply to that vessel type
    designs = {
        "RCRV – measured from its GA (vector CAD)": ("rcrv_from_ga.csv", ["46CFR190"]),
        "Accessible stateroom – interior design, ADA (US units)": ("accessible_stateroom_example.csv", ["36CFR1191AppD"]),
        "NOAA research ship – read from its GA drawing": ("noaa_swath_from_ga.csv", ["46CFR190"]),
        "Research vessel example – 46 CFR 190 (US units)": ("rcrv_example_design.csv", ["46CFR190"]),
        "Cruise-ship sample – synthetic rules": ("sample_design.csv", ["SAMPLE_SYNTHETIC_rules"]),
    }
    all_docs = rule_documents()
    PICTURE = "Picture of a layout (Gemini)"
    src = st.radio("Design values", [PICTURE, *designs, "Upload CSV"], horizontal=True,
                   help="Picture: a screenshot, drawing excerpt, sketch or photo with dimensions written on it.")
    rows: list[DesignRow] = []
    default_docs = all_docs
    if src == PICTURE:
        rows, default_docs = picture_input(), ["36CFR1191AppD"]
    elif src == "Upload CSV":
        up = st.file_uploader("CSV with columns: item_id, space, parameter, value, unit, source, notes. "
                              "Values may be written as 3'-6\" or 39 1/2.", type=["csv"])
        if up is not None:
            try:
                rows = read_design_csv(up.getvalue())
            except ValueError as e:
                st.error(str(e))
    else:
        fname, default_docs = designs[src]
        path = ROOT / "data" / "designs" / fname
        if path.exists():
            rows = read_design_csv(path.read_bytes())
            fj = path.with_suffix(".findings.json")
            if fj.exists():
                import json as _json

                info = _json.loads(fj.read_text())
                with st.expander(f"Read from **{info['document']}**: {len(rows)} checkable values, "
                                 f"{len(info['findings'])} findings for an engineer", expanded=False):
                    for d in info["drawings"]:
                        if d["rooms"]:
                            st.markdown(f"- GA p.{d['page']}, Dwg `{d['drawing']}` {d['title'].title()}: "
                                        f"{d['rooms']} berth labels read by OCR, {d['berths']} berths")
                    gem = [dict(page=d["page"], **r) for d in info["drawings"] for r in d.get("gemini", [])]
                    if gem:
                        st.markdown(f"**Read by Gemini, confirmed in code**: {sum(r['confirmed'] for r in gem)} of "
                                    f"{len(gem)} readings found on the drawing at the reported position")
                        show = st.segmented_control(
                            "Show", ["All", "Cabins, hospital, stairs", "Not confirmed"], default="All",
                            key=f"gem-filter-{src}")
                        pick_g = [r for r in gem if show in (None, "All")
                                  or (show == "Not confirmed" and not r["confirmed"])
                                  or (show == "Cabins, hospital, stairs" and r["kind"] in ("stateroom", "hospital", "stairway"))]
                        st.dataframe(pd.DataFrame([{
                            "page": r["page"], "label": " ".join(r["label"].split()), "room no.": r["room_number"] or "",
                            "kind": r["kind"], "berths": r["berths"],
                            "status": ("confirmed" if r["confirmed"] else "Gemini only - not used")
                                      + (", berths from label" if r["berths_confirmed"] else ""),
                        } for r in pick_g]), hide_index=True, width="stretch", height=table_height(len(pick_g)),
                            column_config={"label": st.column_config.TextColumn(width="large"),
                                           "status": st.column_config.TextColumn(width="medium")})
                    st.markdown("**Findings** (not verdicts: for an engineer to confirm)")
                    for x in info["findings"]:
                        st.markdown(f"- {render_text(x)}")
                    st.caption("Created with `python -m rulemate design <pdf> --out <csv>`.")
        else:
            st.warning(f"{fname} not found in data/designs/.")
    docs = st.multiselect("Rule sets that apply to this vessel", all_docs,
                          default=[d for d in default_docs if d in all_docs], key=f"docs-{src}",
                          help="Only limits from these documents are checked. Empty = all documents.")

    with st.expander("Add a single value"):
        with st.form("one-row", clear_on_submit=True, border=False):
            f1, f2, f3, f4 = st.columns([3, 3, 1.3, 1])
            sp = f1.text_input("Space", placeholder="Deck 4 corridor")
            pa = f2.text_input("Parameter", placeholder="corridor clear width")
            va_raw = f3.text_input("Value", placeholder="1200 or 3'-6\"")
            un = f4.text_input("Unit", placeholder="mm")
            if st.form_submit_button("Add") and pa and va_raw:
                from rulemate.compliance.units import parse_value

                va, un = parse_value(va_raw, un)
                ss.extra_rows.append(DesignRow(item_id=f"F{len(ss.extra_rows) + 1}", space=sp, parameter=pa,
                                               value=va, unit=un, raw_value=va_raw, source="entered by hand"))
    rows = rows + ss.extra_rows
    if ss.extra_rows:
        st.caption(f"{len(ss.extra_rows)} value(s) added by hand.")
        if st.button("Clear added values", type="tertiary"):
            ss.extra_rows = []
            st.rerun()

    o1, o2 = st.columns([1.6, 3])
    explain = o2.toggle("LLM explanations (checked by guardrails)", value=False,
                        help="Slower: one LLM call per row. Verdicts do not change.")
    if o1.button("Run check", type="primary", disabled=not rows, icon=":material/play_arrow:"):
        with st.spinner(f"Checking {len(rows)} values..."):
            ss.check_results = backend.check(rows, explain, provider, docs or None)

    results = ss.check_results
    if results:
        counts = {v: sum(r.shown_verdict == v for r in results)
                  for v in ("PASS", "FAIL", "NEEDS REVIEW", "NO RULE", "CHECK INPUT")}
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Items", len(results))
        m2.metric("PASS", counts["PASS"])
        m3.metric("FAIL", counts["FAIL"])
        m4.metric("NEEDS REVIEW", counts["NEEDS REVIEW"], help="A rule applies, but a condition must be confirmed")
        m5.metric("NO RULE / CHECK INPUT", f'{counts["NO RULE"]} / {counts["CHECK INPUT"]}',
                  help="NO RULE: none of the loaded rule texts limits this value. CHECK INPUT: the value is not a "
                       "number or has no unit.")
        if any(r.synthetic for r in results):
            st.caption(":orange[Limits come from SYNTHETIC sample rules.]")
        def deciding(r):
            """The limit that decided the verdict: the failed one, else the one with the smallest margin."""
            ap = r.applied
            if not ap:
                return None
            failed = [x for x in ap if x.outcome == "fail" and x.role == "applied"]
            if failed:
                return failed[0]
            def margin(x):
                v = x.value_in_limit_unit
                return abs(v - x.limit.value) / abs(x.limit.value) if v is not None and x.limit.value else 9e9
            return min(ap, key=margin)

        def short(r):
            d = deciding(r)
            return (f"{d.limit.describe()}{' (if …)' if d.limit.condition else ''}", d.limit.clause_id) if d else ("", "")

        full_text = st.toggle("Show full text (every limit checked, design source)", key="full-table")
        rows_t = []
        for r in results:
            lim, cl = short(r)
            row_t = {"Item": r.row.item_id, "Verdict": r.shown_verdict,
                     "Checked": f"{r.row.parameter} — {r.row.space}" if r.row.space else r.row.parameter,
                     "Value": r.row.display, "Deciding limit": f"{lim} [{cl}]" if cl else "no matching limit"}
            if full_text:
                row_t["All limits checked"] = "; ".join(
                    f"{x.limit.describe()}{' (if …)' if x.limit.condition else ''} [{x.limit.clause_id}]" for x in r.applied)
                row_t["Design value from"] = r.row.source
            rows_t.append(row_t)
        # a wrapped table always fits the page width: nothing hides off to the right on a laptop screen
        st.table(pd.DataFrame(rows_t).style.map(lambda v: VERDICT_STYLE.get(v, ""), subset=["Verdict"])
                 .hide(axis="index"))
        st.download_button("Download results (CSV)", results_to_csv(results), file_name="rulemate_compliance.csv",
                           mime="text/csv", icon=":material/download:")
        st.divider()
        first_fail = next((i for i, r in enumerate(results) if r.verdict == "FAIL"), 0)
        pick = st.selectbox("Show how the verdict was reached for", range(len(results)), index=first_fail,
                            format_func=lambda i: f"{results[i].row.item_id} · {results[i].verdict} · "
                                                  f"{results[i].row.parameter} — {results[i].row.space}"[:110],
                            key="detail-pick")
        row_detail(results[pick], pick)

    st.divider()
    with st.expander("Rule table: limits extracted from the clauses"):
        rule_table_editor()


# ------------------------------------------------------------------ browse tab

with tab_browse:
    clauses = backend.clauses()
    docs = sorted({c.doc for c in clauses})
    c1, c2, c3 = st.columns([2, 3, 1])
    doc = c1.selectbox("Document", ["All"] + docs)
    filt = c2.text_input("Filter", placeholder="clause ID or words, e.g. 13.3 or stair")
    hide_headings = c3.toggle("Hide headings", value=True)
    shown = [
        c for c in clauses
        if (doc == "All" or c.doc == doc)
        and (not hide_headings or c.kind != "heading")
        and (not filt or filt.lower() in f"{c.clause_id} {c.title} {c.text}".lower())
    ]
    df = pd.DataFrame(
        [{"clause": c.clause_id, "kind": c.kind, "page": c.page, "title": c.title,
          "text": c.text.replace("\n", " ")[:160], "refs": ", ".join(c.refs)} for c in shown]
    )
    ev = st.dataframe(df, hide_index=True, on_select="rerun", selection_mode="single-row", key="browse",
                      width="stretch", height=520)
    sel = tuple(ev.selection.rows)
    if sel and ss.seen_selection.get("browse") != (sel, doc, filt):
        ss.seen_selection["browse"] = (sel, doc, filt)
        open_clause(shown[sel[0]].uid)
    st.caption(f"{len(shown)} of {len(clauses)} clauses. Click a row to open it.")


if ss.open_dialog:
    ss.open_dialog = False
    clause_dialog()
