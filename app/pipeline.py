"""All product logic, split into small functions.

parse -> retrieve -> extract -> compile_spec -> validate

Alongside it, `extract_fullpaper` is the serious competitor: a strong model that
reads the whole paper, with no retrieval. The system has to beat it.

Every function can be called on its own. In November each one becomes an agent
tool without a rewrite.
"""
from __future__ import annotations

import json
import os
import re
import time

import yaml
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

from .guardrails import abstain, cost_gate, scrub
from .retrieval import Chunk, Retriever
from .schema import NOT_FOUND, Citation, Field_, JobSpec, MethodCard

ROOT = os.path.join(os.path.dirname(__file__), "..")
CFG = yaml.safe_load(open(os.path.join(ROOT, "config.yaml")))
load_dotenv(os.path.join(ROOT, ".env"))

# Environment variables override config.yaml: comparing two models should not
# require editing a file.
CFG["model"]["base_url"] = os.environ.get("REPROCHEM_BASE_URL", CFG["model"]["base_url"])
CFG["model"]["name"] = os.environ.get("REPROCHEM_MODEL", CFG["model"]["name"])
_key_env = os.environ.get("REPROCHEM_API_KEY_ENV", CFG["model"].get("api_key_env", "none"))
CFG["model"]["api_key_env"] = _key_env
# Chunk size experiment (scripts/mac_chunks.sh): REPROCHEM_MAX_WORDS=400 overrides
# retrieval.max_words without editing config.yaml.
if os.environ.get("REPROCHEM_MAX_WORDS"):
    CFG["retrieval"]["max_words"] = int(os.environ["REPROCHEM_MAX_WORDS"])

client = OpenAI(
    base_url=CFG["model"]["base_url"] if CFG["model"]["base_url"].startswith("http") else "http://localhost:0/v1",
    api_key="ollama" if _key_env == "none" else os.environ.get(_key_env, "missing"),
)


def _section(name: str, env: str) -> dict:
    """A model section of config.yaml (baseline, teacher), overridden by the
    three environment variables REPROCHEM_<ENV>_BASE_URL / _MODEL / _API_KEY_ENV,
    so comparing two models never requires editing a file."""
    c = dict(CFG.get(name) or {})
    c["base_url"] = os.environ.get(f"REPROCHEM_{env}_BASE_URL", c.get("base_url", CFG["model"]["base_url"]))
    c["name"] = os.environ.get(f"REPROCHEM_{env}_MODEL", c.get("name", CFG["model"]["name"]))
    c["api_key_env"] = os.environ.get(f"REPROCHEM_{env}_API_KEY_ENV", c.get("api_key_env", "none"))
    return c


# The strong baseline (a strong model reads the whole document) and the
# distillation teacher are configured separately: they are often hosted models.
BCFG = _section("baseline", "BASELINE")
TCFG = _section("teacher", "TEACHER")


def client_for(c: dict) -> OpenAI:
    key = c["api_key_env"]
    return OpenAI(base_url=c["base_url"],
                  api_key="ollama" if key == "none" else os.environ.get(key, "missing"),
                  max_retries=c.get("max_retries", 3), timeout=c.get("timeout", 300))


def _baseline_client() -> OpenAI:
    return client_for(BCFG)


def _prompt(name: str) -> str:
    return open(os.path.join(ROOT, CFG["prompts"][name])).read()


# --------------------------------------------------------------- 1 · parse
SECTION_RE = re.compile(r"^#{1,3}\s+(.+)$", re.M)


# ── SAFEGUARD S6 · bounded context (LLM10) ── tested by: C4
#    A passage is cut at 8,000 characters and a title at 300: a 5 MB document still gives prompts of about 12,000 characters.
MAX_CHUNK_CHARS = 8000   # corpus maximum 7,808 (120 papers, 7,610 passages)
MAX_TITLE_CHARS = 300    # corpus maximum 202


