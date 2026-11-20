"""CMA-ES 黑盒优化：params3.json（节拍 + 兵种权重）对战原版 AI Hard。

代码结构（经典黑盒优化接口）：
    ParamCodec      解空间编解码（x <-> params 文档）
    Objective       问题接口：dim / bounds / evaluate(x) -> 结果字典（fitness 最小化）
    Optimizer       优化器接口：ask / tell / mean / sigma / stop
    CmaEs           pycma 适配层
    ParamsObjective 真实问题（跑对局）；MockParamsObjective 是 --dry-run 的假问题
    Runner          对局执行（worker 池 + 重试 + 补抽）
    Trainer         只负责“循环 + 记录 + 检查点”，不碰对局细节

子命令：train（默认）/ test / report / selftest。依赖 numpy、cma、标准库。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import csv
import dataclasses
import hashlib
import json
import math
import os
import pickle
import queue
import random
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("RWX_REPO", str(HERE.parents[2])))
RUN_ENV = REPO / "evaluate" / "RL" / "run-env.ps1"
POOL = HERE / "completition.json"
PARAMS = HERE / "params3.json"
WORK = REPO / "agent-tmp" / "rl-pool"
RUNS = HERE / "runs"

SMALL_WEIGHT = 0.05     # 小于它置 0
THETA_BOUND = 3.0       # θ 硬边界
TICKS_PER_SECOND = 62.5


# =========================================================================== 参数编解码

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


class ParamCodec:
    """x[0:3] = ln(cadence)，x[3:] = θ（权重 logits，已去均值）。"""

    def __init__(self, params_path: Path, frozen_units=(), preserve_total: bool = True):
        self.path = Path(params_path)
        self.doc = json.loads(self.path.read_text(encoding="utf-8"))
        self.preserve_total = preserve_total
        frozen = {str(u).strip().lower() for u in (frozen_units or ())}

        cadence = (self.doc.get("definition") or {}).get("cadence") or {}
        self.cadence = [n for n in ("economy", "tactics", "strategy") if n in cadence]
        if not self.cadence:
            raise SystemExit(f"{self.path} 里没有 definition.cadence")

        weights = ((self.doc.get("units") or {}).get("weights")) or {}
        self.units = list(weights.keys())
        self.spec = {u: _knob(weights[u]) for u in self.units}
        self.active = [u for u in self.units
                       if u.lower() not in frozen and self.spec[u]["value"] > 0]
        self.total = float(sum(self.spec[u]["value"] for u in self.active))

    # -- 边界与初值 -----------------------------------------------------
    def _cad(self, name: str) -> dict:
        return _knob(self.doc["definition"]["cadence"][name])

    @property
    def dim(self) -> int:
        return len(self.cadence) + len(self.active)

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        lo = [math.log(max(1e-6, self._cad(n)["min"])) for n in self.cadence]
        hi = [math.log(max(1e-6, self._cad(n)["max"])) for n in self.cadence]
        n = len(self.active)
        return (np.array(lo + [-THETA_BOUND] * n), np.array(hi + [THETA_BOUND] * n))

    def encode(self) -> np.ndarray:
        x = [math.log(max(1e-6, self._cad(n)["value"])) for n in self.cadence]
        if self.active:
            logs = np.log([self.spec[u]["value"] for u in self.active])
            x.extend(float(v) for v in logs - logs.mean())
        lo, hi = self.bounds()
        return np.clip(np.array(x, dtype=float), lo, hi)

    def decode(self, x) -> dict:
        """返回完整参数文档（只改 value）；评估与导出都用它。"""
        x = np.asarray(x, dtype=float).ravel()
        if x.size != self.dim:
            raise ValueError(f"x 维度应为 {self.dim}，实际 {x.size}")
        d = copy.deepcopy(self.doc)

        for i, name in enumerate(self.cadence):
            spec = self._cad(name)
            value = int(round(math.exp(float(x[i]))))
            _write(d["definition"]["cadence"], name,
                   int(min(max(value, spec["min"]), spec["max"])))

        theta = np.clip(x[len(self.cadence):], -THETA_BOUND, THETA_BOUND)
        if theta.size:
            p = np.exp(theta - theta.max())
            p /= p.sum()
            scale = self.total if self.preserve_total else 1.0
            for name, raw in zip(self.active, p * scale):
                spec = self.spec[name]
                v = round(min(max(float(raw), spec["min"]), spec["max"]), 2)
                _write(d["units"]["weights"], name, 0.0 if v < SMALL_WEIGHT else v)
        return d

    def save(self, x, path: Path) -> dict:
        doc = self.decode(x)
        atomic_json(Path(path), doc)
        return doc

    def describe(self) -> str:
        return (f"d={self.dim}（节拍 {len(self.cadence)} + 权重 {len(self.active)}），"
                f"冻结 {len(self.units) - len(self.active)}，TOTAL={self.total:.2f}")


# =========================================================================== 通用工具

def atomic_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def atomic_pickle(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as fh:
        pickle.dump(obj, fh)
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_hash() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO),
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def pearson(xs, ys) -> float:
    """皮尔逊相关；候选很少时只当方向指示用。"""
    if len(xs) < 3:
        return 0.0
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if sx == 0 or sy == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def wilson_ci(wins: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = wins / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def kill_tree(pid: int) -> None:
    """按进程树强杀：pwsh 起的 java 子进程一起收掉。"""
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, timeout=20)
    except Exception:
        pass


# =========================================================================== 对局规格

@dataclass(frozen=True)
class Matchup:
    name: str
    map: str
    pair: tuple[int, int]


@dataclass(frozen=True)
class MatchSpec:
    """一局：图 + 双方出生点 + 槽位 + 种子 + 批次。

    槽位要轮换：AI 难度收入倍率只作用于 AI 队，候选固定坐槽 0 会一直吃亏。
    """

    matchup: Matchup
    candidate_spawn: int
    seed: int
    batch: int
    candidate_slot: int = 0

    @property
    def opponent_spawn(self) -> int:
        a, b = self.matchup.pair
        return b if self.candidate_spawn == a else a


def load_pool(path: Path) -> list[Matchup]:
    doc = read_json(Path(path)) or {}
    entries: list[Matchup] = []
    for item in doc.get("maps") or []:
        name = str(item.get("name") or Path(str(item["map"])).stem)
        for pair in item.get("pairs") or [[1, 2]]:
            pair = tuple(int(x) for x in pair)
            if len(pair) != 2 or pair[0] == pair[1]:
                raise SystemExit(f"{name}: pairs 必须是两个不同的出生点编号")
            entries.append(Matchup(name, str(item["map"]), pair))
    if not entries:
        raise SystemExit(f"配置池是空的：{path}")
    return entries


def sample(entries: list[Matchup], count: int, rng: random.Random) -> list[Matchup]:
    """无放回抽样；池子不够大就整池打乱后重复。"""
    out: list[Matchup] = []
    while len(out) < count:
        out.extend(rng.sample(entries, len(entries)))
    return out[:count]


def make_specs(entries, rng, n_games: int, batch_size: int) -> list[MatchSpec]:
    """抽 n_games 局。

    先按“地图”等概率抽取（同一张图的多个 pair 只算一次机会），选中地图后再在它的
    配置里均匀挑一个；否则配置多的大图会被不成比例地抽到。
    出口固定：出生点与槽位都奇偶交替（各一半），按 batch_size 分批。
    """
    by_map: dict[str, list[Matchup]] = {}
    for entry in entries:
        by_map.setdefault(entry.name, []).append(entry)
    names = list(by_map)
    picks = [rng.choice(by_map[rng.choice(names)]) for _ in range(n_games)]
    return [MatchSpec(m, m.pair[i % 2], rng.randrange(1, 2_000_000_000),
                      i // max(1, batch_size), candidate_slot=i % 2)
            for i, m in enumerate(picks)]


# =========================================================================== 单局结果与打分

@dataclass
class GameRecord:
    map: str
    pair: tuple[int, int]
    candidate_spawn: int
    seed: int
    batch: int
    outcome: str = "error"      # win / loss / draw / error
    ticks: int = 0
    max_ticks: int = 0
    game_ms: float = 0.0
    win: float = 0.0
    prod_self: int = 0
    prod_enemy: int = 0
    def_self: int = 0
    def_enemy: int = 0
    build_prod: float = 0.0
    build_def: float = 0.0
    army_self: float = 0.0
    army_enemy: float = 0.0
    army: float = 0.0
    income_self: float = 0.0
    income_enemy: float = 0.0
    econ: float = 0.0
    econ_ok: bool = False
    kill_value: float = 0.0      # 全部单位（含建筑，建筑已乘系数）
    loss_value: float = 0.0
    kill_units: float = 0.0      # 只含军事单位，供战损比使用
    loss_units: float = 0.0
    exchange_r: float = 0.0
    exchange: float = 0.0      # 仅诊断用，不进奖励
    board: float = 0.0
    duration_s: float = 0.0
    time_score: float = 0.0
    reward: float = 0.0
    samples_ok: bool = False
    samples_loss_ok: bool = False
    telemetry_ok: bool = False
    unknown_cost: int = 0
    wall_s: float = 0.0
    error: str = ""

    def to_json(self) -> dict:
        doc = dataclasses.asdict(self)
        doc["pair"] = list(self.pair)
        return doc


_PROD_KEYS = ("factory", "commandcenter")
_DEF_KEYS = ("turret", "defence", "antinuke", "launcher", "repairbay")
_BLD_KEYS = ("extractor", "fabricat", "center", "lab")


def unit_kind(name: str) -> str:
    """把单位类型名归类：prod / def / building / builder / unit。"""
    n = name.lower()
    if any(k in n for k in _PROD_KEYS):
        return "prod"
    if any(k in n for k in _DEF_KEYS):
        return "def"
    if "builder" in n:
        return "builder"
    if any(k in n for k in _BLD_KEYS):
        return "building"
    return "unit"


def gap(mine: float, theirs: float) -> float:
    """差异比例 (我 - 敌) / (我 + 敌)，[-1, 1]，双方都为 0 时取 0。"""
    total = mine + theirs
    return (mine - theirs) / total if total > 0 else 0.0


def enemy_spawn_of(rec: GameRecord) -> int:
    a, b = rec.pair
    return b if rec.candidate_spawn == a else a


def parse_telemetry(game_dir: Path, rec: GameRecord, cfg: "TrainConfig", costs: dict) -> None:
    """从 telemetry 取死亡事件（K/L）并采集单位造价。

    telemetry 的 side 相对它跟踪的队伍（meta.team），候选在另一侧时敌我要反过来。
    """
    files = sorted(game_dir.glob("events-live/*/telemetry.jsonl"))
    if not files:
        return
    rec.telemetry_ok = True
    end_ms = rec.game_ms or rec.ticks / TICKS_PER_SECOND * 1000.0
    death_end_ms = max(0.0, end_ms - cfg.death_end_margin_ms)
    my_team = rec.candidate_spawn - 1

    for path in files:
        self_is_mine = True
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if '"meta"' in line and '"team"' in line:
                    row = read_json_line(line)
                    if row.get("kind") == "meta" and row.get("team") is not None:
                        self_is_mine = int(row["team"]) == my_team
                    continue
                if '"death"' not in line and '"unit"' not in line:
                    continue
                row = read_json_line(line)
                kind = row.get("kind")
                if kind == "unit":
                    for act in (row.get("unit") or {}).get("actions", {}).values():
                        if act.get("kind") == "produce" and act.get("type"):
                            costs.setdefault(str(act["type"]).lower(), float(act.get("cost") or 0.0))
                    continue
                if kind != "death":
                    continue
                unit, killer = row.get("unit") or {}, row.get("killer") or {}
                # 排除：无击杀者（自毁/撤销建造）、同阵营击杀、局终清场
                if not unit.get("type") or not killer or killer.get("side") == unit.get("side"):
                    continue
                if float(row.get("timeMs") or 0.0) > death_end_ms:
                    continue
                cost = costs.get(str(unit["type"]).lower())
                if cost is None:
                    cost, rec.unknown_cost = cfg.default_unit_cost, rec.unknown_cost + 1
                if unit.get("building"):
                    cost *= cfg.building_value_weight
                elif unit.get("builder"):
                    cost *= cfg.builder_value_weight
                mine = (unit.get("side") == "self") == self_is_mine
                military = unit_kind(str(unit.get("type") or "")) == "unit"
                if mine:
                    rec.loss_value += cost
                    rec.loss_units += cost if military else 0.0
                else:
                    rec.kill_value += cost
                    rec.kill_units += cost if military else 0.0


def read_json_line(line: str) -> dict:
    try:
        return json.loads(line)
    except Exception:
        return {}


def parse_samples(game_dir: Path, rec: GameRecord, cfg: "TrainConfig", costs: dict) -> None:
    """取“终局前一段”（默认 75% 时长）的快照：建筑、兵力、收入，以及累计战损。

    不用最后一帧：输掉的局末帧必然被打光，差距恒 ≈ -1，方差只反映“输得多惨”。
    """
    path = game_dir / "samples.jsonl"
    if not path.exists():
        return
    rows: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = read_json_line(line)
                if row:
                    rows.append(row)
    if not rows:
        return

    final_tick = rows[-1].get("tick") or 0
    target = float(final_tick) * cfg.snapshot_fraction
    snapshot = min(rows, key=lambda r: abs(float(r.get("tick") or 0) - target))
    mine_id, their_id = str(rec.candidate_spawn - 1), str(enemy_spawn_of(rec) - 1)

    def side(row: dict, team_id: str):
        team = (row.get("teams") or {}).get(team_id) or {}
        prod = dfn = 0
        army = 0.0
        for name, count in (team.get("types") or {}).items():
            kind = unit_kind(name)
            if kind == "prod":
                prod += count
            elif kind == "def":
                dfn += count
            elif kind == "unit":
                army += count * (costs.get(name.lower()) or cfg.default_unit_cost)
        income = team.get("incomePerSecond")
        return prod, dfn, army, (float(income) if isinstance(income, (int, float)) else None)

    rec.prod_self, rec.def_self, rec.army_self, mine = side(snapshot, mine_id)
    rec.prod_enemy, rec.def_enemy, rec.army_enemy, theirs = side(snapshot, their_id)
    rec.samples_ok = True
    if mine is not None and theirs is not None:
        rec.income_self, rec.income_enemy, rec.econ_ok = mine, theirs, True

    # 累计战损：相邻采样之间某类型数量下降就是损失
    if not rec.telemetry_ok:
        prev = None
        for row in rows:
            cur = row.get("teams") or {}
            if prev is not None:
                for team_id, is_mine in ((mine_id, True), (their_id, False)):
                    before = ((prev.get(team_id) or {}).get("types") or {})
                    after = ((cur.get(team_id) or {}).get("types") or {})
                    for name, count in before.items():
                        drop = count - int(after.get(name, 0))
                        if drop <= 0:
                            continue
                        cost = costs.get(name.lower()) or cfg.default_unit_cost
                        military = unit_kind(name) == "unit"
                        if is_mine:
                            rec.loss_value += drop * cost
                            rec.loss_units += drop * cost if military else 0.0
                        else:
                            rec.kill_value += drop * cost
                            rec.kill_units += drop * cost if military else 0.0
            prev = cur
        rec.samples_loss_ok = rec.kill_value + rec.loss_value > 0


def score(rec: GameRecord, cfg: "TrainConfig") -> None:
    """单局奖励：胜负 + 建筑差距 + 兵力差距 + 战损比 + 用时 + 收入差。"""
    win = {"win": 1.0, "draw": 0.5, "loss": 0.0}.get(rec.outcome)
    if win is None:
        rec.reward = float("-inf")
        return
    rec.win = win

    if rec.samples_ok:
        rec.build_prod = gap(rec.prod_self, rec.prod_enemy)
        rec.build_def = gap(rec.def_self, rec.def_enemy)
        rec.army = gap(rec.army_self, rec.army_enemy)
    if rec.econ_ok:
        rec.econ = gap(rec.income_self, rec.income_enemy)
    if rec.telemetry_ok or rec.samples_loss_ok:
        # 只算军事单位：建筑损失是“被打崩”的结果，会把战损比带偏
        k, l = rec.kill_units, rec.loss_units
        rec.exchange = k / (k + l) if k + l > 0 else 0.5
        rec.exchange_r = min(999.0, k / max(1e-6, l))

    limit_s = max(1e-6, rec.max_ticks / TICKS_PER_SECOND)
    rec.duration_s = rec.game_ms / 1000.0 if rec.game_ms > 0 else rec.ticks / TICKS_PER_SECOND
    ratio = min(1.0, rec.duration_s / limit_s)
    rec.time_score = (1.0 - ratio) if rec.outcome == "win" else (ratio if rec.outcome == "loss" else 0.0)

    # 暴力口径：只留胜负与时长，局面类塑形项全部不计分（仍记录，供分析）
    rec.board = 0.0
    rec.reward = cfg.w_win * win + cfg.w_time * rec.time_score


# =========================================================================== Runner：跑对局

class Worker:
    """一个常驻槽位：私有参数文件 + 私有对局目录（JVM 仍是一局一启）。"""

    def __init__(self, index: int, root: Path):
        self.index = index
        self.dir = root / f"w{index}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.params_path = self.dir / "ai-params.json"
        self._hash: str | None = None
        self.restarts = 0
        self.games = 0

    def prepare(self, doc: dict) -> Path:
        payload = json.dumps(doc, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if digest != self._hash:
            atomic_json(self.params_path, doc)
            self._hash = digest
        return self.params_path


class Runner:
    """对局执行器：worker 池 + 单局重试 + 备用规格补抽。"""

    def __init__(self, cfg: "TrainConfig", run_dir: Path):
        self.cfg = cfg
        self.workers = [Worker(i, Path(run_dir) / "workers") for i in range(cfg.n_workers)]
        self._free: queue.Queue[Worker] = queue.Queue()
        for worker in self.workers:
            self._free.put(worker)
        self.costs: dict = {}
        if cfg.cost_table and Path(cfg.cost_table).exists():
            self.costs.update({str(k).lower(): float(v) for k, v in (read_json(cfg.cost_table) or {}).items()})

    @property
    def restarts(self) -> int:
        return sum(w.restarts for w in self.workers)

    def _map(self, fn, items: list) -> list:
        results: list = [None] * len(items)

        def task(i: int):
            worker = self._free.get()
            try:
                results[i] = fn(items[i], worker)
            finally:
                self._free.put(worker)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.cfg.n_workers) as pool:
            list(pool.map(task, range(len(items))))
        return results

    def game(self, spec: MatchSpec, params_doc: dict, worker: Worker) -> GameRecord:
        path = worker.prepare(params_doc)
        rec = self._run(spec, path, worker)
        if rec.error:                     # 失败重试 1 次
            rec = self._run(spec, path, worker)
            worker.restarts += 1 if rec.error else 0
        else:
            worker.games += 1
        return rec

    def run_jobs(self, jobs: list) -> list[GameRecord]:
        """一次提交多份 (params_doc, spec)，把 worker 池用满；失败重试 1 次。"""
        def one(job, worker):
            doc, spec = job
            rec = self.game(spec, doc, worker)
            return rec
        return self._map(one, jobs)

    def games(self, params_doc: dict, specs: list[MatchSpec],
              spare: list[MatchSpec] | None = None) -> list[GameRecord]:
        """跑一批；仍失败则用备用规格补抽（最多两轮）。"""
        records = [r for r in self._map(lambda s, w: self.game(s, params_doc, w), specs)
                   if not r.error]
        backup = list(spare or [])
        for _ in range(2):
            missing = len(specs) - len(records)
            if missing <= 0 or not backup:
                break
            take, backup = backup[:missing], backup[missing:]
            records.extend(r for r in self._map(lambda s, w: self.game(s, params_doc, w), take)
                           if not r.error)
        return records

    # -- 启动命令：Windows 走 run-env.ps1，Linux 直接起 java -------------
    @staticmethod
    def _command(env, slots, spec, params_path, game_dir, spec_path):
        if os.name == "nt":
            return ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(RUN_ENV),
                    "-Env", str(spec_path), "-Out", str(game_dir), "-Quiet"]
        repo = Path(os.environ.get("RWX_REPO", str(REPO)))
        java = os.environ.get("RWX_JAVA", "java")
        lib = os.environ.get("RWX_LIB", str(repo / "desktop" / "build" / "headless" / "lib"))
        rollout = {
            "schema": "rwx-rollout-v1", "out": str(game_dir),
            "map": str(repo / spec.matchup.map),
            "teams": [{"slot": s["slot"], "spawn": s["spawn"], "ai": s["ai"], "name": s["name"]}
                      for s in slots],
            "room": {"incomeMultiplier": env["room"]["incomeMultiplier"], "seed": spec.seed},
            "limits": env["limits"], "sampling": env["sampling"],
            "record": False, "winCondition": "commandCenter",
            "telemetry": bool(env.get("telemetry")),
            "aiConfig": str(params_path),
        }
        rollout_path = game_dir / "spec.json"
        rollout_path.write_text(json.dumps(rollout, ensure_ascii=False), encoding="utf-8")
        return [java, "-Xms256m", "-Xmx1536m", "-Dfile.encoding=UTF-8",
                "-Dorg.lwjgl.opengl.contextAPI=native",
                "--enable-native-access=ALL-UNNAMED",
                "--sun-misc-unsafe-memory-access=allow",
                f"-Drwx.repoDir={repo}", f"-Drwx.assetsDir={repo / 'assets'}",
                "-cp", str(Path(lib) / "*"), "io.github.rwx.DesktopMain", "--no-steam",
                f"--rollout-config={rollout_path}", f"--data-dir={game_dir}"]

    # -- 单局：调用 run-env、解析 result / samples --------------------
    def _run(self, spec: MatchSpec, params_path: Path, worker: Worker) -> GameRecord:
        cfg = self.cfg
        rec = GameRecord(map=spec.matchup.name, pair=spec.matchup.pair,
                         candidate_spawn=spec.candidate_spawn, seed=spec.seed,
                         batch=spec.batch, max_ticks=cfg.max_ticks)
        m = spec.matchup
        slug = re.sub(r"[^0-9A-Za-z]+", "-", m.name).strip("-").lower()[:24] or "map"
        game_dir = (Path(cfg.out_dir) / cfg.run_name / "games" /
                    f"w{worker.index}-{slug}-{m.pair[0]}-{m.pair[1]}-s{spec.candidate_spawn}-{spec.seed % 100000}")
        game_dir.mkdir(parents=True, exist_ok=True)

        mine = {"ai": cfg.candidate_id, "spawn": spec.candidate_spawn,
                "name": "candidate", "aiConfig": str(params_path)}
        theirs = {"ai": cfg.opponent_id, "spawn": spec.opponent_spawn, "name": "opponent"}
        slots = ([dict(slot=0, **mine), dict(slot=1, **theirs)] if spec.candidate_slot == 0
                 else [dict(slot=0, **theirs), dict(slot=1, **mine)])
        env = {
            "schema": "rwx-rl-env-v1", "name": game_dir.name, "map": m.map,
            "out": str(game_dir), "record": False, "telemetry": cfg.telemetry,
            "winCondition": "commandCenter", "seed": spec.seed,
            "room": {"incomeMultiplier": cfg.income},
            "sampling": {"everyTicks": cfg.sample_every_ticks, "includeUnitTypes": True},
            "slots": slots,
            "limits": {"maxTicks": cfg.max_ticks, "maxWallSeconds": int(cfg.match_timeout)},
        }
        spec_path = game_dir / "env.json"
        spec_path.write_text(json.dumps(env, ensure_ascii=False, indent=1), encoding="utf-8")

        started = time.time()
        command = self._command(env, slots, spec, params_path, game_dir, spec_path)
        proc = subprocess.Popen(
            command, cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace")
        try:
            out, err = proc.communicate(timeout=cfg.match_timeout + 120)
        except subprocess.TimeoutExpired:
            kill_tree(proc.pid)
            worker.restarts += 1
            rec.error = "timeout"
            return rec
        rec.wall_s = time.time() - started

        payload = game_dir / "result.json"
        if proc.returncode != 0 or not payload.exists():
            tail = ((out or "") + (err or "")).strip().splitlines()
            rec.error = (tail[-1] if tail else f"rc={proc.returncode}")[:160]
            worker.restarts += 1
            return rec

        doc = read_json(payload) or {}
        rec.ticks = int(doc.get("ticks") or 0)
        rec.game_ms = float(doc.get("gameMs") or 0.0)
        # 胜负只看 result.outcome：它从“本地队”（teamId 0）视角写 victory/defeat；
        # teams[].defeated 不能用，胜方会被标成 isTeamVictory=true。
        wire = str(doc.get("outcome") or "")
        if wire in ("victory", "defeat"):
            local_won = wire == "victory"
            mine_is_local = spec.candidate_spawn - 1 == 0
            rec.outcome = "win" if (local_won == mine_is_local) else "loss"
        else:
            rec.outcome = "draw"

        parse_telemetry(game_dir, rec, cfg, self.costs)
        parse_samples(game_dir, rec, cfg, self.costs)
        score(rec, cfg)
        shutil.rmtree(game_dir, ignore_errors=True)
        return rec


def aggregate(records: list[GameRecord]) -> dict:
    """每批单独求均值，再对批次求平均；batch_std 作为噪声估计。"""
    keys = ("win", "board", "build_prod", "build_def", "army", "econ", "time_score")
    if not records:
        return {"reward": 0.0, "batch_std": 0.0, "valid": 0, **{k: 0.0 for k in keys}}
    batches: dict[int, list[GameRecord]] = {}
    for r in records:
        batches.setdefault(r.batch, []).append(r)
    means = [statistics.fmean(x.reward for x in rows) for rows in batches.values()]
    out = {"reward": statistics.fmean(means),
           "batch_std": statistics.pstdev(means) if len(means) > 1 else 0.0,
           "valid": len(records)}
    for key in keys:
        out[key] = statistics.fmean(getattr(r, key) for r in records)
    return out


# =========================================================================== 黑盒优化接口

class Objective(Protocol):
    """最小化问题。evaluate 返回的结果里必须有 fitness 与 reward。"""

    dim: int

    def bounds(self) -> tuple[np.ndarray, np.ndarray]: ...

    def evaluate(self, x) -> dict: ...


class Optimizer(Protocol):
    def ask(self) -> list: ...
    def tell(self, X, F) -> None: ...
    @property
    def mean(self) -> np.ndarray: ...
    @property
    def sigma(self) -> float: ...


class CmaEs:
    """pycma 适配：只暴露 ask/tell/mean/sigma/D/stop 与状态存取。"""

    def __init__(self, objective: Objective, popsize: int, sigma0: float,
                 seed: int, max_generations: int):
        import cma
        lo, hi = objective.bounds()
        self._strategy = cma.CMAEvolutionStrategy(list(objective.encode() if hasattr(objective, "encode") else np.zeros(objective.dim)),
                                                  sigma0, {
            "popsize": popsize,
            "bounds": [list(lo), list(hi)],
            "seed": seed,
            "verbose": -9,
            "maxiter": max_generations,
            # 评估带噪声：关闭一切收敛早停，只由 max_generations 停
            "tolfun": 0, "tolfunhist": 0, "tolx": 0, "tolflatfitness": 0,
        })

    @classmethod
    def resume(cls, path: Path) -> "CmaEs":
        state = pickle.loads(Path(path).read_bytes())
        self = cls.__new__(cls)
        self._strategy = state["es"]
        self.resumed_state = state
        return self

    def ask(self) -> list:
        return self._strategy.ask()

    def tell(self, X, F) -> None:
        self._strategy.tell(X, F)

    @property
    def mean(self):
        return self._strategy.mean

    @property
    def sigma(self) -> float:
        return float(self._strategy.sigma)

    @property
    def D(self):
        return self._strategy.D

    def stop(self) -> dict:
        return self._strategy.stop()


class BaseObjective:
    """公共部分：解空间接口 + 每代对局规划。子类只实现 evaluate。"""

    def __init__(self, cfg: "TrainConfig", codec: ParamCodec, rng: random.Random):
        self.cfg = cfg
        self.codec = codec
        self.rng = rng
        self.entries = load_pool(cfg.pool)
        self._specs: list[MatchSpec] = []
        self._spare: list[MatchSpec] = []

    def encode(self) -> np.ndarray:
        return self.codec.encode()

    @property
    def dim(self) -> int:
        return self.codec.dim

    def bounds(self):
        return self.codec.bounds()

    def start_generation(self) -> None:
        """每代重新抽对局；同代所有候选共用同一组。"""
        total = self.cfg.games_per_batch * self.cfg.n_batches
        spare = max(2, total // 6)
        planned = make_specs(self.entries, self.rng, total + spare, self.cfg.games_per_batch)
        self._specs, self._spare = planned[:total], planned[total:]


    def evaluate_many(self, X) -> list[dict]:
        """默认逐个评估；真实问题会覆盖成并发版本。"""
        return [self.evaluate(x) for x in X]


class ParamsObjective(BaseObjective):
    """真实问题：把 x 解码成参数文件，跑一批对局，返回可最小化的 fitness。"""

    def __init__(self, cfg: "TrainConfig", codec: ParamCodec, runner: Runner, rng: random.Random):
        super().__init__(cfg, codec, rng)
        self.runner = runner

    def evaluate(self, x) -> dict:
        doc = self.codec.decode(x)
        records = self.runner.games(doc, self._specs, self._spare)
        agg = aggregate(records)
        agg.update(x=[float(v) for v in x], params=doc, records=records)
        agg["fitness"] = -agg["reward"] if agg["valid"] else float("inf")
        return agg


    def evaluate_many(self, X) -> list[dict]:
        """所有候选的 (参数, 规格) 一次性铺开，占满 worker 池。"""
        docs = [self.codec.decode(x) for x in X]
        jobs = [(docs[i], spec) for i in range(len(docs)) for spec in self._specs]
        records = self.runner.run_jobs(jobs)
        # 按提交顺序切回每个候选
        grouped = [[] for _ in docs]
        for idx, (doc, spec) in enumerate(jobs):
            rec = records[idx]
            if not rec.error:
                grouped[idx // max(1, len(self._specs))].append(rec)
        # 补抽：每个候选不足的用 spare 规格补齐（一轮）
        extra_jobs, extra_owner = [], []
        for i, recs in enumerate(grouped):
            missing = len(self._specs) - len(recs)
            for spec in self._spare[:max(0, missing)]:
                extra_jobs.append((docs[i], spec))
                extra_owner.append(i)
        if extra_jobs:
            for owner, rec in zip(extra_owner, self.runner.run_jobs(extra_jobs)):
                if not rec.error:
                    grouped[owner].append(rec)
        out = []
        for x, doc, recs in zip(X, docs, grouped):
            agg = aggregate(recs)
            agg.update(x=[float(v) for v in x], params=doc, records=recs)
            agg["fitness"] = -agg["reward"] if agg["valid"] else float("inf")
            out.append(agg)
        return out


class MockParamsObjective(BaseObjective):
    """dry-run：已知最优点的假问题，签名与 ParamsObjective 相同。"""

    def __init__(self, cfg: "TrainConfig", codec: ParamCodec, rng: random.Random, noise: float = 0.05):
        super().__init__(cfg, codec, rng)
        self.noise = noise
        self.optimum = (codec.bounds()[0] + codec.bounds()[1]) / 2.0

    def evaluate(self, x) -> dict:
        base = -float(np.linalg.norm(np.asarray(x) - self.optimum))
        specs = self._specs[:self.cfg.games_per_batch * self.cfg.n_batches]
        records = [GameRecord(map=s.matchup.name, pair=s.matchup.pair,
                              candidate_spawn=s.candidate_spawn, seed=s.seed, batch=s.batch,
                              max_ticks=self.cfg.max_ticks, ticks=int(self.cfg.max_ticks * 0.6),
                              outcome="win" if base > 0 else "loss",
                              win=1.0 if base > 0 else 0.0,
                              army=max(-1.0, min(1.0, base)), exchange=0.5,
                              samples_ok=True, telemetry_ok=True,
                              reward=base + self.rng.gauss(0.0, self.noise))
                  for s in specs]
        agg = aggregate(records)
        agg.update(x=[float(v) for v in x], params=self.codec.decode(x), records=records)
        agg["fitness"] = -agg["reward"]
        return agg


# =========================================================================== 配置

@dataclass
class TrainConfig:
    """全部可调项；奖励系数也在这里。"""

    # 路径
    params: Path = PARAMS
    pool: Path = POOL
    out_dir: Path = RUNS
    run_name: str = "cma"
    cost_table: Path | None = None

    # 优化器
    popsize: int = 20
    sigma0: float = 0.3
    max_generations: int = 30
    seed: int = 2026

    # 对局
    n_workers: int = 6
    games_per_batch: int = 6
    n_batches: int = 3
    opponent_id: str = "rwx.original.hard"
    candidate_id: str = "rwx.ai-rl-hard"
    match_timeout: float = 600.0
    max_ticks: int = 200000
    income: float = 2.0
    min_valid_games: int = 12

    # 奖励系数
    w_win: float = 1.0
    w_board: float = 0.35            # 局面优势（下四项的加权平均）
    w_build_prod: float = 0.10
    w_build_def: float = 0.10
    w_army: float = 0.15
    w_econ: float = 0.05
    w_time: float = 0.05
    default_unit_cost: float = 300.0
    builder_value_weight: float = 1.2
    building_value_weight: float = 0.4
    death_end_margin_ms: float = 2000.0
    sample_every_ticks: int = 500
    snapshot_fraction: float = 0.75
    telemetry: bool = False

    # 动态权重
    auto_weights: bool = False
    auto_weight_min_signal: float = 0.005

    # 保存 / 验证
    checkpoint_every: int = 1
    keep_checkpoints: int = 3
    permanent_every: int = 10
    validation_every: int = 5
    validation_games: int = 60
    resume: Path | None = None

    # 其它
    frozen_units: list = field(default_factory=list)
    dry_run: bool = False

    @classmethod
    def load(cls, path: Path | None) -> "TrainConfig":
        cfg = cls()
        for key, value in ((read_json(Path(path)) or {}) if path else {}).items():
            if not hasattr(cfg, key):
                continue
            if isinstance(getattr(cfg, key), Path) or key in ("cost_table", "resume"):
                value = Path(value) if value else None
            setattr(cfg, key, value)
        return cfg

    def to_json(self) -> dict:
        return {k: (str(v) if isinstance(v, Path) else v) for k, v in dataclasses.asdict(self).items()}


# =========================================================================== 训练

class Trainer:
    # 顶层奖励项（用相关性判定方向）
    TOP = {"time_score": "w_time"}
    INNER: dict = {}

    def __init__(self, cfg: TrainConfig):
        self.cfg = cfg
        self.run_dir = Path(cfg.out_dir) / cfg.run_name
        self.ckpt_dir = self.run_dir / "checkpoints"
        self.params_dir = self.run_dir / "params"
        for d in (self.run_dir, self.ckpt_dir, self.params_dir, self.run_dir / "games"):
            d.mkdir(parents=True, exist_ok=True)
        atomic_json(self.run_dir / "config.json", cfg.to_json())

        self.codec = ParamCodec(cfg.params, frozen_units=cfg.frozen_units)
        self.rng = random.Random(cfg.seed)
        self.stop_requested = False
        self.started = time.time()
        self.gen = 0
        self.total_games = 0
        self.base_weights = {f: getattr(cfg, f) for f in (list(self.TOP.values()) + list(self.INNER.values()))}
        self.runner = Runner(cfg, self.run_dir)
        self.objective = (MockParamsObjective(cfg, self.codec, self.rng) if cfg.dry_run
                          else ParamsObjective(cfg, self.codec, self.runner, self.rng))
        self.optimizer = self._make_optimizer()

    # -- 优化器 ---------------------------------------------------------
    def _make_optimizer(self) -> CmaEs:
        if self.cfg.resume:
            opt = CmaEs.resume(Path(self.cfg.resume))
            state = opt.resumed_state
            self.gen = int(state["gen"])
            self.total_games = int(state.get("total_games", 0))
            self.rng.setstate(state["rng"])
            print(f"已恢复：gen={self.gen} sigma={opt.sigma:.4f}")
            return opt
        return CmaEs(self.objective, self.cfg.popsize, self.cfg.sigma0,
                     self.cfg.seed, self.cfg.max_generations)

    # -- 训练循环 -------------------------------------------------------
    def train(self) -> None:
        self.write_meta()
        history = self.run_dir / "history.csv"
        fresh = self.cfg.resume is None
        with open(history, "w" if fresh else "a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if fresh:
                writer.writerow(["gen", "games", "elapsed_s", "fit_min", "fit_median", "fit_max",
                                 "fit_std", "sigma", "D_max", "D_min", "stop",
                                 "cadence_economy", "cadence_tactics", "cadence_strategy",
                                 "batch_std", "restarts"])
            while self.gen < self.cfg.max_generations:
                if self.stop_requested:
                    print("收到中断，保存检查点后退出。")
                    self.save_checkpoint(permanent=True)
                    break
                started = time.time()
                self.gen += 1
                self.objective.start_generation()
                X = self.optimizer.ask()
                results = self.objective.evaluate_many(X)
                fitness = self._penalise(results)
                self.optimizer.tell(X, fitness)
                self.total_games += sum(r["valid"] for r in results)
                self._log(writer, fh, fitness, results, time.time() - started)
                self._append_candidates(results)
                if self.cfg.auto_weights:
                    self.adjust_weights(results)
                if self.cfg.checkpoint_every and self.gen % self.cfg.checkpoint_every == 0:
                    self.save_checkpoint()
                if self.cfg.permanent_every and self.gen % self.cfg.permanent_every == 0:
                    self.save_checkpoint(permanent=True)
                if self.cfg.validation_every and self.gen % self.cfg.validation_every == 0:
                    self.validate()
        self.finalize()

    def _penalise(self, results: list[dict]) -> list[float]:
        """有效局不足 / 非有限值：罚到本代最差再差一点，绝不把 NaN/inf 交给 tell。"""
        fitness = [r["fitness"] for r in results]
        finite = [f for f in fitness if math.isfinite(f)]
        penalty = (max(finite) + 0.05) if finite else 1.0
        need = min(self.cfg.min_valid_games, max(1, int(self.cfg.games_per_batch * self.cfg.n_batches * 0.8)))
        fitness = [f if math.isfinite(f) else penalty for f in fitness]
        for i, result in enumerate(results):
            if result["valid"] < need:
                fitness[i] = penalty
                result["penalized"] = True
        return fitness

    # -- 记录 -----------------------------------------------------------
    def _log(self, writer, fh, fitness, results, elapsed: float) -> None:
        fit = fitness or [0.0]
        mean = self.codec.decode(self.optimizer.mean)
        cadence = {n: int(mean["definition"]["cadence"][n]["value"]) for n in self.codec.cadence}
        stop = self.optimizer.stop()
        writer.writerow([
            self.gen, self.total_games, round(elapsed, 1),
            round(min(fit), 6), round(statistics.median(fit), 6), round(max(fit), 6),
            round(statistics.pstdev(fit), 6) if len(fit) > 1 else 0.0,
            round(self.optimizer.sigma, 6),
            round(float(np.max(self.optimizer.D)), 6), round(float(np.min(self.optimizer.D)), 6),
            json.dumps(stop) if stop else "",
            cadence.get("economy", ""), cadence.get("tactics", ""), cadence.get("strategy", ""),
            round(statistics.fmean(r["batch_std"] for r in results), 6),
            self.runner.restarts,
        ])
        fh.flush()
        if self.runner.costs:
            atomic_json(self.run_dir / "costs.json",
                        {k: round(v, 2) for k, v in sorted(self.runner.costs.items())})
        print(f"[gen {self.gen}] fit {min(fit):.4f}/{statistics.median(fit):.4f} "
              f"sigma {self.optimizer.sigma:.4f} {elapsed:.0f}s")

    def _append_candidates(self, results) -> None:
        with open(self.run_dir / "candidates.jsonl", "a", encoding="utf-8") as fh:
            for r in results:
                fh.write(json.dumps({
                    "gen": self.gen, "x": r["x"], "params": r["params"],
                    "reward": r["reward"], "batch_std": r["batch_std"], "valid": r["valid"],
                    "win": r["win"], "board": r["board"],
                    "build_prod": r["build_prod"], "build_def": r["build_def"],
                    "army": r["army"], "time": r["time_score"],
                    "econ": r["econ"], "penalized": r.get("penalized", False),
                    "had_failures": r["valid"] < self.cfg.games_per_batch * self.cfg.n_batches,
                    "games": [g.to_json() for g in r["records"]],
                }, ensure_ascii=False) + "\n")

    # -- 动态权重 -------------------------------------------------------
    def adjust_weights(self, results) -> None:
        """顶层项按 corr+SNR 调（方向反了就归零）；board 内部只按 SNR 调配比。"""
        report = {}
        rewards = [r["reward"] for r in results]

        def stats(comp):
            vals = [r[comp] for r in results]
            between = statistics.pstdev(vals) if len(vals) > 1 else 0.0
            within = [statistics.pstdev(getattr(g, comp) for g in r["records"]) / len(r["records"]) ** 0.5
                      for r in results if len(r["records"]) > 1]
            noise = statistics.fmean(within) if within else 0.0
            return vals, between, noise, statistics.fmean(vals), between / max(noise, 1e-6)

        for comp, field in self.TOP.items():
            vals, between, noise, mean, snr = stats(comp)
            corr = pearson(vals, rewards)
            saturated = abs(mean) > 0.9 and noise < 0.1
            if corr < -0.3:
                factor = 0.0
            elif abs(corr) < 0.2 or saturated or between < self.cfg.auto_weight_min_signal or snr < 0.5:
                factor = 0.2
            else:
                factor = min(1.4, max(1 / 1.4, min(2.0, max(0.5, snr))))
            new = self.base_weights[field] * factor
            setattr(self.cfg, field, round(new, 4))
            report[comp] = {"mean": round(mean, 4), "between": round(between, 4),
                            "noise": round(noise, 4), "snr": round(snr, 2),
                            "corr": round(corr, 2), "saturated": saturated,
                            "factor": round(factor, 2), "weight": round(new, 4)}

        for comp, field in self.INNER.items():
            vals, between, noise, mean, snr = stats(comp)
            saturated = abs(mean) > 0.9 and noise < 0.1
            if saturated or between < self.cfg.auto_weight_min_signal or snr < 0.5:
                factor = 0.2
            else:
                factor = min(2.0, max(0.5, snr))
            new = self.base_weights[field] * factor
            setattr(self.cfg, field, round(new, 4))
            report[comp] = {"mean": round(mean, 4), "between": round(between, 4),
                            "noise": round(noise, 4), "snr": round(snr, 2),
                            "corr": None, "saturated": saturated,
                            "factor": round(factor, 2), "weight": round(new, 4)}

        with open(self.run_dir / "weights.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"gen": self.gen, **report}, ensure_ascii=False) + "\n")

    # -- 验证 -----------------------------------------------------------
    def validate(self) -> None:
        x = self.optimizer.mean
        path = self.params_dir / f"mean_gen{self.gen:04d}.json"
        self.codec.save(x, path)
        if self.cfg.dry_run:
            n = max(1, self.cfg.validation_games)
            wr = max(0.0, min(1.0, 0.5 + (-float(np.linalg.norm(np.asarray(x) - getattr(self.objective, "optimum", x))))))
            lo, hi = wilson_ci(wr * n, n)
            stats = {"games": n, "wins": int(round(wr * n)), "losses": n - int(round(wr * n)),
                     "draws": 0, "win_rate": wr, "wilson": [lo, hi], "per_map": {},
                     "batch_rate_std": 0.0, "mean_ticks": 0.0, "mean_exchange": 0.0, "failures": 0}
        else:
            stats = evaluate_config(path, max(1, self.cfg.validation_games // self.cfg.games_per_batch),
                                    self.cfg.games_per_batch, self.cfg.seed + 999, self.cfg)
        stats.update(gen=self.gen, sigma=self.optimizer.sigma)
        with open(self.run_dir / "validation.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(stats, ensure_ascii=False) + "\n")
        if stats["win_rate"] >= self._best_validation()[0]:
            atomic_json(self.params_dir / "best_val.json", self.codec.decode(x))
        print(f"  验证 gen{self.gen}: 胜率 {stats['win_rate']:.3f} "
              f"[{stats['wilson'][0]:.3f},{stats['wilson'][1]:.3f}] n={stats['games']}")

    def _best_validation(self) -> tuple[float, int]:
        best = (-1.0, -1)
        path = self.run_dir / "validation.jsonl"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                row = read_json_line(line)
                if row.get("win_rate", -1) > best[0]:
                    best = (row["win_rate"], int(row.get("gen", -1)))
        return best

    # -- 保存 -----------------------------------------------------------
    def write_meta(self) -> None:
        atomic_json(self.run_dir / "meta.json", {
            "seed": self.cfg.seed,
            "map_pool": [f"{m.name}@{m.pair[0]}-{m.pair[1]}" for m in load_pool(self.cfg.pool)],
            "params_sha256": sha256_file(Path(self.cfg.params)),
            "game_version": "1.15",
            "cma_version": _cma_version(),
            "git": git_hash(),
            "codec": self.codec.describe(),
            "dry_run": self.cfg.dry_run,
            "started": self.started,
        })

    def save_checkpoint(self, permanent: bool = False) -> None:
        state = {"es": self.optimizer._strategy, "gen": self.gen,
                 "rng": self.rng.getstate(), "total_games": self.total_games,
                 "config": self.cfg.to_json()}
        atomic_pickle(self.ckpt_dir / f"ckpt_gen{self.gen:04d}.pkl", state)
        atomic_pickle(self.ckpt_dir / "latest.pkl", state)
        if permanent:
            atomic_pickle(self.ckpt_dir / f"permanent_gen{self.gen:04d}.pkl", state)
        self.codec.save(self.optimizer.mean, self.params_dir / f"mean_gen{self.gen:04d}.json")
        for old in sorted(self.ckpt_dir.glob("ckpt_gen*.pkl"))[:-self.cfg.keep_checkpoints]:
            old.unlink(missing_ok=True)

    def finalize(self) -> None:
        atomic_json(self.params_dir / "final.json", self.codec.decode(self.optimizer.mean))
        meta = read_json(self.run_dir / "meta.json", {}) or {}
        meta.update(finished=time.time(), generations=self.gen, total_games=self.total_games)
        atomic_json(self.run_dir / "meta.json", meta)
        print(f"训练结束：gen={self.gen} 总对局={self.total_games} "
              f"final -> {self.params_dir / 'final.json'}")


def _cma_version() -> str:
    try:
        import cma
        return getattr(cma, "__version__", "unknown")
    except Exception:
        return "missing"


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

    WORK.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="eval-", dir=str(WORK)))
    cfg.out_dir = workdir.parent
    cfg.run_name = workdir.name
    runner = Runner(cfg, workdir / "run")
    try:
        records = runner.games(doc, specs)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    n = len(records)
    wins = sum(1 for r in records if r.outcome == "win")
    draws = sum(1 for r in records if r.outcome == "draw")
    lo, hi = wilson_ci(wins + 0.5 * draws, n)
    per_map: dict[str, list[str]] = {}
    batch_rate: dict[int, list[bool]] = {}
    for r in records:
        per_map.setdefault(r.map, []).append(r.outcome)
        batch_rate.setdefault(r.batch, []).append(r.outcome == "win")
    rates = [sum(v) / len(v) for v in batch_rate.values() if v]
    return {
        "games": n, "wins": wins, "draws": draws,
        "losses": sum(1 for r in records if r.outcome == "loss"),
        "win_rate": (wins + 0.5 * draws) / n if n else 0.0,
        "wilson": [lo, hi],
        "per_map": {k: {"n": len(v), "wins": v.count("win"), "losses": v.count("loss"),
                        "draws": v.count("draw")} for k, v in per_map.items()},
        "batch_rate_std": statistics.pstdev(rates) if len(rates) > 1 else 0.0,
        "mean_ticks": statistics.fmean(r.ticks for r in records) if records else 0.0,
        "mean_exchange": statistics.fmean(r.exchange for r in records) if records else 0.0,
        "failures": total - n,
    }


# =========================================================================== 自检

def selftest() -> int:
    """ParamCodec 单元测试（不启动游戏）。"""
    codec = ParamCodec(PARAMS)
    doc = codec.doc

    back = codec.decode(codec.encode())
    for n in codec.cadence:
        assert int(doc["definition"]["cadence"][n]["value"]) == \
               int(back["definition"]["cadence"][n]["value"]), f"cadence {n} 未还原"
    a = np.array([doc["units"]["weights"][u]["value"] for u in codec.active], dtype=float)
    b = np.array([back["units"]["weights"][u]["value"] for u in codec.active], dtype=float)
    assert np.abs(a / a.sum() - b / b.sum()).max() < 0.01, "权重相对比例误差过大"

    lo, hi = codec.bounds()
    rng = np.random.default_rng(0)
    for trial in range(200):
        x = (lo + rng.random(codec.dim) * (hi - lo) if trial % 2 == 0
             else lo - 5 + rng.random(codec.dim) * (hi - lo + 10))
        d = codec.decode(x)
        for n in codec.cadence:
            node = d["definition"]["cadence"][n]
            assert node["min"] <= node["value"] <= node["max"], f"{n} 越界"
        for u in codec.active:
            node = d["units"]["weights"][u]
            assert 0.0 <= node["value"] <= node["max"], f"{u} 越界"

    frozen = codec.active[:2]
    c2 = ParamCodec(PARAMS, frozen_units=frozen)
    d2 = c2.decode(c2.encode())
    for u in frozen:
        assert d2["units"]["weights"][u]["value"] == doc["units"]["weights"][u]["value"], f"{u} 被改动"
        assert u not in c2.active

    print(f"selftest 通过：{codec.describe()}；随机/越界 200 组；冻结 {len(frozen)} 个")
    return 0


# =========================================================================== CLI

SKIP_CLI = {"frozen_units", "cost_table"}
# 常用参数的短写（保持旧命令兼容）
CLI_ALIASES = {"n_batches": "batches", "n_workers": "workers", "match_timeout": "timeout",
               "max_generations": "generations"}


def build_train_parser(sub) -> None:
    """从 TrainConfig 的字段自动生成参数，避免三处硬编码列表。"""
    t = sub.add_parser("train", help="训练（默认）")
    t.add_argument("--config", type=Path)
    t.add_argument("--frozen", help="逗号分隔的冻结兵种")
    t.add_argument("--cost-table", dest="cost_table", type=Path)
    t.add_argument("--dry-run", action="store_true", dest="dry_run")
    hints = typing.get_type_hints(TrainConfig)
    for f in dataclasses.fields(TrainConfig):
        if f.name in SKIP_CLI or f.name in ("dry_run", "frozen_units"):
            continue
        kind = hints.get(f.name, str)
        flag = f"--{f.name.replace('_', '-')}"
        flags = [flag]
        short = CLI_ALIASES.get(f.name)
        if short:
            flags.append(f"--{short}")
        if kind is bool or kind == "bool":
            t.add_argument(*flags, action="store_true", dest=f.name)
        else:
            arg_type = Path if kind is Path else int if kind is int else float if kind is float else str
            t.add_argument(*flags, dest=f.name, type=arg_type)


def cmd_train(args) -> int:
    cfg = TrainConfig.load(args.config)
    hints = typing.get_type_hints(TrainConfig)
    for f in dataclasses.fields(TrainConfig):
        value = getattr(args, f.name, None)
        if value is None or f.name in ("frozen_units",):
            continue
        kind = hints.get(f.name)
        if kind is Path and not value:
            continue
        setattr(cfg, f.name, bool(value) if kind is bool else value)
    cfg.frozen_units = [u.strip() for u in (args.frozen or "").split(",") if u.strip()]

    trainer = Trainer(cfg)
    old = signal.signal(signal.SIGINT, lambda *_: setattr(trainer, "stop_requested", True))
    try:
        trainer.train()
    finally:
        signal.signal(signal.SIGINT, old)
    return 0


def cmd_test(args) -> int:
    cfg = TrainConfig.load(args.config)
    if args.workers:
        cfg.n_workers = args.workers
    if args.pool:
        cfg.pool = Path(args.pool)
    if getattr(args, "opponent_id", None):
        cfg.opponent_id = args.opponent_id
    stats = evaluate_config(Path(args.params), args.batches, args.games_per_batch, args.seed, cfg)
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


def cmd_report(args) -> int:
    """只读汇总某个 run：按代统计各奖励项。"""
    run = Path(args.run)
    rows = [read_json_line(line) for line in
            (run / "candidates.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    keys = ("win", "build_prod", "build_def", "army", "exchange", "time", "econ")
    gens: dict[int, list] = {}
    for row in rows:
        gens.setdefault(int(row["gen"]), []).append(row)

    print("gen  n   reward_mean  reward_max  " + "  ".join(f"{k:>10}" for k in keys))
    for gen in sorted(gens):
        rs = gens[gen]
        cells = [f"{gen:>3}", f"{len(rs):>2}",
                 f"{statistics.fmean(r['reward'] for r in rs):>12.4f}",
                 f"{max(r['reward'] for r in rs):>11.4f}"]
        cells += [f"{statistics.fmean(r.get(k, 0.0) for r in rs):>10.3f}" for k in keys]
        print("  ".join(cells))

    best = max(rows, key=lambda r: r["reward"])
    print(f"\n最佳候选：gen={best['gen']} reward={best['reward']:.4f} valid={best['valid']}")
    val = run / "validation.jsonl"
    if val.exists():
        for line in val.read_text(encoding="utf-8").splitlines():
            row = read_json_line(line)
            if row:
                print(f"验证 gen{row['gen']}: 胜率 {row['win_rate']:.3f} n={row['games']}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="CMA-ES 调参：params3.json vs 原版 AI Hard")
    sub = parser.add_subparsers(dest="cmd")

    build_train_parser(sub)

    t = sub.add_parser("test", help="多批评测")
    t.add_argument("--params", type=Path, required=True)
    t.add_argument("--config", type=Path)
    t.add_argument("--pool", type=Path)
    t.add_argument("--batches", type=int, default=10)
    t.add_argument("--games-per-batch", type=int, default=6, dest="games_per_batch")
    t.add_argument("--workers", type=int, default=6)
    t.add_argument("--opponent-id", dest="opponent_id", default=None)
    t.add_argument("--seed", type=int, default=2026)

    r = sub.add_parser("report", help="只读汇总某个 run")
    r.add_argument("--run", type=Path, required=True)

    sub.add_parser("selftest", help="ParamCodec 单元测试")

    args = parser.parse_args(argv or ["train"])
    if args.cmd == "selftest":
        return selftest()
    if args.cmd == "test":
        return cmd_test(args)
    if args.cmd == "report":
        return cmd_report(args)
    return cmd_train(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
