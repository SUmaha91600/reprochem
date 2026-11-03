"""Every figure of the report and the slides, generated from the measurement files.

    uv run --with matplotlib python scripts/figures.py

Nothing is typed by hand: each figure reads a file written by a script, and a
figure whose input is missing is skipped with a message.

| Figure | Reads | Shows |
|---|---|---|
| fig1_distillation | eval/report_*.json | base -> distilled -> teacher, 95% CI, share of the gap closed |
| fig2_training | logs/train.log | loss curves; run 1 (NaN) against run 2 |
| fig3_errors | eval/report_*.json + papers | every field: correct, or which stage failed |
| fig4_retrieval | docs/retrieval_ablation.json | recall@k, and recall against prompt length |
| fig5_fields | eval/report_*.json | accuracy per field and system |
| fig6_red_team | docs/red_team_results.md | which attack held, per system |
| fig7_voice | eval/voice_results.json | WER, intent accuracy, latency of the voice module |

Output: docs/figures/*.png (light, for the report), docs/figures/dark/*.png
(dark, for the slides), docs/figures/metrics.json (the derived numbers:
gap closed, paired differences, WER) and docs/figures.md.
"""
from __future__ import annotations

import json
import random
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

OUT = ROOT / "docs/figures"
REPORTS = [("student-base", "eval/report_student-base.json"),
           ("student-lora", "eval/report_student-lora.json"),
           ("teacher", "eval/report_teacher.json")]
NAMES = {"student-base": "Qwen3-1.7B (base)", "student-lora": "Qwen3-1.7B + LoRA",
         "teacher": "Claude (teacher)"}
FIELDS = ("functional", "basis", "dispersion", "solvation", "charge", "multiplicity", "software")