def parse(markdown: str, paper_id: str) -> list[Chunk]:
    """Section-based chunking: it beat fixed-size chunks in the 7 Oct lab
    (correct answers 0.88 vs 0.69). A section longer than `max_words` is split
    into windows that keep the section title. The small model has a short
    context, and a 3,000-word section would bury the one useful sentence."""
    rcfg = CFG["retrieval"]
    if rcfg["chunking"] == "fixed":
        words = markdown.split()
        n = rcfg["fixed_words"]
        return [Chunk(id=f"{paper_id}#w{i}", text=" ".join(words[i:i + n]),
                      meta={"paper": paper_id})
                for i in range(0, len(words), n)]
    parts, last, title = [], 0, "head"
    for m in SECTION_RE.finditer(markdown):
        if m.start() > last:
            parts.append((title, markdown[last:m.start()]))
        title, last = m.group(1).strip(), m.end()
    parts.append((title, markdown[last:]))
    max_w = rcfg.get("max_words") or 10**9
    chunks, k = [], 0
    for t, body in parts:
        words = body.split()
        if not words:
            continue
        for j in range(0, len(words), max_w):
            # C5: a 200-word window can still be huge if one "word" is a 5 MB
            # blob. Corpus maximum: 7,808 characters, so this cap changes nothing
            # in normal use and keeps every prompt bounded.
            chunks.append(Chunk(id=f"{paper_id}#{k}",
                                text=(f"{t[:MAX_TITLE_CHARS]}\n" + " ".join(words[j:j + max_w]))[:MAX_CHUNK_CHARS],
                                meta={"paper": paper_id, "section": t[:MAX_TITLE_CHARS]}))
            k += 1
    return chunks


# ------------------------------------------------------------ 2 · retrieve
# The gold set covers the geometry optimisation step, so the queries target
# the sentences that describe it.
QUERIES = {
    "functional": "geometries optimized with the DFT exchange correlation functional",
    "basis": "geometry optimization basis set def2 cc-pV 6-31G 6-311G",
    "dispersion": "dispersion correction D3 D4 Becke-Johnson damping GD3BJ",
    "solvation": "implicit solvation model CPCM SMD PCM solvent",
    "charge": "total charge of the system anion cation neutral",
    "multiplicity": "spin multiplicity singlet doublet triplet state",
    "software": "software package and version used for the calculations Gaussian ORCA",
}


def retrieve(retriever: Retriever, field: str, mode: str = "rerank"):
    return retriever.search(QUERIES[field], mode=mode)


# -------------------------------------------------------------- 3 · extract
# ── SAFEGUARD S5 · documents are data, never instructions (LLM01) ── tested by: A1-A6
#    Every passage goes through scrub() and is wrapped in <sources>; the system prompt is a separate message the document cannot edit.
def extract_messages(field: str, hits, for_teacher: bool = False) -> tuple[list[dict], list[str]]:
    """The exact messages sent for one field. One function serves the student,
    the teacher and the training set: distillation only makes sense if the
    student trains on what it will see in production, character for character."""
    injections: list[str] = []
    ctx_parts = []
    for chunk, _score in hits:
        clean, found = scrub(chunk.text)
        injections += found
        ctx_parts.append(f"[{chunk.id}] {clean}")
    user = (f"<champ>{field}</champ>\n<sources>\n" + "\n\n".join(ctx_parts)
            + "\n</sources>")
    if CFG["model"].get("disable_thinking") and not for_teacher:
        # Qwen3: turns off the reasoning chain. Copying a value out of a passage
        # does not need it, and it triples the number of generated tokens.
        user += "\n/no_think"
    return ([{"role": "system", "content": _prompt("extract")},
             {"role": "user", "content": user}], injections)


_MLX: dict = {}


def _mlx_chat(messages: list[dict], c: dict) -> tuple[str, dict]:
    """The student served locally by MLX, in the same process (Apple Silicon
    Mac). base_url = "mlx"; name = the model (Hugging Face repo or local
    folder); the LoRA adapter comes from REPROCHEM_ADAPTER or c["adapter_path"]."""
    from mlx_lm import generate, load

    adapter = os.environ.get("REPROCHEM_ADAPTER", c.get("adapter_path")) or None
    edit = os.environ.get("REPROCHEM_EDIT") or None   # optional weight edit (app/weight_edit.py)
    key = (c["name"], adapter, edit)
    if key not in _MLX:
        _MLX.clear()
        _MLX[key] = load(c["name"], adapter_path=adapter)
        if edit:
            from .weight_edit import apply
            apply(_MLX[key][0], edit)
    model, tok = _MLX[key]
    prompt = tok.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
    max_tokens = c.get("max_tokens", 700)
    try:
        from mlx_lm.sample_utils import make_sampler
        text = generate(model, tok, prompt=prompt, max_tokens=max_tokens, sampler=make_sampler(temp=0.0))
    except (ImportError, TypeError):
        text = generate(model, tok, prompt=prompt, max_tokens=max_tokens)
    return text.strip(), {"prompt_tokens": len(tok.encode(prompt)), "completion_tokens": None}


