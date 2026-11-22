#!/bin/bash
# cma-h9：[p4]Island freeze (4p) [by hxyy] 上的固定 2v2。
# 我方两个 Hard-up 调参（出生点 1/3，同色同盟）vs 对手两个内置 Very Hard（2/4），房间收入 x2。
# 起点 = cma-h8 验证最好的权重（best_val.json = mean_gen0200.json）。
set -u
R=/home/aqf/codes/rwx-rl
cd "$R" || exit 1
export RWX_REPO="$R"
export RWX_JAVA="$R/jdk-25.0.5+8/bin/java"
export RWX_LIB="$R/lib"
PY="$HOME/miniconda3/envs/image/bin/python"
echo "[cma-h9] params=$R/runs/cma-h8/params/best_val.json pool=$R/pool-islandfreeze-2v2.json"
exec "$PY" -u optimize.py train \
  --params "$R/runs/cma-h8/params/best_val.json" \
  --pool "$R/pool-islandfreeze-2v2.json" \
  --out-dir "$R/runs" \
  --run-name cma-h9 \
  --popsize 4 \
  --games-per-batch 1 \
  --batches 3 \
  --workers 12 \
  --generations 300 \
  --sigma0 0.2 \
  --max-ticks 337500 \
  --timeout 1800 \
  --opponent-id rwx.original.very-hard \
  --candidate-id rwx.ai-rl-hard \
  --income 2.0 \
  --w-draw 0.2 \
  --seed 3070 \
  --validation-every 100 \
  --validation-games 60 \
  --checkpoint-every 1
