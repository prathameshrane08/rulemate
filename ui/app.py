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
from rulemate.config import CLAUSES_FILE, ROOT  # noqa: E402
from rulemate.guardrails import CITATION_RE  # noqa: E402
from ui.backend import Backend  # noqa: E402

st.set_page_config(page_title="RuleMate", page_icon="⚓", layout="wide")

DEMO_QUESTIONS = [
    "What is the minimum corridor width?",
    "How is the corridor width calculated when many people use it?",
    "What does 13.3.2.1 say?",
    "What is the required size of a helicopter landing area?",
]
PROVIDERS = ["groq,ollama", "groq", "ollama", "openai"]
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
        tag = " · :orange[SYNTHETIC]" if d.get("synthetic") else ""
        st.markdown(f"- `{d['doc']}`  \n  {d['n_clauses']} clauses · {d['n_tables']} tables · {d['style']}{tag}")
    st.divider()
    provider = st.selectbox("LLM provider", PROVIDERS, help="Comma = try in order (fallback on error or timeout)")
    use_cache = st.toggle("Use answer cache", value=True, help="Cached answers return instantly (demo safety)")
    st.caption(f"Retrieval: {health['retrieval_mode']} · Backend: {backend.mode}")
    st.divider()
    st.markdown("**Demo questions**")
    for q in DEMO_QUESTIONS:
        if st.button(q, key=f"demo-{q}", width="stretch"):
            ss.pending = q
    if st.button("Clear chat", type="tertiary"):
        ss.messages, ss.selected = [], None

st.markdown("# RuleMate")
st.caption("Every answer is traceable to a clause, or it says *not found in the provided rules*.")
if health.get("synthetic_data"):
    st.warning(
        "Development data: the loaded rules include **SAMPLE_SYNTHETIC_rules**, an invented document. "
        "Nothing shown here is a real regulation.",
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
            ans = backend.ask(question, provider, use_cache)
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


# ------------------------------------------------------------------ compliance tab (step 5)

with tab_check:
    st.info("Compliance check: upload design values (CSV) and get PASS / FAIL / NEEDS REVIEW per item, "
            "decided in code against limits extracted from the clauses.", icon=":material/construction:")
    sample = ROOT / "data" / "designs" / "sample_design.csv"
    if sample.exists():
        st.caption("Sample design values (synthetic):")
        st.dataframe(pd.read_csv(sample), hide_index=True, width="stretch")


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
