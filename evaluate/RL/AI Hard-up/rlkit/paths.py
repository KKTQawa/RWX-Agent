"""路径与全局常量（可用 `RWX_REPO` 环境变量覆盖仓库根）。"""
from __future__ import annotations

from pathlib import Path

import os


HERE = Path(__file__).resolve().parent.parent
REPO = Path(os.environ.get("RWX_REPO", str(HERE.parents[2])))
RUN_ENV = REPO / "evaluate" / "RL" / "run-env.ps1"
POOL = HERE / "completition.json"
PARAMS = HERE / "params6.json"
WORK = REPO / "agent-tmp" / "rl-pool"
RUNS = HERE / "runs"

SMALL_WEIGHT = 0.05     # 小于它置 0
THETA_BOUND = 3.0       # θ 硬边界
TICKS_PER_SECOND = 62.5
