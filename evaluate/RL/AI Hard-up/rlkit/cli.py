"""命令行：train / test / report / selftest。"""
from __future__ import annotations

import numpy as np
from pathlib import Path

import argparse
import dataclasses
import json
import signal
import statistics
import sys
import typing

from .paths import PARAMS
from .params import ParamCodec
from .config import TrainConfig
from .scoring import read_json_line
from .evaluation import evaluate_config
from .trainer import Trainer

# =========================================================================== 自检

def selftest() -> int:
    """ParamCodec 单元测试（不启动游戏）：所有旋钮的还原、取整、越界与权重冻结。"""
    codec = ParamCodec(PARAMS)
    doc = codec.doc
    back = codec.decode(codec.encode())

    def at(node, path):
        for key in path:
            node = node[key]
        return node

    # 1) 每个旋钮 encode→decode 必须原样还原（默认值都应落在 step 网格上）
    for knob in codec.knobs:
        before = at(doc, knob.path)
        after = at(back, knob.path)
        b = before["value"] if isinstance(before, dict) else before
        a = after["value"] if isinstance(after, dict) else after
        assert abs(float(b) - float(a)) <= knob.step / 2 + 1e-9, f"{knob.label} 未还原：{b} -> {a}"
        if knob.kind == "int":
            assert float(a).is_integer(), f"{knob.label} 应取整，实际 {a}"

    # 2) 权重相对比例保持不变
    a = np.array([doc["units"]["weights"][u]["value"] for u in codec.active], dtype=float)
    b = np.array([back["units"]["weights"][u]["value"] for u in codec.active], dtype=float)
    assert np.abs(a / a.sum() - b / b.sum()).max() < 0.01, "权重相对比例误差过大"

    # 3) 随机/越界 200 组：每个旋钮都要落在文档区间内，且类型正确
    lo, hi = codec.bounds()
    rng = np.random.default_rng(0)
    for trial in range(200):
        x = (lo + rng.random(codec.dim) * (hi - lo) if trial % 2 == 0
             else lo - 5 + rng.random(codec.dim) * (hi - lo + 10))
        d = codec.decode(x)
        for knob in codec.knobs:
            node = at(d, knob.path)
            value = node["value"] if isinstance(node, dict) else node
            assert knob.min - 1e-9 <= float(value) <= knob.max + 1e-9, f"{knob.label} 越界：{value}"
            grid = float(value) / knob.step
            assert abs(grid - round(grid)) < 1e-6, f"{knob.label} 未落在 step 网格上：{value}"
            if knob.kind == "int":
                assert float(value).is_integer(), f"{knob.label} 应为整数：{value}"
        for u in codec.active:
            node = d["units"]["weights"][u]
            assert 0.0 <= node["value"] <= node["max"], f"{u} 越界"

    # 4) 冻结兵种不被改动
    frozen = codec.active[:2]
    c2 = ParamCodec(PARAMS, frozen_units=frozen)
    d2 = c2.decode(c2.encode())
    for u in frozen:
        assert d2["units"]["weights"][u]["value"] == doc["units"]["weights"][u]["value"], f"{u} 被改动"
        assert u not in c2.active

    kinds: dict[str, int] = {}
    for knob in codec.knobs:
        kinds[knob.kind] = kinds.get(knob.kind, 0) + 1
    print(f"selftest 通过：{codec.describe()}；旋钮 {kinds}；随机/越界 200 组；冻结 {len(frozen)} 个")
    return 0


# =========================================================================== CLI

SKIP_CLI = {"frozen_units", "cost_table"}
# 常用参数的短写（保持旧命令兼容）
CLI_ALIASES = {"n_batches": "batches", "n_workers": "workers", "match_timeout": "timeout",
               "max_generations": "generations"}


def build_train_parser(sub) -> None:
    """从 TrainConfig 的字段自动生成参数，避免三处硬编码列表。"""
    t = sub.add_parser("train", help="训练（默认）")
    t.add_argument("--config", type=Path)
    t.add_argument("--frozen", help="逗号分隔的冻结兵种")
    t.add_argument("--cost-table", dest="cost_table", type=Path)
    t.add_argument("--dry-run", action="store_true", dest="dry_run")
    hints = typing.get_type_hints(TrainConfig)
    for f in dataclasses.fields(TrainConfig):
        if f.name in SKIP_CLI or f.name in ("dry_run", "frozen_units"):
            continue
        kind = hints.get(f.name, str)
        flag = f"--{f.name.replace('_', '-')}"
        flags = [flag]
        short = CLI_ALIASES.get(f.name)
        if short:
            flags.append(f"--{short}")
        if kind is bool or kind == "bool":
            t.add_argument(*flags, action="store_true", dest=f.name)
        else:
            arg_type = Path if kind is Path else int if kind is int else float if kind is float else str
            t.add_argument(*flags, dest=f.name, type=arg_type)


