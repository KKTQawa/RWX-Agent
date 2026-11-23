#!/bin/bash
# 从 runs/cma-h9/checkpoints/latest.pkl 续训到 300 代（2v2 Island freeze，我方 1/3 vs VH 2/4，x2 收入）
set -u
R=/home/aqf/codes/rwx-rl
cd "$R" || exit 1
export RWX_REPO="$R"
export RWX_JAVA="$R/jdk-25.0.5+8/bin/java"
export RWX_LIB="$R/lib"
PY="$HOME/miniconda3/envs/image/bin/python"
exec "$PY" -u - <<'PY'
from pathlib import Path
from rlkit.config import TrainConfig
from rlkit.trainer import Trainer

run = Path("runs/cma-h9").resolve()
cfg = TrainConfig.load(run / "config.json")
cfg.resume = run / "checkpoints" / "latest.pkl"
cfg.max_generations = 300
assert cfg.opponent_id == "rwx.original.very-hard", cfg.opponent_id
assert cfg.candidate_id == "rwx.ai-rl-hard" and cfg.income == 2.0
assert cfg.pool.name == "pool-islandfreeze-2v2.json", cfg.pool
trainer = Trainer(cfg)
assert trainer.gen >= 14, trainer.gen
print(f"resume cma-h9 at gen {trainer.gen} -> {cfg.max_generations}")
trainer.train()
PY
