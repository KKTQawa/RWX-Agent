"""多批评测（`test` 子命令）。"""
from __future__ import annotations

from pathlib import Path

import copy
import random
import shutil
import statistics
import tempfile

from .paths import WORK
from .util import read_json, wilson_ci
from .match import load_pool, make_specs
from .config import TrainConfig
from .runner import Runner
from .scenarios import scenario_for_document

# =========================================================================== 评测（也供验证调用）

def evaluate_config(params_path: Path, n_batches: int = 10, games_per_batch: int = 6,
                    seed: int = 2026, cfg: TrainConfig | None = None) -> dict:
    """多批评测：地图轮转、阵营与槽位交换。"""
    cfg = copy.deepcopy(cfg or TrainConfig())
    cfg.n_batches, cfg.games_per_batch = n_batches, games_per_batch
    entries = load_pool(cfg.pool)
    total = n_batches * games_per_batch
    specs = make_specs(entries, random.Random(seed), total, games_per_batch)
    doc = read_json(Path(params_path))
    if cfg.scenario is None and isinstance(doc, dict):
        cfg.scenario = scenario_for_document(doc)

    WORK.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="eval-", dir=str(WORK)))
    cfg.out_dir = workdir.parent
    cfg.run_name = workdir.name
    try:
        runner = Runner(cfg, workdir / "run")
        records = runner.games(doc, specs)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    n = len(records)
    wins = sum(1 for r in records if r.outcome == "win")
    draws = sum(1 for r in records if r.outcome == "draw")
    lo, hi = wilson_ci(wins + 0.5 * draws, n)
    per_map: dict[str, list[str]] = {}
    batch_rate: dict[int, list[bool]] = {}
    per_slot: dict[str, list[str]] = {"slot0": [], "slot1": []}
    per_pair: dict[str, list[str]] = {}
    for r in records:
        per_map.setdefault(r.map, []).append(r.outcome)
        batch_rate.setdefault(r.batch, []).append(r.outcome == "win")
        # slot0/slot1 量的是“同一 pair 的下位/上位出生点”，不是两个玩家座位：
        # 引擎按 spawn-1 决定物理槽位，第一个队伍（playerTeam）永远是下位。
        per_slot["slot0" if r.candidate_spawn == r.pair[0] else "slot1"].append(r.outcome)
        per_pair.setdefault(f"{r.pair[0]}-{r.pair[1]}", []).append(r.outcome)
    rates = [sum(v) / len(v) for v in batch_rate.values() if v]
    return {
        "games": n, "wins": wins, "draws": draws,
        "losses": sum(1 for r in records if r.outcome == "loss"),
        "win_rate": (wins + 0.5 * draws) / n if n else 0.0,
        "wilson": [lo, hi],
        "per_map": {k: {"n": len(v), "wins": v.count("win"), "losses": v.count("loss"),
                        "draws": v.count("draw")} for k, v in per_map.items()},
        "per_slot": {k: {"n": len(v), "wins": v.count("win"), "losses": v.count("loss"),
                         "draws": v.count("draw"),
                         "win_rate": (v.count("win") + 0.5 * v.count("draw")) / len(v) if v else 0.0}
                     for k, v in per_slot.items()},
        "per_pair": {k: {"n": len(v), "wins": v.count("win"), "losses": v.count("loss"),
                         "win_rate": (v.count("win") + 0.5 * v.count("draw")) / len(v) if v else 0.0}
                     for k, v in per_pair.items()},
        "batch_rate_std": statistics.pstdev(rates) if len(rates) > 1 else 0.0,
        "mean_ticks": statistics.fmean(r.ticks for r in records) if records else 0.0,
        "mean_exchange": statistics.fmean(r.exchange for r in records) if records else 0.0,
        "failures": total - n,
    }
