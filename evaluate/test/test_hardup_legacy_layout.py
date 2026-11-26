"""legacy_v2 的 57 维重建：params_Hardupv2.json 的区间放宽后仍要还原历史 bounds。

历史 57 维布局 = 当前 v2 文档 + `impossible.defensiveScoreBase` + 建造间隔值 180 + 当年的
min/max。这里造出这份「历史 bounds」，再让 legacy_layout 只靠模板分支重建，要求逐位相等。
"""
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "RL" / "AI Hard-up"))

from rlkit.legacy_v2 import legacy_layout  # noqa: E402
from rlkit.params import ParamCodec  # noqa: E402
from rlkit.scenarios import SCENARIOS, uses_legacy_v2_timer  # noqa: E402

# 2026-11-26 之前 params_Hardupv2.json 声明的区间；narrow/wide 取其中一种历史下限。
LEGACY_BOUNDS = {
    ("building", "attemptIntervalFrames"): (100, 650),
    ("impossible", "builderGroupMaxUnits"): (4, 16),
    ("impossible", "attackGroupMaxUnitsNarrow"): (7, 24),
    ("impossible", "attackGroupMaxUnitsWide"): (7, 32),
    ("impossible", "seaGroupMaxUnits"): (4, 20),
    ("impossible", "productionIdleUnitsLimit"): (20, 150),
}


def set_range(document, path, low, high):
    node = document
    for key in path[:-1]:
        node = node[key]
    node[path[-1]]["min"], node[path[-1]]["max"] = low, high


class LegacyV2LayoutTest(unittest.TestCase):
    def test_template_branch_restores_pre_widening_bounds(self):
        template = SCENARIOS["hardupv2"][0]
        document = json.loads(template.read_text(encoding="utf-8"))
        document["schema"] = "rwx-rl-ai-v1"
        document["building"]["attemptIntervalFrames"]["value"] = 180
        impossible = {}
        for name, value in document["impossible"].items():
            impossible[name] = value
            if name == "seaGroupMaxUnits":
                impossible["defensiveScoreBase"] = {
                    "name": "防守分基数（帧）", "type": "float",
                    "value": 190, "min": 120, "max": 400, "step": 10}
        document["impossible"] = impossible
        for path, (low, high) in LEGACY_BOUNDS.items():
            set_range(document, path, low, high)

        historical = ParamCodec(template, document=deepcopy(document))
        self.assertTrue(uses_legacy_v2_timer(historical.doc))
        self.assertEqual(historical.dim, 57)

        current = ParamCodec(template)
        self.assertEqual(current.dim, 56)
        state = {"gen": 0, "es": SimpleNamespace(
            boundary_handler=SimpleNamespace(bounds=historical.bounds()))}
        checkpoint = template.parent / "runs/fake/checkpoints/ckpt.pkl"

        rebuilt = legacy_layout(current, checkpoint, state, frozen_units=None)
        self.assertEqual(rebuilt.dim, 57)
        self.assertTrue(np.array_equal(np.asarray(rebuilt.bounds()),
                                       np.asarray(historical.bounds())))


if __name__ == "__main__":
    unittest.main()
