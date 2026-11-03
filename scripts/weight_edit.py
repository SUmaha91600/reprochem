"""Weight-space edit of the student, measured like everything else.

Inspired by "weight-space programming" (rikiyat.github.io/blog/weight-space-programming):
change a small, chosen part of the weights to fix one measured failure, then
re-evaluate on held-out data. Here the failure is the one the benchmark found:
the LoRA student answers NOT_FOUND when the value is in the passages (11 of
its 26 errors). The edit is the simplest reproducible version of the idea:
a direction found from activations (the "activation addition" family, Turner
et al. 2023; Arditi et al. 2024), added as a bias to the MLP output of a few
layers. No language model writes the edit, so it is fully reproducible.

    uv run python scripts/weight_edit.py find  --label student-lora --adapter adapters/qwen3-1.7b-reprochem
    uv run python scripts/weight_edit.py sweep --label student-lora --adapter adapters/qwen3-1.7b-reprochem
    REPROCHEM_EDIT=eval/weight_edit/student-lora.json ... eval/eval.py   (scripts/mac_weight_edit.sh does it all)

Data discipline:
  find   data/sft/train.jsonl  (teacher labels, training papers) -> direction per layer
  sweep  data/sft/valid.jsonl  (other papers)                    -> layers and beta
  eval   eval/testset.jsonl    (gold set, seen once)             -> the comparison
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
OUT = ROOT / "eval/weight_edit"
NF = "NOT_FOUND"


def _mx_call(name, *a):
    """MLX moved these from mx.metal to mx; support both."""
    import mlx.core as mx
    fn = getattr(mx, name, None) or getattr(getattr(mx, "metal", None), name, None)
    if fn:
        try:
            fn(*a)
        except Exception:  # noqa: BLE001 - a cap that cannot be set must not stop the run
            pass


def cap_memory() -> None:
    """Keeps MLX well inside a 16 GB Mac: REPROCHEM_MLX_GB (default 6) for
    everything, 1 GB of reusable cache. Over the cap MLX raises an error
    instead of pushing macOS into swap."""
    gb = float(os.environ.get("REPROCHEM_MLX_GB", "6"))
    _mx_call("set_memory_limit", int(gb * 2**30))
    _mx_call("set_cache_limit", 2**30)


def load_model(adapter):
    from mlx_lm import load
    cap_memory()
    base = os.environ.get("REPROCHEM_MODEL") or (ROOT / "adapters/BASE_MODEL").read_text().strip()
    return load(base, adapter_path=adapter or None)


def rows(path):
    return [json.loads(l) for l in (ROOT / path).open() if l.strip()]


def target(r) -> str:
    try:
        return str(json.loads(r["messages"][-1]["content"]).get("value", NF)).strip() or NF
    except json.JSONDecodeError:
        return NF


def prompt_of(tok, r) -> str:
    return tok.apply_chat_template(r["messages"][:2], add_generation_prompt=True, tokenize=False)


def find(args) -> int:
    import mlx.core as mx
    from app import weight_edit as W

    t_load = time.time()
    model, tok = load_model(args.adapter)
    print(f"model loaded in {time.time() - t_load:.0f} s · {args.n} examples per side", flush=True)
    data = rows("data/sft/train.jsonl")
    rng = random.Random(0)
    pos = [r for r in data if target(r) != NF]
    neg = [r for r in data if target(r) == NF]
    rng.shuffle(pos), rng.shuffle(neg)
    pos, neg = pos[:args.n], neg[:args.n]
    W.add_probes(model)
    acts = {"pos": [], "neg": []}
    t0 = time.time()
    for name, group in (("pos", pos), ("neg", neg)):
        for k, r in enumerate(group, 1):
            ids = mx.array(tok.encode(prompt_of(tok, r)))[None]
            # The transformer body only: the full model would also build the
            # logits, (prompt length × 151,936 vocabulary), several GB on a long
            # prompt, for nothing. That is what froze the Mac.
            mx.eval(model.model(ids))
            acts[name].append(np.stack([W.CAPTURE[i] for i in range(len(W.layers(model)))]))
            del ids
            _mx_call("clear_cache")
            if k == 1 or k % 10 == 0:
                print(f"  {name} {k}/{len(group)} · {time.time() - t0:.0f} s", flush=True)
    W.remove_probes(model)
    P, N = np.stack(acts["pos"]), np.stack(acts["neg"])          # (n, layers, d)
    diff = P.mean(0) - N.mean(0)                                 # (layers, d)
    unit = diff / (np.linalg.norm(diff, axis=1, keepdims=True) + 1e-8)
    sep = []
    for i in range(diff.shape[0]):                               # Cohen's d of the projections
        p, n = P[:, i] @ unit[i], N[:, i] @ unit[i]
        sep.append(float((p.mean() - n.mean()) / np.sqrt((p.var() + n.var()) / 2 + 1e-8)))
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez(OUT / f"{args.label}_directions.npz", **{f"layer{i}": diff[i] for i in range(diff.shape[0])})
    (OUT / f"{args.label}_separation.json").write_text(json.dumps(
        {"n_pos": len(pos), "n_neg": len(neg), "cohens_d_per_layer": sep}, indent=2))
    best = sorted(range(len(sep)), key=lambda i: -sep[i])[:5]
    print("separation (Cohen's d) per layer:", " ".join(f"{i}:{s:.1f}" for i, s in enumerate(sep)))
    print("best layers:", best, f"· {time.time() - t0:.0f} s")
    return 0


def sweep(args) -> int:
    from mlx_lm import generate
    from mlx_lm.sample_utils import make_sampler
    from app import weight_edit as W
    from app.pipeline import _json_block
    from eval import normalise

    sep = json.loads((OUT / f"{args.label}_separation.json").read_text())["cohens_d_per_layer"]
    n_layers = len(sep)
    lo, hi = n_layers // 4, n_layers - 2                          # skip the first and last layers
    layer_ids = args.layers or sorted(sorted(range(lo, hi), key=lambda i: -sep[i])[:2])
    d = np.load(OUT / f"{args.label}_directions.npz")
    t_load = time.time()
    print("sweep: loading the model...", flush=True)
    model, tok = load_model(args.adapter)
    print(f"sweep: model loaded in {time.time() - t_load:.0f} s", flush=True)
    wrappers = W.add_edit(model, {k: d[k] for k in d.files}, layer_ids)
    valid = rows("data/sft/valid.jsonl")[:args.n_valid]
    sampler = make_sampler(temp=0.0)
    table = []
    for beta in args.betas:
        for w in wrappers:
            w.scale = beta
        ok = inv = miss = 0
        t0 = time.time()
        for j, r in enumerate(valid, 1):
            if j == 1 or j % 10 == 0:
                print(f"  beta {beta:+.2f} · {j}/{len(valid)} · {time.time() - t0:.0f} s", flush=True)
            out = _json_block(generate(model, tok, prompt=prompt_of(tok, r), max_tokens=200, sampler=sampler))
            _mx_call("clear_cache")
            got = str(out.get("value", NF)).strip() or NF
            want = target(r)
            ok += normalise(got) == normalise(want)
            inv += want == NF and got != NF
            miss += want != NF and got == NF
        n_nf = sum(target(r) == NF for r in valid)
        row = {"beta": beta, "accuracy": round(ok / len(valid), 3),
               "invented": f"{inv}/{n_nf}", "wrong_not_found": f"{miss}/{len(valid) - n_nf}"}
        table.append(row)
        print(f"beta {beta:+.2f} · accuracy {row['accuracy']:.2f} · invented {row['invented']}"
              f" · wrong NOT_FOUND {row['wrong_not_found']}", flush=True)
    # Best accuracy; ties go to the smaller edit. beta = 0 is always in the sweep.
    best = sorted(table, key=lambda t: (-t["accuracy"], abs(t["beta"])))[0]
    spec = {"label": args.label, "adapter": args.adapter,
            "directions": str((OUT / f"{args.label}_directions.npz").relative_to(ROOT)),
            "layers": layer_ids, "beta": best["beta"], "chosen_on": "data/sft/valid.jsonl",
            "n_valid": len(valid), "sweep": table,
            "edited_weights": f"bias of down_proj in {len(layer_ids)} of {n_layers} layers"}
    (OUT / f"{args.label}.json").write_text(json.dumps(spec, indent=2))
    print(f"\nchosen: layers {layer_ids}, beta {best['beta']:+.2f} -> eval/weight_edit/{args.label}.json")
    if best["beta"] == 0:
        print("no edit beats the unedited model on validation: the gold-set run will equal the baseline")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["find", "sweep"])
    ap.add_argument("--label", required=True)
    ap.add_argument("--adapter", default="")
    ap.add_argument("--n", type=int, default=80, help="examples per contrast set (find)")
    ap.add_argument("--n-valid", type=int, default=50)
    ap.add_argument("--layers", type=int, nargs="*", default=None)
    ap.add_argument("--betas", type=float, nargs="*", default=[-0.25, 0.0, 0.25, 0.5, 1.0])
    args = ap.parse_args()
    return find(args) if args.step == "find" else sweep(args)


if __name__ == "__main__":
    sys.exit(main())
