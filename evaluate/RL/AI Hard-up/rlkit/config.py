"""训练配置（`TrainConfig`）：一次训练的所有输入与权重。"""
from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field

import dataclasses

from .paths import PARAMS, POOL, RUNS
from .scenarios import SCENARIOS
from .util import read_json

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

    # 优化器 / 问题（名字，注册表见 algorithm.py / objective.py）
    optimizer: str = "cma-es"
    objective: str = "matches"

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
    opponent_config: Path | None = None
    candidate_id: str = "rwx.ai-rl-hard"
    match_timeout: float = 600.0
    # 一 tick = 16ms（62.5 tick/s，见 TICKS_PER_SECOND）。90 分钟 = 5400s = 337500 tick。
    # 之前写成 216000 是按 60fps 估的，实际只有 57.6 分钟。
    max_ticks: int = 337500  # 90 分钟 @62.5tps
    retry_wall_limit: bool = False
    income: float = 2.0
    min_valid_games: int = 12

    # 奖励系数（v2：赢局 base 1.0，输局 base 0.0；时间项为归一化项）
    #   win : R = 1.00 + w_win_offense·clip(r,0,1) + w_win_time·speed     ∈ [1.00, 1.30]
    #   loss: R = 0.00 + w_loss_trade·trade        + w_loss_time·survive  ∈ [0.00, 0.30]
    # 这两个 0.30 的总额是刻意固定的；w_win_time / w_loss_time 分别等于旧口径里的 0.07 / 0.14，
    # 不再交给 auto-weights（单局采样下 SNR 恒为无穷，只会把权重顶到上限）。
    w_win: float = 1.0
    w_board: float = 0.35            # 未使用（board 已退出奖励）
    w_build_prod: float = 0.10
    w_build_def: float = 0.10
    w_win_offense: float = 0.23      # 胜局：进攻推进 clip(r,0,1)
    w_win_time: float = 0.07         # 胜局：speed = 1 − t/T
    w_loss_trade: float = 0.16       # 败局：兵力交换 trade = (r_unit+1)/2
    w_loss_time: float = 0.14        # 败局：survive = t/T
    w_draw: float | None = None      # 旧版平局基准覆盖值。默认 v1 0.30，v2 0.20
    win_time_limit: float = 3600.0   # v1/v2 时间归一化基准（游戏秒）
    w_army: float = 0.30           # 已废弃：旧的胜局 army 权重（仅保留字段兼容旧 config）
    w_army_loss: float = 0.10      # 已废弃
    w_econ: float = 0.05
    w_time: float = 0.05           # 已废弃
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
    scenario: str | None = None

    @property
    def legacy_draw_base(self) -> float:
        if self.w_draw is not None:
            return self.w_draw
        return 0.30 if self.scenario == "hardupv1" else 0.20

    @classmethod
    def load(cls, path: Path | None, *, scenario: str | None = None) -> "TrainConfig":
        values = (read_json(Path(path)) or {}) if path else {}
        selected = scenario if scenario is not None else values.get("scenario")
        cfg = cls(scenario=selected)
        if selected is not None:
            if selected not in SCENARIOS:
                raise ValueError(f"Unknown scenario {selected!r}; choose from {', '.join(SCENARIOS)}")
            cfg.params, cfg.pool = SCENARIOS[selected]
            cfg.run_name = f"cma-{selected}"
        for key, value in values.items():
            if key == "scenario" or not hasattr(cfg, key):
                continue
            if isinstance(getattr(cfg, key), Path) or key in ("cost_table", "resume", "opponent_config"):
                value = Path(value) if value else None
            setattr(cfg, key, value)
        return cfg

    def to_json(self) -> dict:
        return {k: (str(v) if isinstance(v, Path) else v) for k, v in dataclasses.asdict(self).items()}