def chat(messages: list[dict], c: dict | None = None) -> tuple[str, dict]:
    """One model call. Without `c`, it uses the system model (config `model`)."""
    c = c or CFG["model"]
    if str(c.get("base_url", "")).startswith("mlx"):
        return _mlx_chat(messages, c)
    cl = client if c is CFG["model"] else client_for(c)
    kwargs = {}
    if c.get("seed") is not None:
        kwargs["seed"] = c["seed"]
    r = cl.chat.completions.create(model=c["name"], temperature=c.get("temperature", 0),
                                   max_tokens=c.get("max_tokens", 700),
                                   messages=messages, **kwargs)
    u = getattr(r, "usage", None)
    usage = {"prompt_tokens": getattr(u, "prompt_tokens", None),
             "completion_tokens": getattr(u, "completion_tokens", None)}
    return (r.choices[0].message.content or "").strip(), usage


def _chat(system: str, user: str) -> str:
    if CFG["model"].get("disable_thinking"):
        user += "\n/no_think"
    text, _ = chat([{"role": "system", "content": system},
                    {"role": "user", "content": user}])
    return text


def abstain_threshold(mode: str) -> float:
    """A threshold only means something on its own retriever's score scale:
    an RRF score is ~0.03, a cosine ~0.5, and a BM25 score can exceed 10."""
    t = CFG["retrieval"].get("abstain_threshold", 0.0)
    if isinstance(t, dict):
        return float(t.get(mode, 0.0))
    return float(t) if mode == "rerank" else 0.0


THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def _json_block(text: str) -> dict:
    """Qwen sometimes wraps its answer in <think>…</think>. Strip it before
    looking for the JSON, or a brace from the reasoning gets picked up."""
    text = THINK_RE.sub("", text)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


# A setting is a few words ("6-311++G(d,p)", "Gaussian 16 B.01"): 24 characters
# at most in every report so far. Anything longer is not a setting, it is text
# the model was pushed to output (a system prompt, a paragraph): NOT_FOUND (A6).
# ── SAFEGUARD S7 · a value is a setting, not a paragraph (LLM07) ── tested by: A6
#    Any answer over 60 characters (a leaked prompt, a pasted paragraph) becomes NOT_FOUND.
MAX_VALUE_CHARS = 60


# ── SAFEGUARD S8 · citation check on every answer (LLM09) ── tested by: B3
#    The quote must be in the passages and the value in the quote; otherwise the screen says 'quote not found, check by hand'.
def citation_verified(value: str, quote: str, hits) -> bool:
    """The quote is in the passages the model read, and the value is in the
    quote. The same checks the evaluation makes, now made on every answer."""
    passages = _norm_text(" ".join(c.text for c, _ in hits))
    q = _norm_text(quote)
    v = re.sub(r"[\s\-()]", "", value.lower())
    return len(q) >= 10 and q in passages and v in re.sub(r"[\s\-()]", "", q)


def parse_field(out: dict, hits, threshold: float) -> Field_:
    value = str(out.get("value", NOT_FOUND)).strip() or NOT_FOUND
    if len(value) > MAX_VALUE_CHARS:
        value = NOT_FOUND
    quote = str(out.get("quote", "")).strip()[:400]
    cid = str(out.get("chunk_id", "")).strip()
    best = max((s for _, s in hits), default=0.0)
    citation = None
    if value != NOT_FOUND and len(quote) >= 10 and cid:
        citation = Citation(chunk_id=cid, quote=quote, score=float(best),
                            verified=citation_verified(value, quote, hits))
    return abstain(Field_(value=value, citation=citation), threshold)


def extract(retriever: Retriever, paper_id: str, mode: str = "rerank") -> MethodCard:
    """One targeted query per field. The model sees the passages, never the
    whole paper, which is what makes the citation checkable."""
    card: dict = {"paper_id": paper_id, "task": NOT_FOUND}
    injections: list[str] = []
    for field in QUERIES:
        hits = retrieve(retriever, field, mode=mode)
        messages, found = extract_messages(field, hits)
        injections += found
        text, _ = chat(messages)
        card[field] = parse_field(_json_block(text), hits,
                                  abstain_threshold(getattr(retriever, "last_mode", mode))).model_dump()
    if injections:
        # feeds docs/red_team_log.md: every attempt seen in production is logged
        # ── SAFEGUARD S21 · audit log of injection attempts (LLM01) ── tested by: docs/injections.log
        #    Every neutralised attempt is written with its paper id, for review.
        with open(os.path.join(ROOT, "docs", "injections.log"), "a") as fh:
            for hit in injections:
                fh.write(f"{paper_id}\t{hit}\n")
    return MethodCard(**card)