def cmd_train(args) -> int:
    cfg = TrainConfig.load(args.config)
    hints = typing.get_type_hints(TrainConfig)
    for f in dataclasses.fields(TrainConfig):
        value = getattr(args, f.name, None)
        if value is None or f.name in ("frozen_units",):
            continue
        kind = hints.get(f.name)
        if kind is Path and not value:
            continue
        setattr(cfg, f.name, bool(value) if kind is bool else value)
    cfg.frozen_units = [u.strip() for u in (args.frozen or "").split(",") if u.strip()]

    trainer = Trainer(cfg)
    old = signal.signal(signal.SIGINT, lambda *_: setattr(trainer, "stop_requested", True))
    try:
        trainer.train()
    finally:
        signal.signal(signal.SIGINT, old)
    return 0


def cmd_test(args) -> int:
    cfg = TrainConfig.load(args.config)
    if args.workers:
        cfg.n_workers = args.workers
    if args.pool:
        cfg.pool = Path(args.pool)
    if getattr(args, "opponent_id", None):
        cfg.opponent_id = args.opponent_id
    if getattr(args, "candidate_id", None):
        cfg.candidate_id = args.candidate_id
    stats = evaluate_config(Path(args.params), args.batches, args.games_per_batch, args.seed, cfg)
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


def cmd_report(args) -> int:
    """只读汇总某个 run：按代统计各奖励项。"""
    run = Path(args.run)
    rows = [read_json_line(line) for line in
            (run / "candidates.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    keys = ("win", "build_prod", "build_def", "army", "exchange", "time", "econ")
    gens: dict[int, list] = {}
    for row in rows:
        gens.setdefault(int(row["gen"]), []).append(row)

    print("gen  n   reward_mean  reward_max  " + "  ".join(f"{k:>10}" for k in keys))
    for gen in sorted(gens):
        rs = gens[gen]
        cells = [f"{gen:>3}", f"{len(rs):>2}",
                 f"{statistics.fmean(r['reward'] for r in rs):>12.4f}",
                 f"{max(r['reward'] for r in rs):>11.4f}"]
        cells += [f"{statistics.fmean(r.get(k, 0.0) for r in rs):>10.3f}" for k in keys]
        print("  ".join(cells))

    best = max(rows, key=lambda r: r["reward"])
    print(f"\n最佳候选：gen={best['gen']} reward={best['reward']:.4f} valid={best['valid']}")
    val = run / "validation.jsonl"
    if val.exists():
        for line in val.read_text(encoding="utf-8").splitlines():
            row = read_json_line(line)
            if row:
                print(f"验证 gen{row['gen']}: 胜率 {row['win_rate']:.3f} n={row['games']}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="CMA-ES 调参：params6.json vs 原版 AI Hard")
    sub = parser.add_subparsers(dest="cmd")

    build_train_parser(sub)

    t = sub.add_parser("test", help="多批评测")
    t.add_argument("--params", type=Path, required=True)
    t.add_argument("--config", type=Path)
    t.add_argument("--pool", type=Path)
    t.add_argument("--batches", type=int, default=10)
    t.add_argument("--games-per-batch", type=int, default=6, dest="games_per_batch")
    t.add_argument("--workers", type=int, default=6)
    t.add_argument("--opponent-id", dest="opponent_id", default=None)
    t.add_argument("--candidate-id", dest="candidate_id", default=None,
                   help="被测方的 AI id（默认 rwx.ai-rl-hard）；改成内置 AI 时 --params 只作占位")
    t.add_argument("--seed", type=int, default=2026)

    r = sub.add_parser("report", help="只读汇总某个 run")
    r.add_argument("--run", type=Path, required=True)

    sub.add_parser("selftest", help="ParamCodec 单元测试")

    args = parser.parse_args(argv or ["train"])
    if args.cmd == "selftest":
        return selftest()
    if args.cmd == "test":
        return cmd_test(args)
    if args.cmd == "report":
        return cmd_report(args)
    return cmd_train(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
