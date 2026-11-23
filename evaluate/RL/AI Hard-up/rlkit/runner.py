"""运行类：并发跑对局（worker 池 + 重试 + 补抽），产出 `GameRecord`。"""
from __future__ import annotations

from pathlib import Path

import concurrent.futures
import hashlib
import json
import os
import queue
import re
import shutil
import statistics
import subprocess
import time

from .paths import REPO, RUN_ENV
from .util import atomic_json, kill_tree, read_json
from .match import MatchSpec
from .config import TrainConfig
from .scoring import GameRecord, parse_final_board, parse_samples, parse_telemetry, score

# =========================================================================== Runner：跑对局

class Worker:
    """一个常驻槽位：私有参数文件 + 私有对局目录（JVM 仍是一局一启）。"""

    def __init__(self, index: int, root: Path):
        self.index = index
        self.dir = root / f"w{index}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.params_path = self.dir / "ai-params.json"
        self._hash: str | None = None
        self.restarts = 0
        self.games = 0

    def prepare(self, doc: dict) -> Path:
        payload = json.dumps(doc, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if digest != self._hash:
            atomic_json(self.params_path, doc)
            self._hash = digest
        return self.params_path


class Runner:
    """对局执行器：worker 池 + 单局重试 + 备用规格补抽。"""

    def __init__(self, cfg: "TrainConfig", run_dir: Path):
        self.cfg = cfg
        self.opponent_config = None
        if cfg.opponent_config is not None:
            self.opponent_config = Path(cfg.opponent_config).resolve(strict=True)
            if not isinstance(read_json(self.opponent_config), dict):
                raise ValueError(f"Opponent config must contain a JSON object: {self.opponent_config}")
            if cfg.opponent_id != "rwx.ai-rl-hard-2":
                raise ValueError("opponent_config requires opponent_id=rwx.ai-rl-hard-2")
        elif cfg.opponent_id == "rwx.ai-rl-hard-2":
            raise ValueError("rwx.ai-rl-hard-2 requires opponent_config")
        self.workers = [Worker(i, Path(run_dir) / "workers") for i in range(cfg.n_workers)]
        self._free: queue.Queue[Worker] = queue.Queue()
        for worker in self.workers:
            self._free.put(worker)
        self.costs: dict = {}
        if cfg.cost_table and Path(cfg.cost_table).exists():
            self.costs.update({str(k).lower(): float(v) for k, v in (read_json(cfg.cost_table) or {}).items()})

    @property
    def restarts(self) -> int:
        return sum(w.restarts for w in self.workers)

    def _map(self, fn, items: list) -> list:
        results: list = [None] * len(items)

        def task(i: int):
            worker = self._free.get()
            try:
                results[i] = fn(items[i], worker)
            finally:
                self._free.put(worker)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.cfg.n_workers) as pool:
            list(pool.map(task, range(len(items))))
        return results

    def game(self, spec: MatchSpec, params_doc: dict, worker: Worker) -> GameRecord:
        path = worker.prepare(params_doc)
        rec = self._run(spec, path, worker)
        if rec.error:                     # 失败重试 1 次
            rec = self._run(spec, path, worker)
            worker.restarts += 1 if rec.error else 0
        else:
            worker.games += 1
        return rec

    def run_jobs(self, jobs: list) -> list[GameRecord]:
        """一次提交多份 (params_doc, spec)，把 worker 池用满；失败重试 1 次。"""
        def one(job, worker):
            doc, spec = job
            rec = self.game(spec, doc, worker)
            return rec
        return self._map(one, jobs)

    def games(self, params_doc: dict, specs: list[MatchSpec],
              spare: list[MatchSpec] | None = None) -> list[GameRecord]:
        """跑一批；仍失败则用备用规格补抽（最多两轮）。"""
        records = [r for r in self._map(lambda s, w: self.game(s, params_doc, w), specs)
                   if not r.error]
        backup = list(spare or [])
        for _ in range(2):
            missing = len(specs) - len(records)
            if missing <= 0 or not backup:
                break
            take, backup = backup[:missing], backup[missing:]
            records.extend(r for r in self._map(lambda s, w: self.game(s, params_doc, w), take)
                           if not r.error)
        return records

    # -- 启动命令：Windows 走 run-env.ps1，Linux 直接起 java -------------
    @staticmethod
    def _command(env, slots, spec, params_path, game_dir, spec_path):
        if os.name == "nt":
            return ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(RUN_ENV),
                    "-Env", str(spec_path), "-Out", str(game_dir), "-Quiet"]
        repo = Path(os.environ.get("RWX_REPO", str(REPO)))
        java = os.environ.get("RWX_JAVA", "java")
        lib = os.environ.get("RWX_LIB", str(repo / "desktop" / "build" / "headless" / "lib"))
        rollout = {
            "schema": "rwx-rollout-v1", "out": str(game_dir),
            "map": str(repo / spec.matchup.map),
            "teams": [{"slot": s["slot"], "spawn": s["spawn"], "ai": s["ai"], "name": s["name"],
                       **({"side": s["side"]} if s.get("side") is not None else {})}
                      for s in slots],
            "room": {"incomeMultiplier": env["room"]["incomeMultiplier"], "seed": spec.seed},
            "limits": env["limits"], "sampling": env["sampling"],
            "record": False, "winCondition": "commandCenter",
            "telemetry": bool(env.get("telemetry")),
            "aiConfig": str(params_path),
        }
        rollout_path = game_dir / "spec.json"
        if "aiConfig2" in env:
            rollout["aiConfig2"] = env["aiConfig2"]
        rollout_path.write_text(json.dumps(rollout, ensure_ascii=False), encoding="utf-8")
        return [java, "-Xms256m", "-Xmx1536m", "-Dfile.encoding=UTF-8",
                "-Dorg.lwjgl.opengl.contextAPI=native",
                "--enable-native-access=ALL-UNNAMED",
                "--sun-misc-unsafe-memory-access=allow",
                f"-Drwx.repoDir={repo}", f"-Drwx.assetsDir={repo / 'assets'}",
                "-cp", str(Path(lib) / "*"), "io.github.rwx.DesktopMain", "--no-steam",
                f"--rollout-config={rollout_path}", f"--data-dir={game_dir}"]

    # -- 单局：调用 run-env、解析 result / samples --------------------
    def _run(self, spec: MatchSpec, params_path: Path, worker: Worker) -> GameRecord:
        cfg = self.cfg
        rec = GameRecord(map=spec.matchup.name, pair=spec.matchup.pair,
                         candidate_spawn=spec.candidate_spawn, seed=spec.seed,
                         batch=spec.batch, max_ticks=cfg.max_ticks)
        m = spec.matchup
        slug = re.sub(r"[^0-9A-Za-z]+", "-", m.name).strip("-").lower()[:24] or "map"
        game_dir = (Path(cfg.out_dir) / cfg.run_name / "games" /
                    f"w{worker.index}-{slug}-{m.pair[0]}-{m.pair[1]}-s{spec.candidate_spawn}-{spec.seed % 100000}")
        game_dir.mkdir(parents=True, exist_ok=True)

        mine = {"ai": cfg.candidate_id, "spawn": spec.candidate_spawn,
                "name": "candidate", "aiConfig": str(params_path), "side": 0}
        theirs = {"ai": cfg.opponent_id, "spawn": spec.opponent_spawn, "name": "opponent", "side": 1}
        if m.is_team_game:
            # 固定布局（2v2）：slot 顺序即 teams 顺序，同色 = 同盟（引擎按 teamColorId 判敌我）。
            slots = []
            for index, (spawn, role) in enumerate(m.teams):
                team = mine if role == "candidate" else theirs
                slots.append(dict(slot=index, **{**team, "spawn": spawn}))
        else:
            slots = ([dict(slot=0, **mine), dict(slot=1, **theirs)] if spec.candidate_slot == 0
                     else [dict(slot=0, **theirs), dict(slot=1, **mine)])
        env = {
            "schema": "rwx-rl-env-v1", "name": game_dir.name, "map": m.map,
            "out": str(game_dir), "record": False, "telemetry": cfg.telemetry,
            "winCondition": "commandCenter", "seed": spec.seed,
            "room": {"incomeMultiplier": cfg.income},
            "sampling": {"everyTicks": cfg.sample_every_ticks, "includeUnitTypes": True},
            "slots": slots,
            "limits": {"maxTicks": cfg.max_ticks, "maxWallSeconds": int(cfg.match_timeout)},
        }
        spec_path = game_dir / "env.json"
        if self.opponent_config is not None:
            env["aiConfig2"] = str(self.opponent_config)
        spec_path.write_text(json.dumps(env, ensure_ascii=False, indent=1), encoding="utf-8")

        started = time.time()
        command = self._command(env, slots, spec, params_path, game_dir, spec_path)
        proc = subprocess.Popen(
            command, cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace")
        try:
            out, err = proc.communicate(timeout=cfg.match_timeout + 120)
        except subprocess.TimeoutExpired:
            kill_tree(proc.pid)
            worker.restarts += 1
            rec.error = "timeout"
            return rec
        rec.wall_s = time.time() - started

        payload = game_dir / "result.json"
        if (proc.returncode not in (0, 3)) or not payload.exists():
            # rc=3 是 HeadlessRollout 的“非决定性结束”（max-ticks / wall-limit），
            # 对局本身是跑完的，result.json 里 outcome=max-ticks；以前把它当失败丢掉，
            # 会让大地图/水域图的僵持局整批消失（21 图约 10-16%）。
            tail = ((out or "") + (err or "")).strip().splitlines()
            rec.error = (tail[-1] if tail else f"rc={proc.returncode}")[:160]
            worker.restarts += 1
            return rec

        doc = read_json(payload) or {}
        rec.ticks = int(doc.get("ticks") or 0)
        rec.game_ms = float(doc.get("gameMs") or 0.0)
        # 胜负：result.outcome 从“本地队”视角写 victory/defeat，而本地队是 spec.teams 里
        # 第一个队伍（engine.playerTeam），不是 teamId 0——出生点 3/4、5/6 时队伍落在
        # 物理槽 2/3、4/5，teamId 0 根本不存在。候选是第一个队伍当且仅当 candidate_slot==0，
        # 所以这里只能按 candidate_slot 判断，按 candidate_spawn-1==0 会把 [3,4]/[5,6]
        # 的下位出生点整批记反（曾导致 1/3 的局标签翻转）。
        wire = str(doc.get("outcome") or "")
        if wire in ("victory", "defeat"):
            first_team_won = wire == "victory"
            mine_is_first = spec.candidate_slot == 0
            rec.outcome = "win" if (first_team_won == mine_is_first) else "loss"
        else:
            rec.outcome = "draw"

        if cfg.scenario == "hardupv3" and rec.outcome == "draw":
            parse_final_board(doc, rec, slots)
        parse_telemetry(game_dir, rec, cfg, self.costs)
        parse_samples(game_dir, rec, cfg, self.costs)
        score(rec, cfg)
        shutil.rmtree(game_dir, ignore_errors=True)
        return rec


def aggregate(records: list[GameRecord]) -> dict:
    """每批单独求均值，再对批次求平均；batch_std 作为噪声估计。"""
    keys = ("win", "board", "build_prod", "build_def", "army", "bld_value", "econ", "time_score")
    if not records:
        return {"reward": 0.0, "batch_std": 0.0, "valid": 0, **{k: 0.0 for k in keys}}
    batches: dict[int, list[GameRecord]] = {}
    for r in records:
        batches.setdefault(r.batch, []).append(r)
    means = [statistics.fmean(x.reward for x in rows) for rows in batches.values()]
    out = {"reward": statistics.fmean(means),
           "batch_std": statistics.pstdev(means) if len(means) > 1 else 0.0,
           "valid": len(records)}
    for key in keys:
        out[key] = statistics.fmean(getattr(r, key) for r in records)
    return out
