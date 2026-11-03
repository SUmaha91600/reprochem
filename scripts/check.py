"""First command to run: says what works, what is missing, and what to type.

    uv run python scripts/check.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.pipeline import health  # noqa: E402

OK, KO = "  ok  ", " missing "


def main() -> int:
    h = health()
    print(f"endpoint   {h['endpoint']}")
    print(f"model      {h['model']}")
    print()
    print(f"[{OK if h['llm'] == 'ok' else KO}] generation            {h['llm']}")
    print(f"[{OK if h['dense_ok'] else KO}] embeddings            {h['embeddings']}")
    print(f"[{OK if h['reranker'] else KO}] reranker              "
          + ("bge-reranker-v2-m3 available" if h["reranker"]
             else "uv sync --extra rerank  (without it: rerank → hybrid)"))
    print(f"[{OK if h['chemistry'] else KO}] chemistry             "
          + ("pyscf + rdkit available" if h["chemistry"]
             else "uv sync --extra chem  (without them: runnable → null)"))

    if h["llm"] != "ok":
        print()
        if h.get("available"):
            print("Models available on this endpoint:")
            for m in h["available"]:
                print(f"    {m}")
        elif h["available"] == []:
            print("The endpoint answers but serves no model.")
        if h.get("fix"):
            print()
            print(h["fix"])
        return 1

    print()
    print("Ready. Run: uv run python eval/eval.py --mode bm25")
    return 0


if __name__ == "__main__":
    sys.exit(main())
