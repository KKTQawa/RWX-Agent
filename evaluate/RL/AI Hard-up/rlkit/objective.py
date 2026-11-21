"""问题实现：把参数解码成配置、交给运行类跑局、把记录折成 fitness。"""
from __future__ import annotations

import numpy as np

import random

from .params import ParamCodec
from .match import MatchSpec, load_pool, make_specs
from .config import TrainConfig
from .scoring import GameRecord
from .runner import Runner, aggregate

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
        """每代重新抽对局；同代所有候选共用同一组，槽位按代轮换。"""
        self._phase = getattr(self, "_phase", -1) + 1
        total = self.cfg.games_per_batch * self.cfg.n_batches
        spare = max(2, total // 6)
        planned = make_specs(self.entries, self.rng, total + spare, self.cfg.games_per_batch,
                             phase=self._phase)
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


# =========================================================================== 注册表（可插拔）

OBJECTIVES: dict = {}


def register_objective(name: str, description: str = ""):
    """注册一个问题：``factory(cfg=..., codec=..., rng=..., runner=...) -> BaseObjective``。"""

    def deco(factory):
        OBJECTIVES[name] = {"factory": factory, "description": description}
        return factory

    return deco


def build_objective(name: str, cfg, codec, rng, runner):
    entry = OBJECTIVES.get(name)
    if entry is None:
        raise SystemExit(f"未知问题 {name!r}；已注册：{sorted(OBJECTIVES)}")
    return entry["factory"](cfg=cfg, codec=codec, rng=rng, runner=runner)


@register_objective("matches", "真跑对局（默认）")
def _make_matches(cfg, codec, rng, runner):
    return ParamsObjective(cfg, codec, runner, rng)


@register_objective("dry-run", "不启动游戏，用假对局验证训练循环")
def _make_dry(cfg, codec, rng, runner):
    return MockParamsObjective(cfg, codec, rng)
