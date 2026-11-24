"""把历史 57 维 v2 检查点迁到当前的 56 维空间。

旧布局里 `impossible.defensiveScoreBase`（原版 Impossible 第 6 条特权通道）和
`building.attemptIntervalFrames` 喂的是同一个建造计时器，前者在旧世界生效、后者是死维。
现在顺序反了（文档写了 `attemptIntervalFrames` 就优先），所以迁移必须**搬值**：
把旧世界真正生效的基数写进 `attemptIntervalFrames`，再删掉 `defensiveScoreBase`。

迁移后的检查点保留：均值（= 训练出来的参数值，解码后与旧检查点逐项一致）、sigma、代数、RNG 状态。
不保留：协方差矩阵（pycma 没有换维接口，硬切会破坏内部采样器）。也就是说行为不变、探索重新铺开。
"""
from __future__ import annotations

import copy
import pickle
import random
from pathlib import Path

import numpy as np

from .legacy_v2 import legacy_layout
from .params import ParamCodec
from .scenarios import SCENARIOS
from .util import atomic_json, atomic_pickle

SCORE_KEY = "defensiveScoreBase"
ORIGINAL_TIMER = 270.0   # 原版非 Impossible 的防守分基数
GRID = 5.0               # building.attemptIntervalFrames 的搜索步长


def _raw(node):
    return node.get("value") if isinstance(node, dict) else node


def _takeover(doc: dict) -> bool:
    table = doc.get("impossible") or {}
    return bool(table.get("takeover", table.get("enabled", False)))


def migrate_document(doc57: dict) -> tuple[dict, float, float]:
    """57 维文档 -> 56 维文档；返回 (新文档, 旧生效值, 新值)。

    旧世界里两个字段谁生效取决于 `overrides.buildingProduction`：
    * 接管建造：`building.attemptIntervalFrames` 是自定义建造节拍（生效），`defensiveScoreBase`
      只影响原版分支的重算频率（该分支被接管跳过）。
    * 不接管：`attemptIntervalFrames` 是死维，`defensiveScoreBase`（表开着时）才是计时值。
    """
    table = doc57.get("impossible") or {}
    base = _raw(table.get(SCORE_KEY))
    taken_over = bool(_raw((doc57.get("overrides") or {}).get("buildingProduction")))
    if taken_over:
        # 自定义建造节拍本来就是活的，原样保留；第 6 条只留出处。
        keep = _raw((doc57.get("building") or {}).get("attemptIntervalFrames"))
        effective = float(keep) if keep is not None else float(base or ORIGINAL_TIMER)
        snapped = float(min(max(round(effective / GRID) * GRID, 120.0), 650.0))
    else:
        # 旧世界生效值：表开着才是表里的基数，否则是原版 270。
        effective = float(base) if base is not None and _takeover(doc57) else ORIGINAL_TIMER
        snapped = float(min(max(round(effective / GRID) * GRID, 120.0), 650.0))

    doc56 = copy.deepcopy(doc57)
    doc56.get("impossible", {}).pop(SCORE_KEY, None)
    building = doc56.setdefault("building", {})
    node = building.get("attemptIntervalFrames")
    if taken_over:
        # 本来就在用的值，一格都不动。
        snapped = effective
    else:
        value = int(snapped) if float(snapped).is_integer() else snapped
        if isinstance(node, dict):
            node["value"] = value
        else:
            building["attemptIntervalFrames"] = {"value": value, "min": 120, "max": 650}
    return doc56, effective, snapped


def load_legacy_state(checkpoint: Path) -> dict:
    return pickle.loads(Path(checkpoint).read_bytes())


