"""Recover the original v2 coordinate layout of a 57-dimensional CMA checkpoint."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import numpy as np

from .params import ParamCodec
from .scenarios import SCENARIOS, uses_legacy_v2_timer
from .util import read_json


def legacy_layout(current: ParamCodec, checkpoint: Path, state: dict, frozen_units) -> ParamCodec:
    """Prefer a real parameter document. Reconstruct only known historical layouts as a fallback."""
    expected = np.asarray(state["es"].boundary_handler.bounds, dtype=float)

    def matches(codec: ParamCodec) -> bool:
        return (codec.dim == 57 and uses_legacy_v2_timer(codec.doc)
                and np.array_equal(np.asarray(codec.bounds()), expected))

    if matches(current):
        return current

    stored_path = (state.get("config") or {}).get("params")
    generation_snapshot = checkpoint.parent.parent / "params" / f"mean_gen{state['gen']:04d}.json"
    candidates = ([Path(stored_path)] if stored_path else []) + [generation_snapshot]
    for path in candidates:
        doc = read_json(path)
        if isinstance(doc, dict) and uses_legacy_v2_timer(doc):
            codec = ParamCodec(path, frozen_units=frozen_units, document=doc)
            if matches(codec):
                return codec

    template = SCENARIOS["hardupv2"][0]
    if current.path.resolve() == template.resolve():
        doc = deepcopy(current.doc)
        doc["schema"] = "rwx-rl-ai-v1"
        doc["building"]["attemptIntervalFrames"]["value"] = 180
        group = {}
        for name, value in doc["impossible"].items():
            group[name] = value
            if name == "seaGroupMaxUnits":
                group["defensiveScoreBase"] = {
                    "name": "防守分基数（帧）", "type": "float",
                    "value": 190, "min": 120, "max": 400, "step": 10,
                }
        doc["impossible"] = group
        codec = ParamCodec(template, frozen_units=frozen_units, document=doc)
        if matches(codec):
            return codec
        # Archived Hard-equivalent experiments lowered both land-group minima to 6.
        doc["impossible"]["attackGroupMaxUnitsNarrow"]["min"] = 6
        doc["impossible"]["attackGroupMaxUnitsWide"]["min"] = 6
        codec = ParamCodec(template, frozen_units=frozen_units, document=doc)
        if matches(codec):
            return codec

    raise ValueError("Cannot match the 57-dimensional v2 checkpoint layout; "
                     "provide its original parameter JSON via --params")
