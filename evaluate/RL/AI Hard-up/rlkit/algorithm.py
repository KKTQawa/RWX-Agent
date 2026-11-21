"""算法层：`Objective` / `Optimizer` 协议 + CMA-ES 适配 + 注册表。"""
from __future__ import annotations

import numpy as np
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