# Reference palette of the dataviz method: categorical slots 1-3 (validated
# all-pairs for colour-blind readers), status colours kept for held / failed.
THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781",
                  grid="#e1e0d9", axis="#c3c2b7",
                  series=["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
                  seq=["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]),
    "dark": dict(surface="#1a1a19", ink="#f0efec", ink2="#c3c2b7", muted="#898781",
                 grid="#2c2c2a", axis="#383835",
                 series=["#3987e5", "#d95926", "#199e70", "#c98500"],
                 seq=["#184f95", "#1c5cab", "#2a78d6", "#6da7ec", "#cde2fb"]),
}
GOOD, CRITICAL, NEUTRAL = "#0ca30c", "#d03b3b", "#898781"
SYS_COLOR = {"student-base": 0, "student-lora": 1, "teacher": 2}

derived: dict = {}


# ------------------------------------------------------------------ helpers
def plt_setup(theme: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t = THEMES[theme]
    plt.rcParams.update({
        "figure.facecolor": t["surface"], "axes.facecolor": t["surface"],
        "savefig.facecolor": t["surface"], "text.color": t["ink"],
        "axes.labelcolor": t["ink2"], "axes.edgecolor": t["axis"],
        "xtick.color": t["muted"], "ytick.color": t["muted"],
        "axes.grid": True, "grid.color": t["grid"], "grid.linewidth": 0.6,
        "axes.spines.top": False, "axes.spines.right": False,
        "font.size": 10.5, "axes.titlesize": 13, "axes.titleweight": "bold",
        "axes.titlelocation": "left", "legend.frameon": False,
        "font.family": "DejaVu Sans",
    })
    return plt, t


def save(fig, name: str, theme: str):
    d = OUT if theme == "light" else OUT / "dark"
    d.mkdir(parents=True, exist_ok=True)
    fig.savefig(d / f"{name}.png", dpi=200, bbox_inches="tight")
    import matplotlib.pyplot as plt
    plt.close(fig)


def note(fig, text: str, t, y: float = -0.02):
    fig.text(0.01, y, text, ha="left", va="top", fontsize=8.5, color=t["muted"], wrap=True)


def load_reports() -> dict:
    reps = {}
    for label, p in REPORTS:
        fp = ROOT / p
        if fp.exists():
            reps[label] = json.loads(fp.read_text())
    return reps


def field_vector(rep: dict, key: str) -> dict:
    """(paper, field) -> 0/1 for one per-field flag of eval.py."""
    out = {}
    for p in rep["per_paper"]:
        for f in FIELDS:
            v = p["fields"][f].get(key)
            if v is not None:
                out[(p["paper_id"], f)] = 1.0 if v else 0.0
    return out


def paired_diff(a: dict, b: dict, samples: int = 2000) -> list | None:
    """Mean of b - a over the fields both systems were scored on, with a paired
    95% bootstrap interval (same resampling as eval.py: fields, seed 0)."""
    keys = sorted(set(a) & set(b))
    if not keys:
        return None
    d = [b[k] - a[k] for k in keys]
    rng = random.Random(0)
    means = sorted(sum(rng.choices(d, k=len(d))) / len(d) for _ in range(samples))
    return [round(sum(d) / len(d), 3), round(means[int(0.025 * samples)], 3),
            round(means[int(0.975 * samples)], 3), len(d)]


# ---------------------------------------------------- fig 1 · distillation
METRICS = [("field_accuracy", "Correct field", "correct", True),
           ("abstention", "NOT_FOUND when absent", "abstained_ok", True),
           ("hallucination", "Invented value when absent", "hallucinated", False),
           ("citation_verified", "Value inside its quote", "cited", True),
           ("teacher_agreement", "Same answer as the teacher", None, True)]


def fig_distillation(reps, theme):
    if not {"student-base", "student-lora"} <= set(reps):
        return "needs report_student-base.json and report_student-lora.json"
    plt, t = plt_setup(theme)
    rows = [m for m in METRICS if any(reps[s].get(m[0]) for s in reps)]
    fig, ax = plt.subplots(figsize=(8.6, 0.72 * len(rows) + 1.6))
    order = [s for s in ("student-base", "student-lora", "teacher") if s in reps]
    for i, (key, lbl, _flag, _up) in enumerate(rows):
        y = len(rows) - 1 - i
        pts = []
        for j, s in enumerate(order):
            v = reps[s].get(key)
            if not v or (s == "teacher" and key == "teacher_agreement"):   # 1.00 by definition
                continue
            off = (j - (len(order) - 1) / 2) * 0.18
            c = t["series"][SYS_COLOR[s]]
            ax.plot([v[1], v[2]], [y + off, y + off], color=c, lw=2, solid_capstyle="round", alpha=0.85)
            ax.scatter([v[0]], [y + off], s=64, color=c, zorder=3, edgecolor=t["surface"], linewidth=2,
                       label=NAMES[s] if i == 0 else None)
            pts.append((s, v[0]))
        if len(pts) >= 2 and pts[0][0] == "student-base" and pts[1][0] == "student-lora":
            ax.annotate("", xy=(pts[1][1], y), xytext=(pts[0][1], y),
                        arrowprops=dict(arrowstyle="-|>", color=t["muted"], lw=1, shrinkA=7, shrinkB=7))
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[1] + ("  ↓" if not r[3] else "") for r in reversed(rows)], color=t["ink"])
    ax.set_xlim(-0.02, 1.02)
    ax.set_xlabel("rate on the gold set (dot = mean, bar = 95% bootstrap interval)")
    ax.grid(axis="y", visible=False)

    # Derived numbers: gap closed and paired differences.
    gaps, diffs = {}, {}
    for key, lbl, flag, up in METRICS:
        b, l, te = (reps.get(s, {}).get(key) for s in ("student-base", "student-lora", "teacher"))
        if b and l and te and abs(te[0] - b[0]) >= 0.02:
            gaps[key] = round((l[0] - b[0]) / (te[0] - b[0]), 2)
        if flag:
            diffs[key] = paired_diff(field_vector(reps["student-base"], flag),
                                     field_vector(reps["student-lora"], flag))
    derived["distillation"] = {"gap_closed": gaps, "lora_minus_base_paired": diffs}
    title = "Distillation: what the LoRA student gained"
    if "field_accuracy" in gaps:
        title += f"  ·  {gaps['field_accuracy']:.0%} of the base→teacher gap closed"
    ax.set_title(title)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=3)
    d = diffs.get("field_accuracy")
    if d:
        verdict = ("the interval excludes 0" if d[1] > 0 or d[2] < 0 else "the interval includes 0: not significant at 95%")
        note(fig, f"Correct field, LoRA − base, paired over {d[3]} fields: {d[0]:+.2f} "
                  f"[{d[1]:+.2f}, {d[2]:+.2f}], {verdict}. Gap closed = (LoRA − base) / (teacher − base).", t, y=-0.07)
    save(fig, "fig1_distillation", theme)


