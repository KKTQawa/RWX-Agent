#!/bin/bash
# cma-h10：Crossing 6p + 火山 8p，1v1 对 Very Hard，房间收入 x2，每代 12 局，500 代。
# 起点 = cma-h9 验证最好的权重（gen200，2v2 验证 75%）
set -u
R=/home/aqf/codes/rwx-rl
cd "$R" || exit 1
export RWX_REPO="$R"
export RWX_JAVA="$R/jdk-25.0.5+8/bin/java"
export RWX_LIB="$R/lib"
PY="$HOME/miniconda3/envs/image/bin/python"
echo "[cma-h10] params=$R/runs/cma-h9/params/best_val.json pool=$R/pool-crossing-volcano-1v1.json"
exec "$PY" -u optimize.py train \
  --params "$R/runs/cma-h9/params/best_val.json" \
  --pool "$R/pool-crossing-volcano-1v1.json" \
  --out-dir "$R/runs" \
  --run-name cma-h10 \
  --popsize 4 \
  --games-per-batch 1 \
  --batches 3 \
  --workers 12 \
  --generations 500 \
  --sigma0 0.2 \
  --max-ticks 337500 \
  --timeout 1800 \
  --opponent-id rwx.original.very-hard \
  --candidate-id rwx.ai-rl-hard \
  --income 2.0 \
  --w-draw 0.2 \
  --seed 4070 \
  --validation-every 100 \
  --validation-games 60 \
  --checkpoint-every 1
