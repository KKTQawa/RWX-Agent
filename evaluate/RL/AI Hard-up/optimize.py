#!/usr/bin/env python3
"""AI Hard-up 参数搜索入口。

实现拆在 ``rlkit/`` 包里（参数层 / 运行类 / 算法层 / 训练循环 / CLI）；
本文件只做入口转发，保持 ``python optimize.py ...`` 的旧用法不变。

    python optimize.py                 # = train
    python optimize.py train --dry-run
    python optimize.py test --params params6.json
    python optimize.py report --run runs/cma-g3
    python optimize.py selftest

扩展：加参数段看 ``rlkit/params.py``，加优化器看 ``rlkit/algorithm.py``，
加问题看 ``rlkit/objective.py``。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rlkit.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
