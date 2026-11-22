"""参数层：把参数文档里的旋钮（浮点 / 整数 / 归一化权重组）编码成优化向量。

文档形状
--------
任何一个段都可以当成“旋钮组”加进来，只要每项是下面两种写法之一::

    "buildingScore": {
      "enabled": true,
      "extractorFirst": {"name": "采掘器首座", "type": "float",
                         "value": 0.98, "min": 0.60, "max": 0.99, "step": 0.01}
    }

或裸数字（此时视为固定值，不参与搜索）。``type`` 缺省为 ``float``，``step``
缺省为 ``1``（int）/ ``0.01``（float）；区间按 step 取整，编码值 = 实际值 / step。

可插拔
------
* 新增**一个通用旋钮段**：调 :func:`register_generic_section` 即可，无需改本文件。
* 需要特殊编码（例如非等距网格、对数轴）：写一个 ``build(doc, read) -> list[Knob]``
  并用 :func:`register_knob_section` 注册。
* 兵种权重永远是 softmax 组：解码得到的是**相对比例**，总和保持文档里的原始 TOTAL。
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .paths import THETA_BOUND
from .util import atomic_json

# =========================================================================== 旋钮


@dataclass(frozen=True)
class Knob:
    """一个数值维度：实际值 = 编码值 × step。"""

    path: tuple
    label: str
    kind: str = "float"          # "float" | "int"
    step: float = 1.0
    min: float = 0.0
    max: float = 0.0
    value: float = 0.0

    def grid(self) -> tuple[float, float, float]:
        """返回 (lo, hi, init)，单位是“格数”。"""
        lo = math.ceil(self.min / self.step)
        hi = math.floor(self.max / self.step)
        if hi < lo:                      # 区间比一个 step 还窄：退化成单点
            hi = lo
        init = min(max(self.value / self.step, lo), hi)
        return lo, hi, init

    def decode(self, x: float, lo: float, hi: float) -> float:
        # 编码值是“格数”，必须落在整数格上：先夹到 [lo,hi] 再四舍五入
        coded = round(float(np.clip(float(x), lo, hi)))
        value = coded * self.step
        if self.kind == "int":
            return int(round(value))
        return round(value, 6)

    def to_json(self) -> dict:
        return {"path": ".".join(self.path), "label": self.label, "kind": self.kind,
                "step": self.step, "min": self.min, "max": self.max, "value": self.value}


# ---- 旧接口：依然是同一套文档格式 -----------------------------------------

def _knob(node) -> dict:
    """参数项可能是 {"value":..} 也可能是裸数字。"""
    if isinstance(node, dict):
        return {"value": float(node.get("value", 0.0)),
                "min": float(node.get("min", 0.0)),
                "max": float(node.get("max", 10.0))}
    return {"value": float(node), "min": 0.0, "max": 10.0}


def _write(container: dict, name: str, value) -> None:
    node = container[name]
    if isinstance(node, dict):
        node["value"] = value
    else:
        container[name] = value


def _node(container: dict, key: str) -> dict:
    """取/建子节点，确保路径存在。"""
    child = container.get(key)
    if not isinstance(child, dict):
        child = {}
        container[key] = child
    return child


def _set_path(doc: dict, path: tuple, value) -> None:
    node = doc
    for key in path[:-1]:
        node = _node(node, key)
    leaf = node.get(path[-1])
    if isinstance(leaf, dict):      # 保留 name/min/max 之类的元数据
        leaf["value"] = value
    else:
        node[path[-1]] = value


# ---- 文档 → 旋钮 ------------------------------------------------------------

def _parse_knob(node, path: tuple, label: str, step=None) -> Knob | None:
    """把文档里的一个节点解析成 Knob；裸数字 = 固定维度（lo == hi）。"""
    if isinstance(node, dict):
        if "value" not in node:
            return None
        kind = str(node.get("type", "float")).lower()
        kind = "int" if kind in ("int", "integer", "i") else "float"
        default_step = 1.0 if kind == "int" else 0.01
        return Knob(
            path=path,
            label=str(node.get("name") or label),
            kind=kind,
            step=float(node.get("step", step if step is not None else default_step)),
            min=float(node.get("min", node["value"])),
            max=float(node.get("max", node["value"])),
            value=float(node["value"]),
        )
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        value = float(node)
        return Knob(path=path, label=label, kind="float",
                    step=float(step if step is not None else 1.0),
                    min=value, max=value, value=value)
    return None


# ---- 旋钮段注册表 -----------------------------------------------------------

KNOB_SECTIONS: list = []


def register_knob_section(build) -> None:
    """注册一个 ``build(doc, read) -> list[Knob]`` 段构建器（后注册的排在后面）。"""
    KNOB_SECTIONS.append(build)


def register_generic_section(section: str) -> None:
    """注册一个“标准旋钮组”段：``section`` 下的每项按 :class:`Knob` 规则解析。"""

    def build(doc: dict, read) -> list:
        group = doc.get(section)
        if not isinstance(group, dict):
            return []
        knobs = []
        for key, val in group.items():
            if key.startswith("_") or key in ("enabled", "preset"):
                continue
            knob = _parse_knob(val, (section, key), key)
            if knob is not None:
                knobs.append(knob)
        return knobs

    register_knob_section(build)


# ---- 内置段 ------------------------------------------------------------------

# 顺序即 x 的排列顺序：节拍三项 → 五个固定项 → 通用段（buildingScore / impossible）→ 权重
FIXED_DIMS = (
    (("building", "attemptIntervalFrames"), "建造尝试间隔", 5),   # 100-650 → 20-130
    (("upgrades", "intervalFrames"), "升级间隔", 5),             # 300-700 → 60-140
    (("units", "maxPerCycle"), "每轮生产上限", 1),               # 8-30
    (("upgrades", "bankCredits"), "升级预存(×100)", 100),        # 3000-5000 → 30-50
    (("upgrades", "maxPerCycle"), "每轮升级上限", 1),            # 1-4
)


def _cadence_section(doc: dict, read) -> list:
    cadence = (doc.get("definition") or {}).get("cadence") or {}
    out = []
    for name in ("economy", "tactics", "strategy"):
        if name in cadence:
            knob = _parse_knob(cadence[name], ("definition", "cadence", name), f"节拍·{name}", step=5)
            if knob is not None:
                out.append(knob)
    return out


def _fixed_section(doc: dict, read) -> list:
    out = []
    for path, label, step in FIXED_DIMS:
        node = read(path)
        if node is None:
            continue
        knob = _parse_knob(node, path, label, step=step)
        if knob is not None:
            out.append(knob)
    return out


register_knob_section(_cadence_section)
register_knob_section(_fixed_section)
register_generic_section("buildingScore")
register_generic_section("impossible")


# ---- 归一化参数组 -----------------------------------------------------------

# 权重下限：文档里 value<=0 的兵种也照样进搜索向量（用这个下限参与 log 编码），
# 避免 log(0) = -inf → 减均值后变 NaN；同时保证“曾经掉到 0”的维度不会被永久踢掉。
WEIGHT_FLOOR = 1e-2


@dataclass
class SoftmaxGroup:
    """一组“只关心相对比例”的正数参数（兵种权重就是这种）。

    编码：x 是 logits；解码：``softmax(logits) × total``，再把每项夹到自己的上限。
    ``total`` 缺省保持文档里的原始总和，所以“全等权”编码出来仍是原版分布。
    """

    name: str
    path: tuple
    members: list[tuple[str, float, float]]   # (id, 初值, 上限)
    total: float
    preserve_total: bool = True
    theta: float = THETA_BOUND

    @property
    def dim(self) -> int:
        return len(self.members)

    @property
    def names(self) -> list[str]:
        return [m[0] for m in self.members]

    def bounds(self) -> tuple[list[float], list[float]]:
        return [-self.theta] * self.dim, [self.theta] * self.dim

    def encode(self) -> list[float]:
        if not self.members:
            return []
        # value<=0 用 WEIGHT_FLOOR 兜底：log(0) 会得到 -inf，减均值后整组变 NaN
        logs = np.log([max(float(value), WEIGHT_FLOOR) for _, value, _ in self.members])
        return [float(v) for v in logs - logs.mean()]

    def decode(self, theta, doc: dict) -> None:
        if not self.members:
            return
        theta = np.clip(np.asarray(theta, dtype=float).ravel(), -self.theta, self.theta)
        p = np.exp(theta - theta.max())
        p /= p.sum()
        scale = self.total if self.preserve_total else 1.0
        node = doc
        for key in self.path:
            node = _node(node, key)
        for (name, _, upper), raw in zip(self.members, p * scale):
            value = round(min(max(float(raw), 0.0), upper), 2)
            # 不再写死 0：低于下限也留 WEIGHT_FLOOR，保证下一轮建向量时这一维还在
            _write(node, name, value if value >= WEIGHT_FLOOR else WEIGHT_FLOOR)

    @classmethod
    def from_doc(cls, doc: dict, path: tuple = ("units", "weights"),
                 frozen=(), preserve_total: bool = True, name: str = "weights"):
        node = doc
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            return None
        members = []
        for unit, raw in node.items():
            spec = _knob(raw)
            if unit.lower() in frozen:      # 只认调用方显式 --frozen，不再按当前值剔维
                continue
            members.append((unit, max(spec["value"], WEIGHT_FLOOR), spec["max"]))
        if not members:
            return None
        return cls(name=name, path=path, members=members,
                   total=float(sum(m[1] for m in members)),
                   preserve_total=preserve_total)


def register_softmax_group(name: str, path: tuple) -> None:
    """注册一个归一化参数组（默认已注册 ``units.weights``）。"""
    SOFTMAX_GROUPS.append((name, tuple(path)))


SOFTMAX_GROUPS: list = [("weights", ("units", "weights"))]


# =========================================================================== 编解码


class ParamCodec:
    """x 的前若干维是“格数”形式的数值旋钮，其余是兵种权重的 logits。"""

    def __init__(self, params_path: Path, frozen_units=(), preserve_total: bool = True):
        self.path = Path(params_path)
        self.doc = json.loads(self.path.read_text(encoding="utf-8"))
        self.preserve_total = preserve_total
        frozen = {str(u).strip().lower() for u in (frozen_units or ())}

        cadence = (self.doc.get("definition") or {}).get("cadence") or {}
        self.cadence = [n for n in ("economy", "tactics", "strategy") if n in cadence]
        if not self.cadence:
            raise SystemExit(f"{self.path} 里没有 definition.cadence")

        self.knobs: list[Knob] = []
        for build in KNOB_SECTIONS:
            self.knobs.extend(build(self.doc, self._read))
        self.dims = self.knobs          # 兼容旧名字

        self.lo: list[float] = []
        self.hi: list[float] = []
        self.init: list[float] = []
        for knob in self.knobs:
            lo, hi, init = knob.grid()
            self.lo.append(lo)
            self.hi.append(hi)
            self.init.append(init)

        self.groups: list[SoftmaxGroup] = []
        for name, path in SOFTMAX_GROUPS:
            group = SoftmaxGroup.from_doc(self.doc, path, frozen=frozen,
                                          preserve_total=self.preserve_total, name=name)
            if group is not None:
                self.groups.append(group)

        # 兼容旧接口：units / spec / active / total 都映射到第一个（通常也是唯一的）权重组
        weights = ((self.doc.get("units") or {}).get("weights")) or {}
        self.units = list(weights.keys())
        self.spec = {u: _knob(weights[u]) for u in self.units}
        group = self.groups[0] if self.groups else None
        self.active = group.names if group else []
        self.total = group.total if group else 0.0

    def _read(self, path: tuple):
        node = self.doc
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return node

    @property
    def dim(self) -> int:
        return len(self.knobs) + sum(g.dim for g in self.groups)

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        lo = list(self.lo)
        hi = list(self.hi)
        for group in self.groups:
            g_lo, g_hi = group.bounds()
            lo.extend(g_lo)
            hi.extend(g_hi)
        return np.array(lo, dtype=float), np.array(hi, dtype=float)

    def encode(self) -> np.ndarray:
        x = list(self.init)
        for group in self.groups:
            x.extend(group.encode())
        lo, hi = self.bounds()
        return np.clip(np.array(x, dtype=float), lo, hi)

    def decode(self, x) -> dict:
        """返回完整参数文档；数值维度按 step 取整，权重走 softmax。"""
        x = np.asarray(x, dtype=float).ravel()
        if x.size != self.dim:
            raise ValueError(f"x 维度应为 {self.dim}，实际 {x.size}")
        doc = copy.deepcopy(self.doc)
        for i, knob in enumerate(self.knobs):
            _set_path(doc, knob.path, knob.decode(x[i], self.lo[i], self.hi[i]))

        offset = len(self.knobs)
        for group in self.groups:
            group.decode(x[offset:offset + group.dim], doc)
            offset += group.dim
        return doc

    def save(self, x, path: Path) -> dict:
        doc = self.decode(x)
        atomic_json(Path(path), doc)
        return doc

    def rows(self) -> list:
        """给 report/CSV 用的旋钮快照（每行一个旋钮）。"""
        return [knob.to_json() for knob in self.knobs]

    def describe(self) -> str:
        groups = "，".join(f"{g.name} {g.dim}" for g in self.groups) or "无组"
        return (f"d={self.dim}（旋钮 {len(self.knobs)} + {groups}），"
                f"冻结 {len(self.units) - len(self.active)}，TOTAL={self.total:.2f}")
