"""训练循环：ask/tell、记录、检查点、resume。"""
from __future__ import annotations

import numpy as np
from pathlib import Path

import csv
import json
import math
import random
import statistics
import time

from .util import atomic_json, atomic_pickle, git_hash, pearson, read_json, sha256_file, wilson_ci
from .params import ParamCodec
from .match import load_pool
from .config import TrainConfig
from .scoring import read_json_line
from .runner import Runner
from .algorithm import build_optimizer, _cma_version
from .objective import build_objective
from .evaluation import evaluate_config

# =========================================================================== 训练

class Trainer:
    # 顶层奖励项（用相关性判定方向）。v2 起为空：奖励系数是刻意固定的，
    # 单局采样下 auto-weights 的 SNR 恒为无穷，只会把权重顶到 1.4× 上限。
    TOP: dict = {}
    INNER: dict = {}

    def __init__(self, cfg: TrainConfig):
        self.cfg = cfg
        self.run_dir = Path(cfg.out_dir) / cfg.run_name
        self.ckpt_dir = self.run_dir / "checkpoints"
        self.params_dir = self.run_dir / "params"
        for d in (self.run_dir, self.ckpt_dir, self.params_dir, self.run_dir / "games"):
            d.mkdir(parents=True, exist_ok=True)
        atomic_json(self.run_dir / "config.json", cfg.to_json())

        self.codec = ParamCodec(cfg.params, frozen_units=cfg.frozen_units)
        self.rng = random.Random(cfg.seed)
        self.stop_requested = False
        self.started = time.time()
        self.gen = 0
        self.total_games = 0
        self.base_weights = {f: getattr(cfg, f) for f in (list(self.TOP.values()) + list(self.INNER.values()))}
        self.runner = Runner(cfg, self.run_dir)
        objective_name = "dry-run" if cfg.dry_run else cfg.objective
        self.objective = build_objective(objective_name, cfg, self.codec, self.rng, self.runner)
        self.optimizer = self._make_optimizer()

    # -- 优化器 ---------------------------------------------------------
    def _make_optimizer(self):
        opt = build_optimizer(self.cfg.optimizer, self.objective, self.cfg)
        state = getattr(opt, "resumed_state", None)
        if state:
            if len(opt.mean) != self.codec.dim:
                raise SystemExit(
                    f"检查点维度 {len(opt.mean)} 与当前参数集 {self.codec.dim} 不一致："
                    f"参数文档变了就不能续训，请换回旧 --params 或去掉 --resume。")
            self.gen = int(state["gen"])
            self.total_games = int(state.get("total_games", 0))
            self.rng.setstate(state["rng"])
            print(f"已恢复：gen={self.gen} sigma={opt.sigma:.4f}")
        return opt

    # -- 训练循环 -------------------------------------------------------
    def train(self) -> None:
        self.write_meta()
        history = self.run_dir / "history.csv"
        fresh = self.cfg.resume is None
        with open(history, "w" if fresh else "a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if fresh:
                writer.writerow(["gen", "games", "elapsed_s", "fit_min", "fit_median", "fit_max",
                                 "fit_std", "sigma", "D_max", "D_min", "stop",
                                 "cadence_economy", "cadence_tactics", "cadence_strategy",
                                 "batch_std", "restarts"])
            while self.gen < self.cfg.max_generations:
                if self.stop_requested:
                    print("收到中断，保存检查点后退出。")
                    self.save_checkpoint(permanent=True)
                    break
                started = time.time()
                self.gen += 1
                self.objective.start_generation()
                X = self.optimizer.ask()
                results = self.objective.evaluate_many(X)
                fitness = self._penalise(results)
                self.optimizer.tell(X, fitness)
                self.total_games += sum(r["valid"] for r in results)
                self._log(writer, fh, fitness, results, time.time() - started)
                self._append_candidates(results)
                if self.cfg.auto_weights:
                    self.adjust_weights(results)
                if self.cfg.checkpoint_every and self.gen % self.cfg.checkpoint_every == 0:
                    self.save_checkpoint()
                if self.cfg.permanent_every and self.gen % self.cfg.permanent_every == 0:
                    self.save_checkpoint(permanent=True)
                if self.cfg.validation_every and self.gen % self.cfg.validation_every == 0:
                    self.validate()
        self.finalize()

    def _penalise(self, results: list[dict]) -> list[float]:
        """有效局不足 / 非有限值：罚到本代最差再差一点，绝不把 NaN/inf 交给 tell。"""
        fitness = [r["fitness"] for r in results]
        finite = [f for f in fitness if math.isfinite(f)]
        penalty = (max(finite) + 0.05) if finite else 1.0
        need = min(self.cfg.min_valid_games, max(1, int(self.cfg.games_per_batch * self.cfg.n_batches * 0.8)))
        fitness = [f if math.isfinite(f) else penalty for f in fitness]
        for i, result in enumerate(results):
            if result["valid"] < need:
                fitness[i] = penalty
                result["penalized"] = True
        return fitness

    # -- 记录 -----------------------------------------------------------
    def _log(self, writer, fh, fitness, results, elapsed: float) -> None:
        fit = fitness or [0.0]
        mean = self.codec.decode(self.optimizer.mean)
        cadence = {n: int(mean["definition"]["cadence"][n]["value"]) for n in self.codec.cadence}
        stop = self.optimizer.stop()
        writer.writerow([
            self.gen, self.total_games, round(elapsed, 1),
            round(min(fit), 6), round(statistics.median(fit), 6), round(max(fit), 6),
            round(statistics.pstdev(fit), 6) if len(fit) > 1 else 0.0,
            round(self.optimizer.sigma, 6),
            round(float(np.max(self.optimizer.D)), 6), round(float(np.min(self.optimizer.D)), 6),
            json.dumps(stop) if stop else "",
            cadence.get("economy", ""), cadence.get("tactics", ""), cadence.get("strategy", ""),
            round(statistics.fmean(r["batch_std"] for r in results), 6),
            self.runner.restarts,
        ])
        fh.flush()
        if self.runner.costs:
            atomic_json(self.run_dir / "costs.json",
                        {k: round(v, 2) for k, v in sorted(self.runner.costs.items())})
        print(f"[gen {self.gen}] fit {min(fit):.4f}/{statistics.median(fit):.4f} "
              f"sigma {self.optimizer.sigma:.4f} {elapsed:.0f}s")

    def _append_candidates(self, results) -> None:
        with open(self.run_dir / "candidates.jsonl", "a", encoding="utf-8") as fh:
            for r in results:
                fh.write(json.dumps({
                    "gen": self.gen, "x": r["x"], "params": r["params"],
                    "reward": r["reward"], "batch_std": r["batch_std"], "valid": r["valid"],
                    "win": r["win"], "board": r["board"],
                    "build_prod": r["build_prod"], "build_def": r["build_def"],
                    "army": r["army"], "bld_value": r.get("bld_value", 0.0), "time": r["time_score"],
                    "r_unit": r.get("r_unit", 0.0), "trade": r.get("trade", 0.0),
                    "speed": r.get("speed", 0.0), "survive": r.get("survive", 0.0),
                    "econ": r["econ"], "penalized": r.get("penalized", False),
                    "had_failures": r["valid"] < self.cfg.games_per_batch * self.cfg.n_batches,
                    "games": [g.to_json() for g in r["records"]],
                }, ensure_ascii=False) + "\n")

    # -- 动态权重 -------------------------------------------------------
    def adjust_weights(self, results) -> None:
        """v2：奖励系数固定，不做自动调权。

        旧实现按 corr+SNR 调 army / time_score。但 games_per_batch=1 时候选内部只打 1 局，
        within 标准差恒为 0 → snr = between/1e-6 = ∞ → factor 永远取 1.4 上限，
        实际只剩「corr<-0.3 清零 / 否则顶格」两条规则，没有信息量。
        需要自适应权重时应先把每候选局数提到 ≥3，再启用这里的分支。
        """
        if not self.TOP and not self.INNER:
            with open(self.run_dir / "weights.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "gen": self.gen,
                    "frozen": {k: getattr(self.cfg, k) for k in
                               ("w_win_offense", "w_win_time", "w_loss_trade", "w_loss_time")},
                    "win_time_limit": self.cfg.win_time_limit,
                }, ensure_ascii=False) + "\n")
            return
        report = {}
        rewards = [r["reward"] for r in results]

        def stats(comp):
            vals = [r[comp] for r in results]
            between = statistics.pstdev(vals) if len(vals) > 1 else 0.0
            within = [statistics.pstdev(getattr(g, comp) for g in r["records"]) / len(r["records"]) ** 0.5
                      for r in results if len(r["records"]) > 1]
            noise = statistics.fmean(within) if within else 0.0
            return vals, between, noise, statistics.fmean(vals), between / max(noise, 1e-6)

        for comp, field in self.TOP.items():
            vals, between, noise, mean, snr = stats(comp)
            corr = pearson(vals, rewards)
            saturated = abs(mean) > 0.9 and noise < 0.1
            if corr < -0.3:
                factor = 0.0
            elif abs(corr) < 0.2 or saturated or between < self.cfg.auto_weight_min_signal or snr < 0.5:
                factor = 0.2
            else:
                factor = min(1.4, max(1 / 1.4, min(2.0, max(0.5, snr))))
            new = self.base_weights[field] * factor
            setattr(self.cfg, field, round(new, 4))
            report[comp] = {"mean": round(mean, 4), "between": round(between, 4),
                            "noise": round(noise, 4), "snr": round(snr, 2),
                            "corr": round(corr, 2), "saturated": saturated,
                            "factor": round(factor, 2), "weight": round(new, 4)}

        for comp, field in self.INNER.items():
            vals, between, noise, mean, snr = stats(comp)
            saturated = abs(mean) > 0.9 and noise < 0.1
            if saturated or between < self.cfg.auto_weight_min_signal or snr < 0.5:
                factor = 0.2
            else:
                factor = min(2.0, max(0.5, snr))
            new = self.base_weights[field] * factor
            setattr(self.cfg, field, round(new, 4))
            report[comp] = {"mean": round(mean, 4), "between": round(between, 4),
                            "noise": round(noise, 4), "snr": round(snr, 2),
                            "corr": None, "saturated": saturated,
                            "factor": round(factor, 2), "weight": round(new, 4)}

        with open(self.run_dir / "weights.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"gen": self.gen, **report}, ensure_ascii=False) + "\n")

    # -- 验证 -----------------------------------------------------------
    def validate(self) -> None:
        x = self.optimizer.mean
        path = self.params_dir / f"mean_gen{self.gen:04d}.json"
        self.codec.save(x, path)
        if self.cfg.dry_run:
            n = max(1, self.cfg.validation_games)
            wr = max(0.0, min(1.0, 0.5 + (-float(np.linalg.norm(np.asarray(x) - getattr(self.objective, "optimum", x))))))
            lo, hi = wilson_ci(wr * n, n)
            stats = {"games": n, "wins": int(round(wr * n)), "losses": n - int(round(wr * n)),
                     "draws": 0, "win_rate": wr, "wilson": [lo, hi], "per_map": {},
                     "batch_rate_std": 0.0, "mean_ticks": 0.0, "mean_exchange": 0.0, "failures": 0}
        else:
            stats = evaluate_config(path, max(1, self.cfg.validation_games // self.cfg.games_per_batch),
                                    self.cfg.games_per_batch, self.cfg.seed + 999, self.cfg)
        stats.update(gen=self.gen, sigma=self.optimizer.sigma)
        with open(self.run_dir / "validation.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(stats, ensure_ascii=False) + "\n")
        if stats["win_rate"] >= self._best_validation()[0]:
            atomic_json(self.params_dir / "best_val.json", self.codec.decode(x))
        print(f"  验证 gen{self.gen}: 胜率 {stats['win_rate']:.3f} "
              f"[{stats['wilson'][0]:.3f},{stats['wilson'][1]:.3f}] n={stats['games']}")

    def _best_validation(self) -> tuple[float, int]:
        best = (-1.0, -1)
        path = self.run_dir / "validation.jsonl"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                row = read_json_line(line)
                if row.get("win_rate", -1) > best[0]:
                    best = (row["win_rate"], int(row.get("gen", -1)))
        return best

    # -- 保存 -----------------------------------------------------------
    def write_meta(self) -> None:
        atomic_json(self.run_dir / "meta.json", {
            "seed": self.cfg.seed,
            "map_pool": [f"{m.name}@{m.pair[0]}-{m.pair[1]}" for m in load_pool(self.cfg.pool)],
            "params_sha256": sha256_file(Path(self.cfg.params)),
            "game_version": "1.15",
            "cma_version": _cma_version(),
            "git": git_hash(),
            "codec": self.codec.describe(),
            "dry_run": self.cfg.dry_run,
            "started": self.started,
        })

    def save_checkpoint(self, permanent: bool = False) -> None:
        state = {"es": self.optimizer._strategy, "gen": self.gen,
                 "rng": self.rng.getstate(), "total_games": self.total_games,
                 "config": self.cfg.to_json()}
        atomic_pickle(self.ckpt_dir / f"ckpt_gen{self.gen:04d}.pkl", state)
        atomic_pickle(self.ckpt_dir / "latest.pkl", state)
        if permanent:
            atomic_pickle(self.ckpt_dir / f"permanent_gen{self.gen:04d}.pkl", state)
        self.codec.save(self.optimizer.mean, self.params_dir / f"mean_gen{self.gen:04d}.json")
        for old in sorted(self.ckpt_dir.glob("ckpt_gen*.pkl"))[:-self.cfg.keep_checkpoints]:
            old.unlink(missing_ok=True)

    def finalize(self) -> None:
        atomic_json(self.params_dir / "final.json", self.codec.decode(self.optimizer.mean))
        meta = read_json(self.run_dir / "meta.json", {}) or {}
        meta.update(finished=time.time(), generations=self.gen, total_games=self.total_games)
        atomic_json(self.run_dir / "meta.json", meta)
        print(f"训练结束：gen={self.gen} 总对局={self.total_games} "
              f"final -> {self.params_dir / 'final.json'}")
