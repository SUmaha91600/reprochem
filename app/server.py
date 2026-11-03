"""ReproChem in one HTML page: extraction with its RAG passages, Lens, attacks.

    bash scripts/web.sh                 # opens http://127.0.0.1:8600 (or the next free port)

A small local server, standard library only. It serves app/web/index.html and
the Lens files under /lens/, and answers a few JSON routes. The model runs in
this process (MLX on the Mac), one request at a time. It listens on 127.0.0.1
only: nothing outside the laptop can reach it.

    GET  /api/info              model, gold papers, attack list
    POST /api/extract           {"paper_id"} or {"name", "text"} -> card, passages, teacher, gold
    GET  /api/security          last results of scripts/security_eval.py
    POST /api/security/replay   reruns the 20 attacks (no model, ~20 s)
    POST /api/attack            {"id", "filter_off"} -> the student on an attacked paper
    GET  /api/attack/doc?id=R1  the attacked document, to download
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import app.pipeline as P  # noqa: E402
from app.guardrails import scrub  # noqa: E402
from red_team import ATTACKS, build  # noqa: E402

WEB, LENS = ROOT / "app/web", ROOT / "app/lens"
FIELDS = ("functional", "basis", "dispersion", "solvation", "charge", "multiplicity", "software")
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".woff2": "font/woff2", ".png": "image/png",
         ".svg": "image/svg+xml", ".json": "application/json"}
# ── SAFEGUARD S20 · no free path, bounded upload, one model call at a time (LLM10) ── tested by: server test
#    Paper ids are checked against a pattern, static files cannot leave their folder, uploads stop at 5 MB.
MODEL_LOCK = threading.Lock()          # one model call at a time (16 GB Mac)
MAX_UPLOAD = 5_000_000


def norm(v) -> str:
    return str(v).strip().upper().replace(" ", "").replace("-", "")


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()] if p.exists() else []


def gold() -> dict:
    return {t["paper_id"]: t for t in read_jsonl(ROOT / "eval/testset.jsonl")}


def teacher_cards() -> dict:
    return {c["paper_id"]: c["card"] for c in read_jsonl(ROOT / "data/teacher/doc_cards.jsonl")}


def paper_text(pid: str) -> str:
    """Only gold-set papers or corpus ids: the id never becomes a free path."""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", pid) or ".." in pid:
        raise ValueError(f"unknown paper: {pid}")
    t = gold().get(pid)
    path = ROOT / (t["markdown_path"] if t else f"data/papers/md/{pid}.md")
    if not path.exists():
        raise ValueError(f"unknown paper: {pid}")
    return path.read_text(encoding="utf-8", errors="replace")


def passages(text: str, pid: str) -> dict:
    """The RAG step: the 3 BM25 passages each field gets, as the model reads them."""
    r = P.Retriever(P.parse(text, pid), P.CFG["retrieval"])
    out = {}
    for f in FIELDS:
        rows = []
        for chunk, score in P.retrieve(r, f, mode="bm25"):
            clean, hits = scrub(chunk.text)
            rows.append({"id": chunk.id, "score": round(float(score), 2), "text": clean[:2000],
                         "neutralised": len(hits)})
        out[f] = rows
    return out


def info() -> dict:
    g = gold()
    return {"model": P.CFG["model"]["name"], "adapter": os.environ.get("REPROCHEM_ADAPTER") or "none",
            "papers": sorted(g), "fields": FIELDS,
            "attacks": [{"id": a["id"], "name": a["name"], "how": a["how"], "check": a["check"]}
                        for a in ATTACKS]}


def extract(body: dict) -> dict:
    if body.get("text"):
        text, pid = body["text"][:MAX_UPLOAD], Path(str(body.get("name") or "upload")).stem[:80]
    else:
        pid = str(body["paper_id"])
        text = paper_text(pid)
    with MODEL_LOCK:
        t0 = time.time()
        out = P.answer(text, pid, "O", 1, mode="bm25")
        seconds = time.time() - t0
    card = {}
    for f in FIELDS:
        s = out["card"].get(f) or {}
        c = s.get("citation") or {}
        card[f] = {"value": s.get("value", "NOT_FOUND"), "quote": c.get("quote"), "verified": c.get("verified")}
    t = teacher_cards().get(pid) or {}
    g = (gold().get(pid) or {}).get("fields") or {}
    return {"paper_id": pid, "seconds": round(seconds, 1), "card": card,
            "teacher": {f: (t.get(f) or {}).get("value") for f in FIELDS} if t else None,
            "gold": {f: g.get(f) for f in FIELDS} if g else None,
            "spec": out.get("spec"), "compile_note": out.get("compile_note"),
            "passages": passages(text, pid)}


def attack_by_id(aid: str) -> dict:
    for a in ATTACKS:
        if a["id"] == aid:
            return a
    raise ValueError(f"unknown attack: {aid}")


def attacked_doc(aid: str) -> str:
    return build(paper_text("2202.02370") if "2202.02370" in gold() else
                 (ROOT / "data/papers/md/2202.02370.md").read_text(encoding="utf-8"), attack_by_id(aid))


def attack(body: dict) -> dict:
    a = attack_by_id(str(body["id"]))
    md = attacked_doc(a["id"])
    r = P.Retriever(P.parse(md, "2202.02370"), P.CFG["retrieval"])
    rows = []
    with MODEL_LOCK:
        saved = P.scrub
        if body.get("filter_off"):
            P.scrub = lambda t: (t, [])
        try:
            for f, want in a["check"].items():
                hits = P.retrieve(r, f, mode="bm25")
                messages, found = P.extract_messages(f, hits)
                raw, _ = P.chat(messages)
                got = P.parse_field(P._json_block(raw), hits, P.abstain_threshold("bm25")).value
                rows.append({"field": f, "expected": want, "got": got, "held": norm(got) == norm(want),
                             "neutralised": len(found), "read": messages[1]["content"][:4000]})
        finally:
            P.scrub = saved
    return {"id": a["id"], "name": a["name"], "filter_off": bool(body.get("filter_off")), "fields": rows}


def security(replay: bool = False) -> dict | None:
    if replay:
        subprocess.run([sys.executable, str(ROOT / "scripts/security_eval.py")], cwd=ROOT,
                       capture_output=True, text=True, timeout=300)
    p = ROOT / "docs/security_results.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    d["updated"] = time.strftime("%H:%M", time.localtime(p.stat().st_mtime))
    return d


class Handler(BaseHTTPRequestHandler):
    server_version = "ReproChem"

    def log_message(self, fmt, *args):            # quiet console: one line per API call
        if self.path.startswith("/api/"):
            sys.stderr.write(f"{time.strftime('%H:%M:%S')} {self.command} {self.path}\n")

    def send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj, code: int = 200):
        self.send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def static(self, base: Path, rel: str):
        p = (base / (rel or "index.html")).resolve()
        if not p.is_relative_to(base.resolve()) or not p.is_file():
            return self.send(404, b"not found", "text/plain")
        self.send(200, p.read_bytes(), TYPES.get(p.suffix, "application/octet-stream"))

    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path == "/api/info":
                return self.json(info())
            if u.path == "/api/security":
                return self.json(security())
            if u.path == "/api/attack/doc":
                aid = parse_qs(u.query).get("id", ["R1"])[0]
                return self.send(200, attacked_doc(aid).encode(), "text/markdown; charset=utf-8",
                                 {"Content-Disposition": f'attachment; filename="2202.02370_{aid}.md"'})
            if u.path == "/lens" or u.path.startswith("/lens/"):
                return self.static(LENS, u.path[len("/lens/"):] if u.path != "/lens" else "")
            return self.static(WEB, u.path.lstrip("/"))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self.json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_UPLOAD + 10_000:
                return self.json({"error": "document too large (5 MB maximum)"}, 413)
            body = json.loads(self.rfile.read(n) or b"{}")
            if u.path == "/api/extract":
                return self.json(extract(body))
            if u.path == "/api/attack":
                return self.json(attack(body))
            if u.path == "/api/security/replay":
                return self.json(security(replay=True))
            return self.json({"error": "unknown route"}, 404)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self.json({"error": f"{type(e).__name__}: {e}"}, 500)


def free_port(start: int) -> int:
    for port in range(start, start + 20):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("no free port")


def main() -> int:
    port = free_port(int(os.environ.get("PORT", "8600")))
    # ── SAFEGUARD S20 · local server only (LLM10) ── tested by: server test
    #    Bound to 127.0.0.1: nothing outside the laptop can reach the app.
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"ReproChem: {url}   (Ctrl-C to stop)", flush=True)
    if os.environ.get("REPROCHEM_OPEN", "1") == "1" and sys.platform == "darwin":
        subprocess.Popen(["open", url])
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
