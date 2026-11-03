"""A small, targeted weight edit of the student, applied when the model loads.

The edit adds one vector to the output of the MLP (`down_proj`) of a few
layers: a bias term, the same for every token. The vector is the difference
between the mean activations of two contrast sets, measured on the training
data only (scripts/weight_edit.py `find`): answers where the teacher gave a
value, and answers where it said NOT_FOUND. Its scale `beta` is chosen on the
validation set, never on the gold set (`sweep`).

    REPROCHEM_EDIT=eval/weight_edit/student-lora.json  (read by app/pipeline.py)

Spec file: {"directions": "<npz>", "layers": [14, 18], "beta": 0.25, ...}.
beta > 0 pushes toward "a value is present", beta < 0 toward NOT_FOUND,
beta = 0 is the unedited model.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CAPTURE: dict[int, np.ndarray] = {}      # layer -> last-token MLP output (probe mode)


def _nn():
    import mlx.core as mx
    import mlx.nn as nn
    return mx, nn


def layers(model):
    return model.model.layers


def _make_classes():
    mx, nn = _nn()

    class Probe(nn.Module):
        """Records the MLP output at the last position; changes nothing."""

        def __init__(self, inner, idx: int):
            super().__init__()
            self.inner = inner
            self.idx = idx

        def __call__(self, x):
            y = self.inner(x)
            CAPTURE[self.idx] = np.array(y[0, -1].astype(mx.float32))
            return y

    class Biased(nn.Module):
        """down_proj(x) + scale * direction: the weight edit."""

        def __init__(self, inner, direction):
            super().__init__()
            self.inner = inner
            self.direction = direction
            self.scale = 0.0

        def __call__(self, x):
            y = self.inner(x)
            if self.scale == 0.0:
                return y
            return y + (self.scale * self.direction).astype(y.dtype)

    return Probe, Biased


def add_probes(model) -> None:
    Probe, _ = _make_classes()
    for i, layer in enumerate(layers(model)):
        layer.mlp.down_proj = Probe(layer.mlp.down_proj, i)


def remove_probes(model) -> None:
    for layer in layers(model):
        if hasattr(layer.mlp.down_proj, "idx"):
            layer.mlp.down_proj = layer.mlp.down_proj.inner


def add_edit(model, directions: dict, layer_ids: list[int]) -> list:
    """Wraps the chosen layers; returns the wrappers so the scale can be swept."""
    mx, _ = _nn()
    _, Biased = _make_classes()
    out = []
    for i in layer_ids:
        mlp = layers(model)[i].mlp
        mlp.down_proj = Biased(mlp.down_proj, mx.array(directions[f"layer{i}"]))
        out.append(mlp.down_proj)
    return out


def apply(model, spec_path: str) -> dict:
    """Reads a spec written by scripts/weight_edit.py and edits the model in place."""
    spec = json.loads(Path(spec_path).read_text())
    d = np.load(ROOT / spec["directions"]) if not Path(spec["directions"]).is_absolute() \
        else np.load(spec["directions"])
    for w in add_edit(model, {k: d[k] for k in d.files}, spec["layers"]):
        w.scale = float(spec["beta"])
    return spec