# -------------------------------------------------------- fig 2 · training
def parse_train_log():
    p = ROOT / "logs/train.log"
    if not p.exists():
        return None
    s = p.read_text(errors="replace")
    starts = [m.start() for m in re.finditer(r"Iter 1: Val loss", s)] + [len(s)]
    runs = []
    for a, b in zip(starts, starts[1:]):
        seg = s[a:b]
        num = lambda x: float("nan") if x == "nan" else float(x)
        runs.append({
            "train": [(int(i), num(v)) for i, v in re.findall(r"Iter (\d+): Train loss ([\d.]+|nan)", seg)],
            "val": [(int(i), num(v)) for i, v in re.findall(r"Iter (\d+): Val loss ([\d.]+|nan)", seg)],
            "mem": max([float(m) for m in re.findall(r"Peak mem ([\d.]+) GB", seg)] or [0]),
        })
    return runs


def fig_training(theme):
    import math
    runs = parse_train_log()
    if not runs:
        return "needs logs/train.log"
    plt, t = plt_setup(theme)
    fig, ax = plt.subplots(figsize=(8.6, 4.2))
    final = runs[-1]
    info = {}
    for k, r in enumerate(runs):
        last = k == len(runs) - 1
        c = t["series"][1] if last else t["muted"]
        name = f"run {k + 1}" + (" (delivered)" if last else "")
        tr = [(i, v) for i, v in r["train"] if not math.isnan(v)]
        va = [(i, v) for i, v in r["val"] if not math.isnan(v)]
        if tr:
            ax.plot(*zip(*tr), color=c, lw=1.2, alpha=0.45 if last else 0.6, label=f"{name} · train")
        if va:
            ax.plot(*zip(*va), color=c, lw=2, marker="o", ms=6, label=f"{name} · validation")
        first_nan = next((i for i, v in r["train"] if math.isnan(v)), None)
        if first_nan:
            ax.axvline(first_nan, color=CRITICAL, lw=1, ls="--")
            ax.text(first_nan + 12, 2.2e-3, f"run {k + 1}: loss = NaN from iteration {first_nan}\n"
                    "(prompts longer than max-seq: no target token, loss 0/0)",
                    color=CRITICAL, fontsize=8.5, va="bottom")
            info[f"run{k + 1}_first_nan_iter"] = first_nan
    ax.set_yscale("log")
    ax.set_xlabel("iteration (batch 1)")
    ax.set_ylabel("loss (log scale)")
    ax.set_title("Training the student: same seed, same curve until run 1 broke")
    ax.legend(loc="upper right", fontsize=8.5)
    va = [(i, v) for i, v in final["val"] if not math.isnan(v)]
    if va:
        info.update(val_first=va[0], val_last=va[-1], val_best=min(va, key=lambda x: x[1]),
                    peak_mem_gb=final["mem"])
        note(fig, f"Delivered run: validation loss {va[0][1]:.3f} (iteration {va[0][0]}) → {va[-1][1]:.3f} "
                  f"(iteration {va[-1][0]}); peak memory {final['mem']:.1f} GB. Source: logs/train.log.", t)
    derived["training"] = info
    save(fig, "fig2_training", theme)