# ---------------------------------------------------------- 4 · compile_spec
def compile_spec(card: MethodCard, smiles: str) -> tuple[JobSpec | None, str]:
    """Method card + molecule -> runnable spec, or a refusal with a reason.

    A missing field is never filled in. It blocks compilation, and making that
    visible is exactly the product's job."""
    missing = [f for f in ("functional", "basis", "charge", "multiplicity")
               if not getattr(card, f).found]
    if missing:
        return None, "required fields missing from the paper: " + ", ".join(missing)
    raw = _json_block(_chat(
        _prompt("compile"),
        json.dumps({"card": card.model_dump(), "smiles": smiles}, ensure_ascii=False)))
    try:
        spec = JobSpec(**raw)
    except ValidationError as err:
        return None, f"invalid spec: {err.errors()[0]['msg']}"
    return spec, "ok"


# -------------------------------------------------------------- 5 · validate
def validate(spec: JobSpec, n_heavy_atoms: int) -> dict:
    ok, note = cost_gate(n_heavy_atoms, spec.basis, CFG["compiler"]["max_basis_functions"])
    if not ok:
        return {"accepted": False, "reason": note}
    import importlib.util as iu

    missing = [m for m in ("pyscf", "rdkit") if iu.find_spec(m) is None]
    if missing:
        # Without the engine there is no verdict. `converged: None` drops the row
        # from the metric instead of counting it as a failure.
        return {"accepted": True, "note": note, "converged": None,
                "log": f"runnability test skipped, missing package: {', '.join(missing)}"}
    from .compile_pyscf import render, runs

    script = render(spec, CFG["compiler"]["scf_conv_tol"], CFG["compiler"]["max_scf_cycles"])
    converged, log = runs(script)
    return {"accepted": True, "note": note, "script": script,
            "converged": converged, "log": log}


# ---------------------------------------------------- baseline · full paper
TASKS = ("single_point", "geometry_optimisation", "frequency")


