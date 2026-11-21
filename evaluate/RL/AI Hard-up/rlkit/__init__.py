"""rlkit —— AI Hard-up 的参数搜索工具包（可插拔）。

分层
----
``paths``      路径与全局常量
``util``       原子写 / hash / 统计 / 进程清理
``params``     **参数层**：旋钮类型 + 编解码 + 段注册表
``match``      对局规格（地图池、抽样）
``config``     训练配置
``scoring``    单局结果解析与适应度打分
``runner``     **运行类**：并发跑对局
``algorithm``  **算法层**：Objective/Optimizer 协议 + CMA-ES + 注册表
``objective``  问题实现（真实对局 / dry-run）
``evaluation`` 多批评测
``trainer``    训练循环
``cli``        命令行

扩展点
------
* 新参数段：``rlkit.params.register_generic_section("mySection")``，文档里放同名段即可。
* 新优化器：``rlkit.algorithm.register_optimizer("name")``，然后用 ``--optimizer name``。
* 新问题：``rlkit.objective.register_objective("name")``，然后用 ``--objective name``。
"""

from __future__ import annotations

from .algorithm import (OPTIMIZERS, CmaEs, Objective, Optimizer, build_optimizer,
                        register_optimizer)
from .config import TrainConfig
from .objective import OBJECTIVES, build_objective, register_objective
from .params import (KNOB_SECTIONS, Knob, ParamCodec, register_generic_section,
                     register_knob_section)
from .paths import PARAMS, POOL, REPO, RUNS, THETA_BOUND

__all__ = [
    "CmaEs", "Objective", "Optimizer", "OPTIMIZERS", "build_optimizer", "register_optimizer",
    "TrainConfig",
    "OBJECTIVES", "build_objective", "register_objective",
    "Knob", "ParamCodec", "KNOB_SECTIONS", "register_knob_section", "register_generic_section",
    "PARAMS", "POOL", "REPO", "RUNS", "THETA_BOUND",
]
