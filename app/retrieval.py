"""Hybrid search + reranking.

The recipe comes from the 7 Oct lab, where it was measured:
BM25 Recall@1 0.64 · dense (bge-m3) 0.93 · hybrid 0.79 · + reranker 1.00.
All three retrievers stay available because the evaluation always compares
the system with a simpler baseline.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


@dataclass
class Chunk:
    id: str
    text: str
    meta: dict = field(default_factory=dict)


def tokenize(s: str) -> list[str]:
    """Keeps `def2-tzvp` whole AND its pieces. Otherwise the lexical baseline
    misses any query that spells the name differently, and the comparison is
    skewed in favour of the full system."""
    toks = re.findall(r"[a-zA-Z0-9\-\+\*]{2,}", s.lower())
    out = list(toks)
    for t in toks:
        if "-" in t:
            out += [p for p in t.split("-") if len(p) >= 2]
    return out


class BM25:
    """Lexical baseline, no dependencies. Fast and honest."""

    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.docs = [tokenize(c.text) for c in chunks]
        self.avgdl = sum(len(d) for d in self.docs) / max(len(self.docs), 1)
        self.df: dict[str, int] = {}
        for d in self.docs:
            for t in set(d):
                self.df[t] = self.df.get(t, 0) + 1
        self.N = len(self.docs)

    def search(self, query: str, k: int = 10) -> list[tuple[Chunk, float]]:
        q = tokenize(query)
        scored = []
        for chunk, doc in zip(self.chunks, self.docs):
            dl = len(doc) or 1
            s = 0.0
            for t in q:
                f = doc.count(t)
                if not f:
                    continue
                idf = math.log(1 + (self.N - self.df[t] + 0.5) / (self.df[t] + 0.5))
                s += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            scored.append((chunk, s))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]


def _normalise(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class Dense:
    """bge-m3 embeddings, through either of two paths.

    `ollama`: the model is already on the machine (`ollama pull bge-m3`) and is
    called through /v1/embeddings. No extra Python dependency, so no torch and
    none of the 3 GB that come with it.

    `sentence-transformers`: the path from the 7 Oct lab, handy for running the
    same code as in class or running without a server.

    The dot product is plain Python: over a few dozen passages the cost is
    negligible, and it keeps numpy out of the core.
    """

    def __init__(self, chunks: list[Chunk], cfg: dict):
        self.chunks = chunks
        self.backend = cfg.get("embedder_backend", "ollama")
        self.model_name = cfg["embedder"]
        self.base_url = cfg.get("embeddings_base_url", "http://localhost:11434/v1")
        self._client = None
        self._model = None
        self._emb: list[list[float]] | None = None

    # ------------------------------------------------------------- encoding
    def _encode_ollama(self, texts: list[str]) -> list[list[float]]:
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(base_url=self.base_url, api_key="ollama")
        out = self._client.embeddings.create(model=self.model_name, input=texts)
        return [_normalise(d.embedding) for d in out.data]

    def _encode_st(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            from sentence_transformers import SentenceTransformer     # heavy
            self._model = SentenceTransformer(self.model_name)
        return [list(map(float, v))
                for v in self._model.encode(texts, normalize_embeddings=True)]

    def encode(self, texts: list[str]) -> list[list[float]]:
        return (self._encode_ollama(texts) if self.backend == "ollama"
                else self._encode_st(texts))

    # ---------------------------------------------------------------- search
    def search(self, query: str, k: int = 10) -> list[tuple[Chunk, float]]:
        if self._emb is None:
            self._emb = self.encode([c.text for c in self.chunks])
        qv = self.encode([query])[0]
        scored = [(c, _cosine(qv, e)) for c, e in zip(self.chunks, self._emb)]
        scored.sort(key=lambda x: -x[1])
        return scored[:k]


def rrf(runs: list[list[tuple[Chunk, float]]], k: int = 60, top: int = 10):
    """Reciprocal Rank Fusion: merges rankings without calibrating the scores."""
    agg: dict[str, float] = {}
    byid: dict[str, Chunk] = {}
    for run in runs:
        for rank, (chunk, _) in enumerate(run, start=1):
            agg[chunk.id] = agg.get(chunk.id, 0.0) + 1.0 / (k + rank)
            byid[chunk.id] = chunk
    order = sorted(agg.items(), key=lambda x: -x[1])[:top]
    return [(byid[i], s) for i, s in order]


class Reranker:
    """Cross-encoder. This is what took Recall@1 to 1.00 in the lab."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None

    def __call__(self, query: str, cands: list[tuple[Chunk, float]], top: int):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name)
        pairs = [(query, c.text) for c, _ in cands]
        scores = self._model.predict(pairs)
        ranked = sorted(zip([c for c, _ in cands], map(float, scores)),
                        key=lambda x: -x[1])
        return ranked[:top]


def _have_sentence_transformers() -> bool:
    import importlib.util
    return importlib.util.find_spec("sentence_transformers") is not None


class Retriever:
    """One object, four modes. `mode` is what the evaluation varies.

    Fallback happens in two steps: without a cross-encoder, `rerank` becomes
    `hybrid`; with no embeddings at all, everything becomes `bm25`. The report
    always states what actually ran."""

    _warned = False

    def __init__(self, chunks: list[Chunk], cfg: dict):
        self.cfg = cfg
        self.chunks = chunks
        self.bm25 = BM25(chunks)
        self.dense = Dense(chunks, cfg)
        self.reranker = Reranker(cfg["reranker"])
        # Reranking uses a cross-encoder, which Ollama does not offer, so it
        # needs sentence-transformers. Dense retrieval goes through Ollama.
        self.can_rerank = _have_sentence_transformers()
        self.can_dense = (cfg.get("embedder_backend", "ollama") == "ollama"
                          or self.can_rerank)

    def resolve(self, mode: str) -> str:
        """The mode that will actually run, given what is installed.
        The report shows this one, never the one requested."""
        if mode == "rerank" and not self.can_rerank:
            if not Retriever._warned:
                print("[retrieval] reranker unavailable (sentence-transformers "
                      "not installed): falling back to hybrid fusion.")
                Retriever._warned = True
            mode = "hybrid"
        if mode in ("dense", "hybrid") and not self.can_dense:
            if not Retriever._warned:
                print("[retrieval] embeddings unavailable: falling back to BM25.")
                Retriever._warned = True
            mode = "bm25"
        return mode

    def search(self, query: str, mode: str = "rerank"):
        k = self.cfg["top_k"]
        mode = self.resolve(mode)
        self.last_mode = mode
        if mode == "bm25":
            return self.bm25.search(query, k)
        if mode == "dense":
            return self.dense.search(query, k)
        fused = rrf([self.bm25.search(query, 20), self.dense.search(query, 20)],
                    k=self.cfg["rrf_k"], top=self.cfg["rerank_n"])
        if mode == "hybrid":
            return fused[:k]
        return self.reranker(query, fused, k)
