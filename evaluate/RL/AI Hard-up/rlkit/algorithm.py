"""算法层：`Objective` / `Optimizer` 协议 + CMA-ES 适配 + 注册表。"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pickle

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



def _cma_version() -> str:
    try:
        import cma
        return getattr(cma, "__version__", "unknown")
    except Exception:
        return "missing"


@dataclass
class SingleCandidateState:
    mean: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    sigma: float
    rng: np.random.Generator
    best_fitness: float | None = None


class SingleCandidateES:
    """(1+1)-ES. Evaluate the starting point first, then one mutation per generation."""

    def __init__(self, objective, sigma, seed):
        lower, upper = objective.bounds()
        self._strategy = SingleCandidateState(objective.encode(), lower, upper, sigma,
                                              np.random.default_rng(seed))

    @classmethod
    def resume(cls, path):
        state = pickle.loads(Path(path).read_bytes())
        if not isinstance(state["es"], SingleCandidateState):
            raise ValueError("Checkpoint does not contain a one-plus-one optimizer")
        self = cls.__new__(cls)
        self._strategy = state["es"]
        self.resumed_state = state
        return self

    def ask(self):
        state = self._strategy
        if state.best_fitness is None:
            return [state.mean.copy()]
        step = state.rng.normal(size=state.mean.size) * state.sigma
        return [np.clip(state.mean + step * (state.upper - state.lower), state.lower, state.upper)]

    def tell(self, X, F):
        state = self._strategy
        if state.best_fitness is None or F[0] < state.best_fitness:
            state.mean = np.asarray(X[0]).copy()
            state.best_fitness = float(F[0])

    @property
    def mean(self):
        return self._strategy.mean

    @property
    def sigma(self):
        return self._strategy.sigma

    @property
    def D(self):
        return np.ones_like(self.mean)

    def stop(self):
        return {}


# =========================================================================== 注册表（可插拔）

OPTIMIZERS: dict = {}


def register_optimizer(name: str, description: str = ""):
    """注册一个优化器：``factory(objective=..., cfg=...) -> Optimizer``。"""

    def deco(factory):
        OPTIMIZERS[name] = {"factory": factory, "description": description}
        return factory

    return deco


def build_optimizer(name: str, objective, cfg):
    entry = OPTIMIZERS.get(name)
    if entry is None:
        raise SystemExit(f"未知优化器 {name!r}；已注册：{sorted(OPTIMIZERS)}")
    return entry["factory"](objective=objective, cfg=cfg)


@register_optimizer("cma-es", "pycma 的 CMA-ES（默认；支持 --resume 续训）")
def _make_cma_es(objective, cfg):
    if cfg.resume:
        return CmaEs.resume(Path(cfg.resume))
    return CmaEs(objective, cfg.popsize, cfg.sigma0, cfg.seed, cfg.max_generations)


@register_optimizer("one-plus-one", "(1+1)-ES，每代只评估一个候选")
def _make_single_candidate(objective, cfg):
    if cfg.popsize != 1:
        raise ValueError("one-plus-one requires --popsize 1")
    if cfg.resume:
        return SingleCandidateES.resume(cfg.resume)
    if not np.isfinite(cfg.sigma0) or cfg.sigma0 <= 0:
        raise ValueError("--sigma0 must be positive and finite")
    return SingleCandidateES(objective, cfg.sigma0, cfg.seed)
