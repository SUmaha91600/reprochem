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
from urllib.parse import quote

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.guardrails import md_escape  # noqa: E402
from app.pipeline import CFG, answer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ("functional", "basis", "dispersion", "solvation", "charge", "multiplicity", "software")
# Lens (bash scripts/lens.sh) explains each setting with a checked diagram. lens.sh
# writes the address it really uses (8765, or the next free port) to logs/lens_url.txt.
_lens_file = ROOT / "logs/lens_url.txt"
LENS_URL = (os.environ.get("REPROCHEM_LENS_URL")
            or (_lens_file.read_text().strip() if _lens_file.exists() else "")
            or "http://localhost:8765").rstrip("/")


def lens_link(field: str, value: str) -> str:
    """The field name, plus the value when there is one, is enough for the Lens router."""
    q = field if value in ("", "NOT_FOUND", "—") else f"{field} {value}"
    return f"[explain ↗]({LENS_URL}/?q={quote(q[:120])})"


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
    st.session_state["run"] = {"pid": pid, "text": text, "out": out, "s": time.time() - t0}

tab_x, tab_lens, tab_att = st.tabs(["1 · Extract (RAG)", "2 · Lens: explain a setting", "3 · Attacks"])

# ------------------------------------------------------------------ 1 · extract
with tab_x:
    run = st.session_state.get("run")
    if not run or run["pid"] != pid:
        st.info("Pick a paper or upload a file in the sidebar, then press Extract.")
    else:
        out = run["out"]
        st.write(f"**{run['s']:.1f} s** for 7 fields, no network.")
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
            c1.markdown(f"`{f}`  \n{lens_link(f, sv)}")
            if sv == "NOT_FOUND":
                c2.markdown(":red[NOT_FOUND]")
            else:
                c2.markdown(f"**{md_escape(sv)}**")
                if s.get("citation"):
                    c2.caption("« " + md_escape(s["citation"]["quote"][:220]) + " »")
                    if s["citation"].get("verified") is False:
                        c2.caption(":orange[⚠ quote not found in the passages: check by hand]")
            mark = "" if tv == "—" else (" ✓" if norm(tv) == norm(sv) else " ✗")
            c3.markdown(f"{md_escape(tv)}{mark}")
            if gv != "—":
                c4.markdown(f"{md_escape(gv)}" + (" ✓" if norm(gv) == norm(sv) else " ✗"))
            else:
                c4.markdown("—")
        st.divider()
        if out["spec"] is None:
            st.warning("Compilation blocked: " + out["compile_note"])
        else:
            st.success("Complete protocol: spec compiled")
            st.json(out["spec"])

        # The RAG step made visible: exactly what the student read for each field.
        st.subheader("What the model read: 3 BM25 passages per field")
        from app.guardrails import scrub
        from app.pipeline import Retriever, parse, retrieve
        r = Retriever(parse(run["text"], pid), CFG["retrieval"])
        for f in FIELDS:
            with st.expander(f"{f}"):
                for chunk, score in retrieve(r, f, mode="bm25"):
                    clean, hits = scrub(chunk.text)
                    st.caption(f"{chunk.id} · BM25 score {score:.2f}"
                               + (f" · ⚠ {len(hits)} injection(s) neutralised" if hits else ""))
                    st.text(clean[:1500])

# ------------------------------------------------------------------ 2 · Lens
def lens_up() -> bool:
    import urllib.request
    try:
        page = urllib.request.urlopen(LENS_URL, timeout=0.5).read(4000).decode("utf-8", "ignore")
        return "ReproChem Lens" in page          # not another app that took the port
    except Exception:  # noqa: BLE001
        return False


with tab_lens:
    if lens_up():
        st.caption(f"Click a concept, or type a question. For the microphone, open Lens in its own "
                   f"window: [{LENS_URL}]({LENS_URL}) (browsers allow the microphone there).")
        if hasattr(st, "iframe"):                       # Streamlit >= 1.66
            st.iframe(LENS_URL, height=760)
        else:
            import streamlit.components.v1 as components
            components.iframe(LENS_URL, height=760, scrolling=False)
    else:
        st.warning("Lens is not running. In a second terminal: `bash scripts/lens.sh`, then reload this page.")