# --------------------------------------------------------- fig 3 · errors
CATS = [("correct", "correct"), ("retrieval", "retrieval: value not in the 3 passages"),
        ("wrong", "generation: wrong value"), ("abstain", "generation: wrong NOT_FOUND"),
        ("invent", "generation: invented value")]


def classify(reps):
    from app.pipeline import CFG, Retriever, parse, retrieve
    from eval import normalise
    ts = {json.loads(l)["paper_id"]: json.loads(l) for l in (ROOT / "eval/testset.jsonl").open() if l.strip()}
    rec = {}
    for pid, t in ts.items():
        md = (ROOT / t["markdown_path"]).read_text(encoding="utf-8", errors="replace")
        r = Retriever(parse(md, pid), CFG["retrieval"])
        for f in FIELDS:
            if t["fields"][f] != "NOT_FOUND":
                txt = normalise(" ".join(c.text for c, _ in retrieve(r, f, mode="bm25")))
                rec[(pid, f)] = normalise(t["fields"][f]) in txt
    out = {}
    for s, rep in reps.items():
        n = {k: 0 for k, _ in CATS}
        for p in rep["per_paper"]:
            for f in FIELDS:
                row = p["fields"][f]
                if row["correct"]:
                    n["correct"] += 1
                elif row["gold"] == "NOT_FOUND":
                    n["invent"] += 1
                elif not rec.get((p["paper_id"], f), True):
                    n["retrieval"] += 1
                elif row["value"] == "NOT_FOUND":
                    n["abstain"] += 1
                else:
                    n["wrong"] += 1
        out[s] = n
    return out


def fig_errors(reps, theme):
    if not reps:
        return "needs eval/report_*.json"
    plt, t = plt_setup(theme)
    counts = derived.get("errors") or classify(reps)
    derived["errors"] = counts
    order = [s for s in ("student-base", "student-lora", "teacher") if s in counts]
    colors = {"correct": t["grid"] if theme == "light" else "#383835",
              "retrieval": t["series"][0], "wrong": t["series"][1],
              "abstain": t["series"][3], "invent": CRITICAL}
    fig, ax = plt.subplots(figsize=(8.6, 0.8 * len(order) + 1.8))
    seen = set()
    for y, s in enumerate(reversed(order)):
        left, tot = 0, sum(counts[s].values())
        for k, lbl in CATS:
            v = counts[s][k]
            if not v:
                continue
            ax.barh(y, v, left=left, color=colors[k], height=0.55, edgecolor=t["surface"], linewidth=2,
                    label=lbl if k not in seen else None)
            seen.add(k)
            ink = t["ink"] if k == "correct" or k == "abstain" else "#ffffff"
            if v / tot > 0.04:
                ax.text(left + v / 2, y, str(v), ha="center", va="center", color=ink, fontsize=9)
            left += v
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([NAMES[s] for s in reversed(order)], color=t["ink"])
    ax.set_xlabel(f"fields of the gold set ({sum(counts[order[0]].values())})")
    ax.grid(axis="y", visible=False)
    ax.set_title("Where each field is lost: retrieval or generation")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=colors[k], label=lbl) for k, lbl in CATS],
              loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=3, fontsize=8.5)
    note(fig, "Retrieval error: the gold value is absent from the 3 BM25 passages, so no model could have "
              "quoted it. Same passages for all three systems.", t)
    save(fig, "fig3_errors", theme)


