# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""A fake OpenAI server, standard library only, for testing without a model.

    uv run scripts/fake_llm.py &
    REPROCHEM_BASE_URL=http://127.0.0.1:8111/v1 REPROCHEM_MODEL=fake \\
    REPROCHEM_API_KEY_ENV=none uv run python eval/eval.py --mode bm25

It answers with a regex over the given passages. It is a harness, not a
model: it shows the plumbing holds when the model goes down. Useful in CI,
and on demo day if the network fails.
"""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer

PATTERNS = {
    "functional": r"\b(B3LYP|PBE0|PBE|M06-2X|wB97X-D|TPSS|CAM-B3LYP|BP86)\b",
    "basis": r"\b(def2-[A-Z]+|cc-pV[TDQ]Z|aug-cc-pV[TDQ]Z|6-31\+?G\*{1,2}|6-311\+\+G\*\*|STO-3G)\b",
    "dispersion": r"\b(D3\(BJ\)|D3BJ|D3|D4)\b",
    "solvation": r"\b(CPCM|SMD|PCM|COSMO)\s*\(?\s*(water|acetonitrile|toluene|dmso|methanol)?\)?",
    "charge": r"charge (?:is |of )?(-?\d+)",
    "multiplicity": r"multiplicity (?:is |of )?(\d+)",
    "software": r"\b(ORCA|Gaussian|PySCF|Psi4|Q-Chem|Turbomole)\s*([\d.]+)?\b",
}


def _find(field: str, text: str) -> tuple[str, str]:
    m = re.search(PATTERNS.get(field, r"(?!x)x"), text, re.I)
    if not m:
        return "NOT_FOUND", ""
    value = m.group(1) if m.lastindex else m.group(0)
    sentence = next((s for s in re.split(r"(?<=\.)\s+", text) if m.group(0) in s),
                    m.group(0))
    return value.strip(), sentence


def answer(body: str) -> str:
    if "<article>" in body:                         # baseline: whole paper
        text = body.split("<article>")[-1].split("</article>")[0]
        out = {"task": "geometry_optimisation" if re.search(r"optimi[sz]", text, re.I)
               else "single_point"}
        for f in PATTERNS:
            value, sentence = _find(f, text)
            out[f] = {"value": value, "quote": " ".join(sentence.split())[:300]}
        return json.dumps(out)
    field = (re.search(r"<champ>(\w+)</champ>", body) or [None, ""])[1]
    sources = body.split("<sources>")[-1]
    if not field:                                   # compiler call
        return json.dumps({"molecule_smiles": "O", "task": "single_point",
                           "functional": "B3LYP", "basis": "def2-TZVP",
                           "charge": 0, "multiplicity": 1,
                           "dispersion": None, "solvent": None})
    m = re.search(PATTERNS.get(field, r"(?!x)x"), sources, re.I)
    if not m:
        return json.dumps({"value": "NOT_FOUND", "chunk_id": "", "quote": ""})
    value = m.group(1) if m.lastindex else m.group(0)
    sentence = next((s for s in re.split(r"(?<=\.)\s+", sources) if m.group(0) in s),
                    m.group(0))
    chunk = (re.search(r"\[([^\]]+)\]", sentence) or re.search(r"\[([^\]]+)\]", sources))
    return json.dumps({"value": value.strip(),
                       "chunk_id": chunk.group(1) if chunk else "unknown",
                       "quote": sentence.strip()[:300]})


SERVED = "fake"


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):                                            # noqa: N802
        # Ollama exposes GET /v1/models; we do the same so scripts/check.py
        # can list what the endpoint actually serves.
        if self.path.rstrip("/").endswith("/models"):
            self._send(200, {"object": "list",
                             "data": [{"id": SERVED, "object": "model",
                                       "created": 0, "owned_by": "local"}]})
        else:
            self._send(404, {"error": {"message": "not found"}})

    def _embed(self, texts: list[str], dim: int = 64) -> list[list[float]]:
        """Deterministic hashed bag-of-words embeddings. Enough to check that
        the dense plumbing holds; nothing to do with bge-m3."""
        out = []
        for t in texts:
            v = [0.0] * dim
            for tok in re.findall(r"[a-z0-9\-\+\*]{2,}", t.lower()):
                v[hash(tok) % dim] += 1.0
            out.append(v)
        return out

    def do_POST(self):                                           # noqa: N802
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.rstrip("/").endswith("/embeddings"):
            raw = payload["input"]
            texts = raw if isinstance(raw, list) else [raw]
            self._send(200, {"object": "list", "model": payload.get("model", SERVED),
                             "data": [{"object": "embedding", "index": i,
                                       "embedding": e}
                                      for i, e in enumerate(self._embed(texts))]})
            return
        if payload.get("model") != SERVED:
            # Same behaviour as Ollama when the model has not been pulled.
            self._send(404, {"error": {"message":
                                       f'model "{payload.get("model")}" not found'}})
            return
        user = payload["messages"][-1]["content"]
        self._send(200, {
            "id": "fake", "object": "chat.completion", "model": SERVED,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": answer(user)}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})

    def log_message(self, *_):                                   # silence
        pass


if __name__ == "__main__":
    print("fake model on http://127.0.0.1:8111/v1")
    HTTPServer(("127.0.0.1", 8111), Handler).serve_forever()