def convert(checkpoint: Path, template: Path = None, legacy_params: Path = None,
            frozen_units=(), scenario: str = "hardupv2") -> tuple[dict, ParamCodec, dict]:
    """返回 (新检查点状态, 56 维 codec, 迁移摘要)。"""
    import cma

    template = Path(template or SCENARIOS[scenario][0])
    state = load_legacy_state(checkpoint)
    es = state["es"]
    if len(es.mean) != 57:
        raise SystemExit(f"只处理 57 维检查点，这个文件是 {len(es.mean)} 维：{checkpoint}")

    current = ParamCodec(template, frozen_units=frozen_units)
    if legacy_params is not None:
        doc57 = atomic_json_read(legacy_params)
        codec57 = ParamCodec(template, frozen_units=frozen_units, document=doc57)
        if codec57.dim != 57:
            raise SystemExit(f"{legacy_params} 解析成 {codec57.dim} 维，不是 57 维")
    else:
        codec57 = legacy_layout(current, Path(checkpoint), state, frozen_units)

    mean57 = np.asarray(es.mean, dtype=float)
    doc57 = codec57.decode(mean57)
    doc56, effective, snapped = migrate_document(doc57)
    codec56 = ParamCodec(template, frozen_units=frozen_units, document=doc56)
    if codec56.dim != current.dim:
        raise SystemExit(f"迁移后是 {codec56.dim} 维，与模板 {current.dim} 维不一致")

    lo, hi = codec56.bounds()
    # 只搬与维度无关的选项：minstd / CMA_stds 之类是 57 维数组，搬过去会直接报维度错。
    opts = {key: es.opts[key] for key in
            ("popsize", "seed", "tolfun", "tolfunhist", "tolx", "tolflatfitness") if key in es.opts}
    opts.update({
        "bounds": [list(lo), list(hi)],
        "verbose": -9,
        # 旧 run 的迭代预算按“已用 + 原预算”接上，避免第一代就撞 maxiter。
        "maxiter": int(state.get("gen", 0)) + int(es.opts.get("maxiter", 100)),
    })
    sigma = float(es.sigma if es.sigma > 0 else es.sigma0)
    new_es = cma.CMAEvolutionStrategy(list(codec56.encode()), max(sigma, 1e-6), opts)

    summary = {
        "checkpoint": str(checkpoint), "gen": int(state.get("gen", 0)),
        "dim": f"{len(mean57)} -> {codec56.dim}",
        SCORE_KEY: effective, "attemptIntervalFrames": snapped,
        "takeover": _takeover(doc57), "sigma": sigma,
        "drift": compare(codec57, mean57, codec56, new_es.mean),
    }
    if summary["drift"]:
        raise SystemExit("迁移后参数值漂移：" + ", ".join(summary["drift"][:5]))

    new_state = {
        "es": new_es, "gen": int(state.get("gen", 0)),
        "rng": state.get("rng", random.Random(0).getstate()),
        "total_games": int(state.get("total_games", 0)),
        "config": state.get("config"),
        "migrated_from": str(checkpoint),
    }
    return new_state, codec56, summary


def compare(codec57: ParamCodec, mean57, codec56: ParamCodec, mean56) -> list:
    """逐项比较两个解码文档，返回不一致的路径（attemptIntervalFrames 与权重除外）。"""
    a = codec57.decode(mean57)
    b = codec56.decode(mean56)
    problems = []

    def at(doc, path):
        node = doc
        for key in path:
            node = node[key]
        return node.get("value") if isinstance(node, dict) else node

    for knob in codec56.knobs:
        if knob.path[-1] == "attemptIntervalFrames":
            continue
        left = at(a, knob.path)
        right = at(b, knob.path)
        if left is None:
            problems.append(f"{'.'.join(knob.path)} 在旧文档里不存在")
        elif abs(float(left) - float(right)) > knob.step / 2 + 1e-6:
            problems.append(f"{'.'.join(knob.path)}: {left} -> {right}")

    for unit, node in (b.get("units", {}).get("weights") or {}).items():
        old = (a.get("units", {}).get("weights") or {}).get(unit)
        if not isinstance(node, dict) or not isinstance(old, dict):
            continue
        # 权重只在 decode 时按总和归一化，重建 56 维空间会把个别兵种挪 1–2%（4.19→4.22），
        # 相对优先级不变，所以这里放到 5%；其余旋钮仍按 step/2 严格比。
        if abs(float(old["value"]) - float(node["value"])) > 0.05:
            problems.append(f"units.weights.{unit}: {old['value']} -> {node['value']}")
    return problems


def atomic_json_read(path: Path) -> dict:
    import json
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(new_state: dict, codec56: ParamCodec, out: Path, params_out: Path = None) -> Path:
    out = Path(out)
    atomic_pickle(out, new_state)
    target = Path(params_out) if params_out else out.with_suffix(".json")
    atomic_json(target, codec56.doc)
    return target