# ------------------------------------------------------ fig 4 · retrieval
def fig_retrieval(theme):
    p = ROOT / "docs/retrieval_ablation.json"
    if not p.exists():
        return "needs docs/retrieval_ablation.json (scripts/retrieval_ablation.py)"
    ab = json.loads(p.read_text())
    plt, t = plt_setup(theme)
    prod = ab["production"]["label"]
    rows = ab["rows"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.4), gridspec_kw={"width_ratios": [1, 1.15]})
    # left: recall@k for the production setting and the retriever alternatives
    show = [r for r in rows if r["label"] == prod]
    ks = list(range(1, ab["kmax"] + 1))
    for r in show:
        idx = {"bm25": 1, "dense": 0, "hybrid": 2}[r["retriever"]]
        name = {"bm25": "BM25", "dense": f"dense ({r.get('model', '')})", "hybrid": "hybrid (RRF)"}[r["retriever"]]
        a1.plot(ks, r["recall_at_k"], color=t["series"][idx], lw=2, marker="o", ms=5, label=name)
    a1.axvline(ab["production"]["top_k"], color=t["muted"], lw=1, ls="--")
    a1.text(ab["production"]["top_k"] + 0.15, 0.52, f"k = {ab['production']['top_k']}\n(what the\nstudent reads)",
            color=t["muted"], fontsize=8.5)
    a1.set_ylim(0.5, 1.02)
    a1.set_xticks(ks)
    a1.set_xlabel("k passages")
    a1.set_ylabel("recall@k (present fields)")
    a1.set_title(f"Recall@k · {prod}")
    a1.legend(loc="lower right")
    # right: trade-off recall@3 vs prompt length, BM25 chunkings
    bm = [r for r in rows if r["retriever"] == "bm25"]
    use_tok = all(r.get("median_prompt_tokens") for r in bm)
    xkey = "median_prompt_tokens" if use_tok else "median_context_words_top3"
    for r in bm:
        c3 = r["recall_at_3_ci"]
        x = r[xkey]
        is_prod = r["label"] == prod
        col = t["series"][1] if is_prod else (t["series"][0] if r["chunking"] == "sections" else t["series"][2])
        a2.errorbar(x, c3[0], yerr=[[c3[0] - c3[1]], [c3[2] - c3[0]]], fmt="o", ms=9 if is_prod else 6,
                    color=col, ecolor=col, elinewidth=1.2, alpha=1 if is_prod else 0.8,
                    markeredgecolor=t["surface"], markeredgewidth=1.5, zorder=3 if is_prod else 2)
        short = "all" if r["size"] is None else str(r["size"])
        a2.annotate(short, (x, c3[0]),
                    xytext=(7, -11) if r["chunking"] == "fixed" else (-7, 5), textcoords="offset points",
                    ha="left" if r["chunking"] == "fixed" else "right",
                    fontsize=8, color=t["ink"] if is_prod else t["ink2"],
                    fontweight="bold" if is_prod else "normal")
    a2.set_xscale("log")
    a2.set_xlabel(("prompt tokens, median" if use_tok else "words in the 3 passages, median") + " (log)")
    a2.set_ylabel("recall@3 (95% CI)")
    a2.set_title("Chunk size: recall against reading cost")
    from matplotlib.lines import Line2D
    a2.legend(handles=[Line2D([], [], marker="o", ls="", color=t["series"][0], label="sections split at N words (all = never split)"),
                       Line2D([], [], marker="o", ls="", color=t["series"][2], label="fixed windows of N words"),
                       Line2D([], [], marker="o", ls="", color=t["series"][1], label="production")],
              loc="lower right", fontsize=8.5)
    a2.set_ylim(0.6, 1.03)
    note(fig, f"{ab['n_papers']} gold papers, {rows[0]['n_fields']} present fields; recall = gold value inside "
              "the passages; no model involved. Source: docs/retrieval_ablation.json.", t)
    fig.tight_layout()
    save(fig, "fig4_retrieval", theme)


