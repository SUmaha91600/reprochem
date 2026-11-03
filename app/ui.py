"""Demo: one paper, the local student's card next to the teacher's.

    bash scripts/demo.sh            # Qwen3 student + LoRA, local
    uv run streamlit run app/ui.py  # with the model set in config.yaml

Every value comes with the sentence that proves it. A field missing from the
paper is shown as missing. The teacher column shows Claude's labels on the same
passages: the gap between the two columns is what the benchmark measures.
"""
import json
import os
import sys
import time
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.pipeline import CFG, answer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ("functional", "basis", "dispersion", "solvation", "charge", "multiplicity", "software")


@st.cache_data
def teacher_cards() -> dict:
    p = ROOT / "data/teacher/doc_cards.jsonl"
    if not p.exists():
        return {}
    return {json.loads(l)["paper_id"]: json.loads(l)["card"] for l in p.open(encoding="utf-8") if l.strip()}


@st.cache_data
def gold() -> dict:
    p = ROOT / "eval/testset.jsonl"
    if not p.exists():
        return {}
    return {json.loads(l)["paper_id"]: json.loads(l)["fields"] for l in p.open(encoding="utf-8") if l.strip()}


def norm(v) -> str:
    return str(v).strip().upper().replace(" ", "").replace("-", "")


st.set_page_config(page_title="ReproChem", layout="wide")
st.title("ReproChem")
adapter = os.environ.get("REPROCHEM_ADAPTER") or "none"
st.caption(f"Student: {CFG['model']['name']} · LoRA: {adapter} · everything runs on this machine")

with st.sidebar:
    gold_ids = sorted(gold())
    source = st.radio("Document", ["Gold set paper", "Upload a file"])
    if source == "Gold set paper" and gold_ids:
        pid = st.selectbox("Paper", gold_ids)
        text = (ROOT / f"data/papers/md/{pid}.md").read_text(encoding="utf-8", errors="replace")
    else:
        up = st.file_uploader("Markdown or text", type=["md", "txt"])
        pid, text = (Path(up.name).stem, up.read().decode("utf-8", "replace")) if up else (None, None)
    go = st.button("Extract", type="primary", disabled=text is None)

if go and text:
    t0 = time.time()
    with st.spinner("BM25 retrieval, then 7 calls to the student…"):
        out = answer(text, pid, "O", 1, mode="bm25")
    st.write(f"**{time.time() - t0:.1f} s** for 7 fields, no network.")
    tcard = teacher_cards().get(pid, {})
    g = gold().get(pid, {})
    head = st.columns([1.1, 2.4, 1.4, 1.1])
    for h, c in zip(["Field", "Student (local)", "Teacher (Claude)", "Gold set"], head):
        c.markdown(f"**{h}**")
    for f in FIELDS:
        s = out["card"].get(f) or {}
        sv = s.get("value", "NOT_FOUND")
        tv = (tcard.get(f) or {}).get("value", "—") if tcard else "—"
        gv = g.get(f, "—")
        c1, c2, c3, c4 = st.columns([1.1, 2.4, 1.4, 1.1])
        c1.markdown(f"`{f}`")
        if sv == "NOT_FOUND":
            c2.markdown(":red[NOT_FOUND]")
        else:
            c2.markdown(f"**{sv}**")
            if s.get("citation"):
                c2.caption("« " + s["citation"]["quote"][:220] + " »")
        mark = "" if tv == "—" else (" ✓" if norm(tv) == norm(sv) else " ✗")
        c3.markdown(f"{tv}{mark}")
        if gv != "—":
            c4.markdown(f"{gv}" + (" ✓" if norm(gv) == norm(sv) else " ✗"))
        else:
            c4.markdown("—")
    st.divider()
    if out["spec"] is None:
        st.warning("Compilation blocked: " + out["compile_note"])
    else:
        st.success("Complete protocol: spec compiled")
        st.json(out["spec"])