def _norm_text(t: str) -> str:
    """For matching a quote against the paper: case, whitespace and markdown
    marks must not make an exact quote fail."""
    t = re.sub(r"\[[^\]]*#[^\]]*\]", " ", t)      # passage labels [paper#3]
    t = re.sub(r"[*_`#>]", "", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def quote_in_paper(quote: str, markdown: str) -> bool:
    """Is the quote really in the paper? A model can write a plausible
    sentence that never appears there."""
    q = _norm_text(quote or "")
    return len(q) >= 10 and q in _norm_text(markdown)


def fullpaper_messages(markdown: str) -> list[dict]:
    return [{"role": "system", "content": _prompt("baseline")},
            {"role": "user", "content": f"<article>\n{markdown}\n</article>"}]


def card_from_fullpaper(out: dict, paper_id: str) -> MethodCard:
    card: dict = {"paper_id": paper_id}
    task = str(out.get("task", NOT_FOUND)).strip()
    card["task"] = task if task in TASKS else NOT_FOUND
    for field in QUERIES:
        raw = out.get(field) or {}
        if not isinstance(raw, dict):
            raw = {"value": raw, "quote": ""}
        value = str(raw.get("value", NOT_FOUND)).strip() or NOT_FOUND
        quote = str(raw.get("quote", "")).strip()[:400]
        citation = (Citation(chunk_id="fullpaper", quote=quote, score=1.0)
                    if value != NOT_FOUND and len(quote) >= 10 else None)
        card[field] = Field_(value=value, citation=citation).model_dump()
    return MethodCard(**card)


def extract_fullpaper(markdown: str, paper_id: str, c: dict | None = None) -> tuple[MethodCard, dict]:
    """Strong baseline: the whole paper in a single call, same rules as the
    system (NOT_FOUND allowed, citation required), no retrieval and no
    guardrails. This is what someone pasting the paper into a chat would do.
    With `c = TCFG`, it also produces the teacher's reference card."""
    c = c or BCFG
    approx_tokens = len(markdown) // 4
    limit = c.get("max_context_tokens", 120_000)
    if approx_tokens > limit:
        raise ValueError(f"document too long: ~{approx_tokens} tokens, "
                         f"limit {limit} (max_context_tokens)")
    extra = {}
    if c.get("reasoning_effort"):
        extra["reasoning_effort"] = c["reasoning_effort"]
    kwargs = {"seed": c["seed"]} if c.get("seed") is not None else {}
    r = client_for(c).chat.completions.create(
        model=c["name"], temperature=c.get("temperature", 0),
        max_tokens=c.get("max_tokens", 4000), messages=fullpaper_messages(markdown),
        **kwargs, **({"extra_body": extra} if extra else {}))
    u = getattr(r, "usage", None)
    usage = {"prompt_tokens": getattr(u, "prompt_tokens", None),
             "completion_tokens": getattr(u, "completion_tokens", None),
             "approx_input_tokens": approx_tokens}
    return card_from_fullpaper(_json_block(r.choices[0].message.content or ""), paper_id), usage


def answer_fullpaper(markdown: str, paper_id: str, smiles: str,
                     n_heavy_atoms: int) -> dict:
    """Same output as `answer`, so the evaluation compares like with like.
    Compilation and execution are the system's own; only extraction differs."""
    t0 = time.time()
    card, usage = extract_fullpaper(markdown, paper_id, BCFG)
    spec, note = compile_spec(card, smiles)
    out = {"card": card.model_dump(), "missing": card.missing(),
           "effective_mode": "fullpaper", "usage": usage, "model": BCFG["name"],
           "spec": spec.model_dump() if spec else None, "compile_note": note}
    if spec:
        out["validation"] = validate(spec, n_heavy_atoms)
    out["seconds"] = round(time.time() - t0, 2)
    return out


def health() -> dict:
    """What is actually installed and reachable, here and now.

    A useful diagnosis separates three failures that the raw error lumps
    together: the server does not answer, the server answers but does not know
    this model, or the key is rejected."""
    import importlib.util as iu

    status: dict = {"endpoint": CFG["model"]["base_url"],
                    "model": CFG["model"]["name"], "available": None}

    # What the endpoint actually serves. Ollama exposes GET /v1/models.
    try:
        status["available"] = sorted(m.id for m in client.models.list().data)
    except Exception:                                          # noqa: BLE001
        pass

    try:
        _chat("Réponds par OK.", "ping")
        status["llm"] = "ok"
    except Exception as err:                                   # noqa: BLE001
        name = type(err).__name__
        if "Connection" in name or "Timeout" in name:
            status["llm"] = "server unreachable"
            status["fix"] = ("Nothing is listening on this endpoint. Run `ollama serve`, "
                             "or fix base_url in config.yaml.")
        elif "NotFound" in name:
            status["llm"] = f"server ok, unknown model \"{CFG['model']['name']}\""
            status["fix"] = (f"The server answers but does not have this model. "
                             f"`ollama pull {CFG['model']['name']}`, or copy a tag "
                             f"from the list above into config.yaml.")
        elif "Authentication" in name or "Permission" in name:
            status["llm"] = "key rejected"
            status["fix"] = (f"The variable {CFG['model']['api_key_env']} is missing "
                             "or invalid. Check .env.")
        else:
            status["llm"] = f"{name}: {err}"
            status["fix"] = ""

    # Embeddings: through Ollama (no extra package) or sentence-transformers.
    rcfg = CFG["retrieval"]
    if rcfg.get("embedder_backend", "ollama") == "ollama":
        try:
            from openai import OpenAI
            OpenAI(base_url=rcfg.get("embeddings_base_url", "http://localhost:11434/v1"),
                   api_key="ollama").embeddings.create(model=rcfg["embedder"], input=["ping"])
            status["embeddings"] = f"ok via Ollama ({rcfg['embedder']})"
        except Exception as err:                               # noqa: BLE001
            name = type(err).__name__
            status["embeddings"] = ("embedding model missing: "
                                    f"ollama pull {rcfg['embedder'].split(':')[0]}"
                                    if "NotFound" in name else f"unavailable ({name})")
    else:
        status["embeddings"] = ("ok via sentence-transformers"
                                if iu.find_spec("sentence_transformers")
                                else "uv sync --extra rerank")
    status["dense_ok"] = str(status["embeddings"]).startswith("ok")
    status["reranker"] = bool(iu.find_spec("sentence_transformers"))
    status["chemistry"] = bool(iu.find_spec("pyscf")) and bool(iu.find_spec("rdkit"))
    return status


# ------------------------------------------------------------------ facade
def answer(markdown: str, paper_id: str, smiles: str, n_heavy_atoms: int,
           mode: str = "rerank") -> dict:
    t0 = time.time()
    chunks = parse(markdown, paper_id)
    retriever = Retriever(chunks, CFG["retrieval"])
    card = extract(retriever, paper_id, mode=mode)
    spec, note = compile_spec(card, smiles)
    out = {"card": card.model_dump(), "missing": card.missing(),
           "effective_mode": getattr(retriever, "last_mode", mode),
           "model": CFG["model"]["name"],
           "spec": spec.model_dump() if spec else None, "compile_note": note}
    if spec:
        out["validation"] = validate(spec, n_heavy_atoms)
    out["seconds"] = round(time.time() - t0, 2)
    return out