# ---------------------------------------------------------- fig 5 · fields
def fig_fields(reps, theme):
    if not reps:
        return "needs eval/report_*.json"
    plt, t = plt_setup(theme)
    from matplotlib.colors import LinearSegmentedColormap
    order = [s for s in ("student-base", "student-lora", "teacher") if s in reps]
    M, lab = [], []
    for f in FIELDS:
        row, lr = [], []
        for s in order:
            v = [p["fields"][f]["correct"] for p in reps[s]["per_paper"]]
            row.append(sum(v) / len(v) if v else float("nan"))
            lr.append(f"{sum(v)}/{len(v)}")
        M.append(row)
        lab.append(lr)
    cmap = LinearSegmentedColormap.from_list("seq", THEMES["light"]["seq"] if theme == "light" else THEMES["dark"]["seq"])
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    ax.imshow(M, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for i in range(len(FIELDS)):
        for j in range(len(order)):
            v = M[i][j]
            ink = "#ffffff" if (v > 0.55) == (theme == "light") else t["ink"]
            if theme == "dark":
                ink = t["surface"] if v > 0.6 else t["ink"]
            ax.text(j, i, lab[i][j], ha="center", va="center", color=ink, fontsize=9.5)
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([NAMES[s].replace(" (", "\n(") for s in order], color=t["ink"])
    ax.set_yticks(range(len(FIELDS)))
    ax.set_yticklabels(FIELDS, color=t["ink"])
    ax.grid(False)
    ax.set_title("Correct fields, per setting")
    note(fig, "Cell = correct / scored (13 papers per field). Darker = higher.", t)
    save(fig, "fig5_fields", theme)


# ------------------------------------------------------ fig 6 · red team
def fig_red_team(theme):
    p = ROOT / "docs/red_team_results.md"
    if not p.exists():
        return "needs docs/red_team_results.md (scripts/red_team.py)"
    rows = []
    for line in p.read_text().splitlines():
        m = re.match(r"\| (R\d) \| ([^|]+) \| (\w+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|", line)
        if m:
            rid, name, field, want, teacher, got, held = (x.strip() for x in m.groups())
            norm = lambda v: v.upper().replace(" ", "").replace("-", "")
            rows.append(dict(id=rid, name=name, field=field, want=want,
                             teacher=None if teacher in ("—", "") else norm(teacher) == norm(want),
                             student=held == "yes", got=got, t_val=teacher))
    if not rows:
        return "no table found in docs/red_team_results.md"
    plt, t = plt_setup(theme)
    fig, ax = plt.subplots(figsize=(8.6, 0.42 * len(rows) + 1.4))
    cols = [("teacher", "Claude (teacher)"), ("student", "Qwen3-1.7B + LoRA")]
    for i, r in enumerate(rows):
        y = len(rows) - 1 - i
        for j, (k, _) in enumerate(cols):
            v = r[k]
            c = NEUTRAL if v is None else (GOOD if v else CRITICAL)
            sym = "–" if v is None else ("✓ held" if v else "✗ failed")
            ax.add_patch(__import__("matplotlib").patches.FancyBboxPatch(
                (j + 0.06, y - 0.36), 0.88, 0.72, boxstyle="round,pad=0,rounding_size=0.08",
                color=c, alpha=0.9))
            val = r["t_val"] if k == "teacher" else r["got"]
            ax.text(j + 0.5, y, f"{sym}  ·  {val}" if v is not None else sym,
                    ha="center", va="center", color="#ffffff", fontsize=8.5, fontweight="bold")
    ax.set_xlim(0, len(cols))
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xticks([j + 0.5 for j in range(len(cols))])
    ax.set_xticklabels([c[1] for c in cols], color=t["ink"])
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([f"{r['id']} {r['name']} · {r['field']} (expect {r['want']})" for r in reversed(rows)],
                       color=t["ink"], fontsize=8.5)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title("Red team: does the extraction resist?", pad=28)
    derived["red_team"] = {"student_held": sum(r["student"] for r in rows), "checks": len(rows)}
    save(fig, "fig6_red_team", theme)


# ---------------------------------------------------------- fig 7 · voice
def wer_norm(s: str) -> list[str]:
    """Lower case, no accents, no punctuation, letters and digits split apart
    ("BP86" and "BP 86" both become "bp 86"). Applied to reference AND hypothesis."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[-/]", " ", s)
    s = re.sub(r"[^a-z0-9+ ]", " ", s)
    s = re.sub(r"(?<=[a-z])(?=[0-9])|(?<=[0-9])(?=[a-z])", " ", s)
    return s.split()


def edit_ops(ref: list[str], hyp: list[str]):
    """Levenshtein alignment on words -> (substitutions, deletions, insertions)."""
    n, m = len(ref), len(hyp)
    D = [[(0, 0, 0, 0)] * (m + 1) for _ in range(n + 1)]   # (cost, S, D, I)
    for i in range(1, n + 1):
        D[i][0] = (i, 0, i, 0)
    for j in range(1, m + 1):
        D[0][j] = (j, 0, 0, j)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                D[i][j] = D[i - 1][j - 1]
                continue
            s, d, ins = D[i - 1][j - 1], D[i - 1][j], D[i][j - 1]
            D[i][j] = min((s[0] + 1, s[1] + 1, s[2], s[3]), (d[0] + 1, d[1], d[2] + 1, d[3]),
                          (ins[0] + 1, ins[1], ins[2], ins[3] + 1))
    _, S, De, I = D[n][m]
    return S, De, I


def voice_stats(items):
    by = {}
    for it in items:
        ref, hyp = wer_norm(it["reference"]), wer_norm(it.get("hypothesis", ""))
        S, De, I = edit_ops(ref, hyp)
        it.update(S=S, D=De, I=I, N=len(ref))
        by.setdefault(it.get("condition", "quiet"), []).append(it)
    out = {}
    rng = random.Random(0)
    for cond, its in by.items():
        err = lambda xs: sum(x["S"] + x["D"] + x["I"] for x in xs) / max(1, sum(x["N"] for x in xs))
        boots = sorted(err(rng.choices(its, k=len(its))) for _ in range(2000))
        ok = [1.0 if x.get("routed") == x.get("expected") else 0.0 for x in its]
        bo = sorted(sum(rng.choices(ok, k=len(ok))) / len(ok) for _ in range(2000))
        lat = sorted(x["latency_ms"] for x in its if x.get("latency_ms") is not None)
        out[cond] = {
            "n": len(its), "words": sum(x["N"] for x in its),
            "wer": [round(err(its), 3), round(boots[50], 3), round(boots[1949], 3)],
            "S": sum(x["S"] for x in its), "D": sum(x["D"] for x in its), "I": sum(x["I"] for x in its),
            "intent_accuracy": [round(sum(ok) / len(ok), 3), round(bo[50], 3), round(bo[1949], 3)],
            "latency_ms_median": lat[len(lat) // 2] if lat else None,
            "latency_ms_p90": lat[int(0.9 * (len(lat) - 1))] if lat else None,
            "latencies": lat,
        }
    return out


def fig_voice(theme):
    p = ROOT / "eval/voice_results.json"
    dl = sorted(Path.home().glob("Downloads/voice_results*.json"), key=lambda x: x.stat().st_mtime)
    if not p.exists() and dl:                      # the browser saves it in Downloads
        p.write_bytes(dl[-1].read_bytes())
        print(f"copied {dl[-1]} -> eval/voice_results.json")
    if not p.exists():
        return "needs eval/voice_results.json (record it on localhost:8765/voicetest.html)"
    data = json.loads(p.read_text())
    st = voice_stats(data["items"])
    derived["voice"] = {k: {kk: vv for kk, vv in v.items() if kk != "latencies"} for k, v in st.items()}
    derived["voice_asr"] = data.get("asr")
    plt, t = plt_setup(theme)
    conds = list(st)
    fig, axs = plt.subplots(1, 3, figsize=(11.5, 3.8))
    for ax, key, title, fmt in ((axs[0], "wer", "Word error rate ↓", "{:.0%}"),
                                (axs[1], "intent_accuracy", "Right concept opened", "{:.0%}")):
        for i, c in enumerate(conds):
            v = st[c][key]
            col = t["series"][i % 4]
            ax.bar(i, v[0], width=0.55, color=col, edgecolor=t["surface"], linewidth=2)
            ax.errorbar(i, v[0], yerr=[[v[0] - v[1]], [v[2] - v[0]]], color=t["ink2"], capsize=4, lw=1.2)
            ax.text(i, v[2] + 0.02, fmt.format(v[0]), ha="center", va="bottom", color=t["ink"], fontsize=10)
        ax.set_xticks(range(len(conds)))
        ax.set_xticklabels([f"{c}\n(n={st[c]['n']})" for c in conds], color=t["ink"])
        ax.set_ylim(0, 1.12)
        ax.set_title(title, fontsize=11.5)
        ax.grid(axis="x", visible=False)
    ax = axs[2]
    for i, c in enumerate(conds):
        lat = st[c]["latencies"]
        if lat:
            jit = [i + (k % 7 - 3) * 0.035 for k in range(len(lat))]
            ax.scatter(jit, lat, s=22, color=t["series"][i % 4], alpha=0.75, edgecolor="none")
            ax.hlines(st[c]["latency_ms_median"], i - 0.25, i + 0.25, color=t["ink"], lw=2)
    ax.set_xticks(range(len(conds)))
    ax.set_xticklabels(conds, color=t["ink"])
    ax.set_ylabel("ms")
    ax.set_title("Release of Space → final transcript", fontsize=11.5)
    ax.grid(axis="x", visible=False)
    fig.suptitle(f"Voice module · {data.get('asr', 'browser speech recognition')}", x=0.01, ha="left",
                 fontweight="bold", fontsize=13)
    note(fig, "WER = (S + D + I) / N over all words of a condition, after lower-casing and removing "
              "punctuation (2 Nov lecture, slide 15). WER is not meaning, so the task is scored too: "
              "did the sentence open the expected concept? 95% bootstrap intervals over sentences.", t)
    fig.tight_layout()
    save(fig, "fig7_voice", theme)


# --------------------------------------------------------------------- main
CAPTIONS = {
    "fig1_distillation": "Base student, distilled student and teacher on the same passages.",
    "fig2_training": "Loss curves of the LoRA runs, read from the training log.",
    "fig3_errors": "Each gold field: correct, lost at retrieval, or lost at generation.",
    "fig4_retrieval": "Retrieval on its own: recall@k, and recall@3 against prompt length per chunk size.",
    "fig5_fields": "Correct fields per setting and system.",
    "fig6_red_team": "The five attacks of the red team, per system.",
    "fig7_voice": "Voice module: word error rate, intent accuracy, recognition latency.",
}


def main() -> int:
    reps = load_reports()
    jobs = [("fig1_distillation", lambda th: fig_distillation(reps, th)),
            ("fig2_training", fig_training),
            ("fig3_errors", lambda th: fig_errors(reps, th)),
            ("fig4_retrieval", fig_retrieval),
            ("fig5_fields", lambda th: fig_fields(reps, th)),
            ("fig6_red_team", fig_red_team),
            ("fig7_voice", fig_voice)]
    made = []
    for name, fn in jobs:
        status = None
        for th in ("light", "dark"):
            try:
                status = fn(th)
            except Exception as e:  # one broken input must not stop the others
                status = f"error: {type(e).__name__}: {e}"
            if status:
                break
        print(f"{name:<20} {'skipped · ' + status if status else 'ok'}")
        if not status:
            made.append(name)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(derived, indent=2, ensure_ascii=False, default=str))
    L = ["# Figures", "", "*Generated by `scripts/figures.py` from the measurement files. "
         "Dark versions for slides: `docs/figures/dark/`. Derived numbers: `docs/figures/metrics.json`.*", ""]
    for n in made:
        L += [f"## {CAPTIONS[n]}", "", f"![{n}](figures/{n}.png)", ""]
    (ROOT / "docs/figures.md").write_text("\n".join(L), encoding="utf-8")
    print(f"\n{len(made)} figures → docs/figures/ · docs/figures.md · docs/figures/metrics.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
