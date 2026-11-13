"""Load a micro case's `config.json` for scoring.

One file is the source of truth for both the engine's map tuning and the offline score. This
module only reads the `evaluation` section; the engine reads `run` and `map`.
"""
from __future__ import annotations

import json
from pathlib import Path


def load_case(case_dir: Path) -> dict:
    path = Path(case_dir) / "config.json"
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def evaluation(case_dir: Path) -> dict:
    config = load_case(case_dir)
    section = config.get("evaluation")
    if not isinstance(section, dict):
        raise ValueError(f"{case_dir}/config.json has no evaluation object")
    return section
