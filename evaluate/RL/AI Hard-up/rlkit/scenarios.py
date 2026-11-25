"""Hard-up experiment defaults and recognition of historical weight documents."""

from __future__ import annotations

from pathlib import Path

from .paths import HERE, PARAMS, POOL
from .util import read_json


SCENARIOS = {
    "hardupv1": (HERE / "params_Hardupv1.json", HERE / "completition_v1-19.json"),
    "hardupv2": (PARAMS, POOL),
    "hardupv3": (HERE / "params_Hardupv3.json", POOL),
    "hardupv4": (HERE / "params_Hardupv4.json", POOL),
}

V3_REWARD_SCENARIOS = {"hardupv3", "hardupv4"}


def scenario_for_document(doc: dict) -> str:
    schema = doc.get("schema")
    if schema == "rwx-rl-ai-v4":
        return "hardupv4"
    if schema == "rwx-rl-ai-v3":
        return "hardupv3"
    # Older v2 runs used v1 schema or had no schema. Takeover tables identify their parameter layout.
    if schema == "rwx-rl-ai-v2" or "buildingScore" in doc or "impossible" in doc:
        return "hardupv2"
    return "hardupv1"


def uses_legacy_v2_timer(doc: dict) -> bool:
    if scenario_for_document(doc) != "hardupv2" or doc.get("schema") == "rwx-rl-ai-v2":
        return False
    timer = (doc.get("impossible") or {}).get("defensiveScoreBase")
    return (timer.get("value") if isinstance(timer, dict) else timer) is not None


def identify_params(path: Path, expected: str | None) -> str:
    doc = read_json(path)
    if not isinstance(doc, dict) or not doc:
        raise ValueError(f"Cannot read a parameter document from {path}")
    actual = scenario_for_document(doc)
    if expected is not None and expected != actual:
        raise ValueError(f"Scenario {expected} expects its own parameter layout, but {path} uses {actual}")
    return actual