# ------------------------------------------------------------------ 3 · attacks
with tab_att:
    st.subheader("A · The 20 attacks, replayed without a model")
    sec_path = ROOT / "docs/security_results.json"
    if st.button("Replay the 20 attacks (about 20 s)"):
        import subprocess
        with st.spinner("scripts/security_eval.py…"):
            subprocess.run([sys.executable, str(ROOT / "scripts/security_eval.py")], cwd=ROOT,
                           capture_output=True, text=True, timeout=300)
    if sec_path.exists():
        sec = json.loads(sec_path.read_text())
        sm = sec.get("summary")
        if sm:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("blocked", sm["blocked"])
            m2.metric("detected", sm["detected"])
            m3.metric("passed", sm["passed"])
            lo, hi = sm["asr_ci95"]
            m4.metric("success rate", f"{sm['passed']}/{sm['attacks']}", f"95% CI {lo:.1%}–{hi:.0%}",
                      delta_color="off")
            icon = {"blocked": "🟢", "detected": "🟠", "passed": "🔴"}
            for a in sec["attacks"]:
                with st.expander(f"{icon.get(a['outcome'], '⚪')} {a['id']} · {a['attack']}  [{a['owasp']}]"):
                    if a.get("payload"):
                        st.markdown("**Attacker writes**")
                        st.text(a["payload"])
                    if a.get("seen"):
                        st.markdown("**What gets through**")
                        st.text(a["seen"])
                    for d in a.get("details", []):
                        st.text("· " + d)
                    st.caption(f"{a['outcome'].upper()} · {a['evidence']}")
        st.caption(f"Report: docs/security_results.md · last run "
                   f"{time.strftime('%H:%M', time.localtime(sec_path.stat().st_mtime))}")

    st.divider()
    st.subheader("B · Attack the live student")
    st.caption("Paper 2202.02370 (B3LYP/6-311++G(d,p), Gaussian 09, no solvent) is edited, then the "
               "student answers the fields the attack targets.")
    sys.path.insert(0, str(ROOT / "scripts"))
    from red_team import ATTACKS, build
    choice = st.selectbox("Attack", [f"{a['id']} · {a['name']}" for a in ATTACKS])
    att = ATTACKS[[f"{a['id']} · {a['name']}" for a in ATTACKS].index(choice)]
    st.text(att["how"])
    off = st.checkbox("Turn the injection filter off, to see what it stops")
    md_att = build((ROOT / "data/papers/md/2202.02370.md").read_text(encoding="utf-8"), att)
    st.download_button("Download the attacked document (to upload in tab 1)", md_att,
                       file_name=f"2202.02370_{att['id']}.md")
    if st.button("Run on the student", type="primary"):
        import app.pipeline as P
        r = P.Retriever(P.parse(md_att, "2202.02370"), CFG["retrieval"])
        saved = P.scrub
        if off:
            P.scrub = lambda t: (t, [])
        try:
            for f, want in att["check"].items():
                hits = P.retrieve(r, f, mode="bm25")
                messages, found = P.extract_messages(f, hits)
                with st.spinner(f"student: {f}…"):
                    raw, _ = P.chat(messages)
                got = P.parse_field(P._json_block(raw), hits, P.abstain_threshold("bm25")).value
                ok = norm(got) == norm(want)
                st.markdown(f"{'🟢 HELD' if ok else '🔴 FAILED'} · `{f}` expected **{md_escape(want)}**, "
                            f"student answered **{md_escape(got)}**"
                            + (f" · {len(found)} injection(s) neutralised" if found else ""))
                with st.expander(f"the passages the student read for {f}"):
                    st.text(messages[1]["content"][:4000])
        finally:
            P.scrub = saved
