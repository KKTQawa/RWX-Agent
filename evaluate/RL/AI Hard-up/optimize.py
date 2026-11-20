#!/usr/bin/env python3
"""Measurement harness for the configurable RWX AI (`rwx.ai-rl-hard`).

The AI reads one JSON document (`ai.json`).  The knobs worth touching are curated
in `params.json` next to this file: only those are accepted by `--param`, and the
file records the measured effect, noise and the reason each one is (or is not)
worth turning.

Three commands, each usable on its own:

  probe   run one document over a case matrix; shows noise, runtime, seat effects
  screen  one knob at a time, ranked by effect on a cheap truncated proxy match
  duel    equal-income duel: both teams on the configurable AI, definition income
          pinned to 1.0, candidate policy only overlaying one slot

Correctness notes that decide whether a number means anything:

* `result.json.outcome` is slot 0's verdict, so a candidate in slot 1 wins on
  `defeat`.
* The engine gives the AI income multiplier only to teams that are actually AI
  team objects (`PlayerTeam:1246`, `isTeamSpectator`).  Slot 0 is the local player
  team and never gets it, so a naive duel measures a 1.4x vs 1.0x income gap, not
  two AIs.  `duel` pins both definitions to 1.0 and puts the candidate policy in
  the `slots` overlay instead.
* Engine AI randomness is not seeded, so one game is one noisy sample; every
  number printed here carries its sample count.

Usage (repo root, PowerShell 7 for run-env.ps1):
  python "evaluate/RL/AI Hard-up/optimize.py" probe  --ai "evaluate/RL/AI Hard-up/presets/hardup-tuned.json"
  python "evaluate/RL/AI Hard-up/optimize.py" screen --ai "evaluate/RL/AI Hard-up/presets/hardup-takeover.json"
  python "evaluate/RL/AI Hard-up/optimize.py" duel   --ai "evaluate/RL/AI Hard-up/presets/hardup-tuned.json"
"""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import json
import math
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
AI_JSON = Path(__file__).resolve().parent / "ai.json"
RUN_ENV = REPO / "evaluate" / "RL" / "run-env.ps1"
WORK = REPO / "agent-tmp" / "rl-opt"

# --------------------------------------------------------------------------- space

@dataclass(frozen=True)
class Knob:
    """One tunable field of ai.json.

    `fair` marks knobs that change decisions only.  Anything that changes the
    resource flow (income, starting credits, harvest rate) is unfair by the
    definition used here and is never searched.
    """
    path: str
    kind: str            # int | float | bool | order
    lo: float = 0.0
    hi: float = 1.0
    fair: bool = True
    options: tuple = ()
    note: str = ""

    def clamp(self, value):
        if self.kind == "bool":
            return bool(value)
        if self.kind in ("order", "mix"):
            return int(min(max(round(value), 0), len(self.options) - 1))
        if self.kind == "int":
            return int(min(max(round(value), self.lo), self.hi))
        return float(min(max(value, self.lo), self.hi))


# Unit-mix policies.  Names must be real unit types (verified from a live match's
# sample dump); a type a factory cannot build is skipped by the strategy, so a
# mix may name land, mech and air units together.
MIXES: dict[str, dict[str, float]] = {
    "balanced": {"c_tank": 3, "hoverTank": 2, "scout": 1, "c_artillery": 1,
                 "mechGun": 2, "mechMissile": 1, "lightGunship": 1, "c_interceptor": 1},
    "tank": {"c_tank": 6, "hoverTank": 3, "scout": 1},
    "hover": {"hoverTank": 6, "c_tank": 2, "scout": 2},
    "mech": {"mechGun": 4, "mechMissile": 3, "mechArtillery": 1, "c_tank": 1},
    "air": {"lightGunship": 3, "c_interceptor": 2, "c_helicopter": 2, "heavyInterceptor": 1},
    "artillery": {"c_artillery": 4, "scout": 3, "hoverTank": 2, "c_tank": 1},
}

# The search space comes from `params.json` — the curated list of knobs that
# actually moved something.  Entries without a measurable effect stay in that
# file as documentation but are not searched.
PARAMS_FILE = Path(__file__).resolve().parent / "params.json"


def load_knobs(path: Path = PARAMS_FILE) -> dict[str, "Knob"]:
    data = json.loads(path.read_text(encoding="utf-8"))
    knobs: dict[str, Knob] = {}
    for tier, entries in (data.get("tiers") or {}).items():
        if tier == "structural":
            continue
        for entry in entries:
            kind = entry.get("kind")
            if kind not in ("int", "float", "bool", "order", "mix"):
                continue
            rng = entry.get("range") or [0, 1]
            knobs[entry["path"]] = Knob(
                entry["path"], kind,
                float(rng[0]), float(rng[1]),
                bool(entry.get("fair", True)),
                tuple(entry.get("options") or ()),
                entry.get("label", ""),
            )
    return knobs


KNOBS: dict[str, Knob] = {}


WEIGHT_FILE = Path(__file__).resolve().parent / "units.json"

PRIORITIES = {
    "baseline": ["extractorT1", "landFactory", "turret", "antiAirTurret",
                 "fabricator", "extractorT2"],
    "economy-first": ["extractorT1", "extractorT2", "landFactory", "fabricator",
                      "turret", "antiAirTurret"],
    "factory-first": ["landFactory", "extractorT1", "airFactory", "extractorT2",
                      "fabricator", "turret", "antiAirTurret"],
    "defense-first": ["extractorT1", "turret", "landFactory", "antiAirTurret",
                      "extractorT2", "fabricator"],
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def get_param(doc: dict, path: str):
    node = doc
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node


def set_param(doc: dict, path: str, value) -> None:
    parts = path.split(".")
    node = doc
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    leaf = parts[-1]
    current = node.get(leaf)
    if isinstance(current, dict) and "value" in current:
        current["value"] = value
    else:
        node[leaf] = value


def apply_params(doc: dict, params: dict[str, float]) -> dict:
    """Return a copy of `doc` with every knob applied (value wrappers preserved)."""
    out = copy.deepcopy(doc)
    for path, raw in params.items():
        knob = KNOBS.get(path)
        if knob is None:
            raise KeyError(f"unknown knob {path}")
        value = knob.clamp(raw)
        if knob.kind == "order":
            out_priority = PRIORITIES[knob.options[value]]
            set_param(out, "building.priority", list(out_priority))
        elif knob.kind == "mix":
            set_param(out, "units.weights", dict(MIXES[knob.options[value]]))
        else:
            set_param(out, path, value)
    return out


def apply_sets(doc: dict, pairs) -> dict:
    """`--set path=true` style overrides outside the search space (gates, dicts)."""
    out = copy.deepcopy(doc)
    for item in pairs or []:
        path, _, raw = item.partition("=")
        path = path.strip()
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw.strip()
        set_param(out, path, value)
    return out


# --------------------------------------------------------------------------- cases

@dataclass(frozen=True)
class Case:
    map: str
    seed: int
    slot: int
    versus: str
    income: float = 2.0
    rep: int = 0
    max_ticks: int = 216000
    fog: int = 2
    ai_config: str = ""

    @property
    def key(self) -> str:
        return (f"{self.map}|{self.seed}|{self.slot}|{self.versus}|{self.income}"
                f"|{self.rep}|{self.max_ticks}|{self.fog}|{self.ai_config}")


DEFAULT_MAPS = ("Lake (2p)", "Two cold sides (2p)", "Small_Island (2p)")
DEFAULT_SEEDS = (1331, 2026)


def build_cases(maps, seeds, versus, income, seatings=(0, 1), reps: int = 1,
                max_ticks: int = 216000, fog: int = 2) -> list[Case]:
    return [Case(m, s, slot, versus, income, rep, max_ticks, fog)
            for rep in range(reps) for m in maps for s in seeds for slot in seatings]


# --------------------------------------------------------------------------- runner

@dataclass
class Match:
    case: Case
    outcome: str = "error"
    decisive: bool = False
    ticks: int = 0
    wall_ms: int = 0
    units: tuple = (0, 0)
    credits: tuple = (0.0, 0.0)
    last: dict = field(default_factory=dict)   # final samples.jsonl row, when sampling is on
    error: str = ""

    @property
    def candidate_won(self) -> bool:
        # outcome is slot 0's verdict
        return (self.outcome == "win") if self.case.slot == 0 else (self.outcome == "defeat")

    @property
    def candidate_alive(self) -> int:
        return self.units[self.case.slot]

    @property
    def enemy_alive(self) -> int:
        return self.units[1 - self.case.slot]

    def _team_sample(self, idx: int) -> dict:
        return (self.last.get("teams") or {}).get(str(idx)) or {}

    @property
    def own_hp(self) -> float:
        return float(self._team_sample(self.case.slot).get("hp") or 0.0)

    @property
    def enemy_hp(self) -> float:
        return float(self._team_sample(1 - self.case.slot).get("hp") or 0.0)

    @property
    def own_buildings(self) -> int:
        return int(self._team_sample(self.case.slot).get("buildings") or 0)

    @property
    def enemy_buildings(self) -> int:
        return int(self._team_sample(1 - self.case.slot).get("buildings") or 0)


class Runner:
    def __init__(self, workers: int = 12, ai_config: Path = AI_JSON,
                 sampling_ticks: int = 0, keep: bool = False,
                 candidate: str = "rwx.ai-rl-hard"):
        self.workers = workers
        self.ai_config = ai_config
        self.candidate = candidate
        self.sampling_ticks = sampling_ticks
        self.keep = keep
        self.run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=str(WORK)))
        self._cache: dict[str, Match] = {}
        WORK.mkdir(parents=True, exist_ok=True)

    # -- one match ---------------------------------------------------------
    def _one(self, spec_path: Path, case: Case) -> Match:
        out = spec_path.parent / "out"
        env = {
            "schema": "rwx-rl-env-v1",
            "map": case.map,
            "seed": case.seed,
            "record": False,
            "telemetry": False,
            "winCondition": "commandCenter",
            "room": {
                "incomeMultiplier": case.income,
                "startingCredits": 0,
                "fogMode": case.fog,
                "revealedMap": False,
                "startingUnits": 1,
                "noNukes": False,
                "aiDifficulty": 1,
            },
            "slots": [
                {"slot": case.slot, "ai": self.candidate,
                 **({"aiConfig": str(self.ai_config)} if self.ai_config else {})},
                {"slot": 1 - case.slot, "ai": case.versus},
            ],
            "limits": {"maxTicks": case.max_ticks, "maxWallSeconds": 300},
        }
        if self.sampling_ticks:
            env["sampling"] = {"everyTicks": self.sampling_ticks, "includeUnitTypes": True}
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        config_path = Path(case.ai_config) if case.ai_config else self.ai_config
        if config_path is not None:
            env["slots"][0]["aiConfig"] = str(config_path)
        else:
            env["slots"][0].pop("aiConfig", None)
        write_json(spec_path, env)
        started = time.time()
        cmd = ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(RUN_ENV),
               "-Env", str(spec_path), "-Out", str(out), "-Quiet"]
        try:
            proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True,
                                  timeout=900)
        except subprocess.TimeoutExpired:
            return Match(case=case, error="timeout")
        elapsed = int((time.time() - started) * 1000)
        result_path = out / "result.json"
        if proc.returncode != 0 or not result_path.exists():
            tail = (proc.stdout or "")[-400:] + (proc.stderr or "")[-400:]
            return Match(case=case, wall_ms=elapsed, error=f"rc={proc.returncode} {tail}")
        r = read_json(result_path)
        teams = r.get("teams") or []
        units = [0, 0]
        credits = [0.0, 0.0]
        for t in teams:
            idx = t.get("teamId")
            if idx in (0, 1):
                units[idx] = int(t.get("units") or 0)
                credits[idx] = float(t.get("credits") or 0.0)
        last: dict = {}
        samples_path = out / "samples.jsonl"
        if samples_path.exists():
            try:
                with samples_path.open(encoding="utf-8") as handle:
                    for line in handle:
                        if line.strip():
                            last = json.loads(line)
            except (OSError, ValueError):
                last = {}
        return Match(case=case, outcome=r.get("outcome", "error"),
                     decisive=bool(r.get("decisive")), ticks=int(r.get("ticks") or 0),
                     wall_ms=elapsed, units=tuple(units), credits=tuple(credits),
                     last=last)

    # -- a batch -----------------------------------------------------------
    def run(self, cases: list[Case], tag: str = "batch") -> list[Match]:
        todo = [c for c in cases if c.key not in self._cache]
        results: list[Match] = []
        if todo:
            group = self.run_dir / tag
            group.mkdir(parents=True, exist_ok=True)
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
                futures = {}
                for index, case in enumerate(todo):
                    spec = group / f"{index:03d}-{case.slot}" / "env.json"
                    spec.parent.mkdir(parents=True, exist_ok=True)
                    futures[pool.submit(self._one, spec, case)] = case
                for fut in concurrent.futures.as_completed(futures):
                    match = fut.result()
                    self._cache[match.case.key] = match
                    results.append(match)
        for case in cases:
            cached = self._cache.get(case.key)
            if cached is not None and cached not in results:
                results.append(cached)
        return results

    def clear_cache(self) -> None:
        """A new AI document means the old results no longer describe the candidate."""
        self._cache.clear()

    def cleanup(self) -> None:
        if not self.keep and self.run_dir.exists():
            shutil.rmtree(self.run_dir, ignore_errors=True)


# --------------------------------------------------------------------------- scoring

@dataclass
class Score:
    games: int = 0
    decisive: int = 0
    wins: int = 0
    draws: int = 0
    errors: int = 0
    ticks: float = 0.0
    wall_s: float = 0.0
    margin: float = 0.0          # (own - enemy units) / (own + enemy + 1)
    hp_margin: float = 0.0       # same shape, but on total HP from the last sample
    bldg_margin: float = 0.0     # buildings differential
    pairs: int = 0               # (map, seed) groups played in both seatings
    sweeps: int = 0              # +1 both seatings won, 0 split, -1 none
    by_map: dict = field(default_factory=dict)

    @property
    def win_rate(self) -> float:
        return self.wins / self.decisive if self.decisive else 0.0

    @property
    def sweep_rate(self) -> float:
        return self.sweeps / self.pairs if self.pairs else 0.0


def summarise(matches: list[Match]) -> Score:
    score = Score(games=len(matches))
    ticks: list[float] = []
    margins: list[float] = []
    hp_margins: list[float] = []
    bldg_margins: list[float] = []
    per_map: dict[str, list[int]] = {}
    pairs: dict[tuple, list[tuple[int, bool]]] = {}
    for m in matches:
        if m.error:
            score.errors += 1
            continue
        won = 1 if (m.decisive and m.candidate_won) else 0
        if m.decisive:
            score.decisive += 1
            score.wins += won
        else:
            score.draws += 1
        ticks.append(m.ticks)
        margins.append((m.candidate_alive - m.enemy_alive) /
                       (m.candidate_alive + m.enemy_alive + 1))
        per_map.setdefault(m.case.map, []).append(won)
        if m.last:
            hp_margins.append((m.own_hp - m.enemy_hp) / (m.own_hp + m.enemy_hp + 1.0))
            bldg_margins.append((m.own_buildings - m.enemy_buildings) /
                                (m.own_buildings + m.enemy_buildings + 1.0))
        pairs.setdefault((m.case.map, m.case.seed, m.case.rep), []).append((won, m.decisive))
        score.wall_s += m.wall_ms / 1000.0
    score.ticks = statistics.fmean(ticks) if ticks else 0.0
    score.margin = statistics.fmean(margins) if margins else 0.0
    score.hp_margin = statistics.fmean(hp_margins) if hp_margins else 0.0
    score.bldg_margin = statistics.fmean(bldg_margins) if bldg_margins else 0.0
    score.by_map = {k: (sum(v), len(v)) for k, v in per_map.items()}
    for games in pairs.values():
        if len(games) != 2 or not all(decisive for _, decisive in games):
            continue
        score.pairs += 1
        total = sum(won for won, _ in games)
        if total == 2:
            score.sweeps += 1
        elif total == 0:
            score.sweeps -= 1
    return score


def fmt_score(s: Score) -> str:
    parts = [f"{s.wins}/{s.games - s.errors} 胜",
             f"胜率 {s.win_rate:.2f}"]
    if s.pairs:
        parts.append(f"成对净胜 {s.sweeps:+d}/{s.pairs}")
    parts += [f"兵力差 {s.margin:+.2f}"]
    if s.hp_margin:
        parts.append(f"HP差 {s.hp_margin:+.2f}")
    if s.bldg_margin:
        parts.append(f"建筑差 {s.bldg_margin:+.2f}")
    parts.append(f"平均 {s.ticks/1000:.0f}k tick")
    if s.draws:
        parts.append(f"{s.draws} 平/未决")
    if s.errors:
        parts.append(f"{s.errors} 失败")
    return " | ".join(parts)


# --------------------------------------------------------------------------- commands

def cmd_probe(args) -> int:
    doc = apply_sets(read_json(Path(args.ai)), args.sets)
    params = reduce_config(args.param)
    doc = apply_params(doc, params) if params else doc
    ai_path = None if args.candidate == "rwx.original.hard" else Path(args.ai)
    runner = Runner(workers=args.workers, ai_config=ai_path,
                    sampling_ticks=args.sampling, keep=args.keep,
                    candidate=args.candidate)
    maps = args.maps.split(",") if args.maps else list(DEFAULT_MAPS)
    seeds = [int(x) for x in args.seeds.split(",")] if args.seeds else list(DEFAULT_SEEDS)
    cases = build_cases(maps, seeds, args.versus, args.income, reps=args.repeats,
                        max_ticks=args.max_ticks, fog=args.fog)
    print(f"探针：{len(cases)} 局，{args.workers} 并发，对阵 {args.versus}，地图 {','.join(maps)}，"
          f"种子 {','.join(map(str, seeds))}，收入 x{args.income}，每例重复 {args.repeats}")
    started = time.time()
    try:
        matches = runner.run(cases, tag="probe")
    finally:
        runner.cleanup()
    wall = time.time() - started
    matches.sort(key=lambda m: (m.case.map, m.case.seed, m.case.rep, m.case.slot))
    for m in matches:
        flag = "胜" if m.candidate_won else ("负" if m.decisive else "?")
        who = "槽0" if m.case.slot == 0 else "槽1"
        print(f"  {m.case.map:<22} seed={m.case.seed:<5} r{m.case.rep} {who}  {flag}  "
              f"{m.ticks/1000:6.1f}k tick  {m.wall_ms/1000:5.1f}s  "
              f"兵力 {m.units[0]}v{m.units[1]} 资金 {m.credits[0]:.0f}v{m.credits[1]:.0f}"
              + (f"  HP {m.own_hp:.0f}/{m.enemy_hp:.0f} 建筑 {m.own_buildings}v{m.enemy_buildings}"
                 if m.last else "")
              + (f"  ERR {m.error}" if m.error else ""))
    if args.dump_units:
        for label, pick in (("候选方", lambda m: m.case.slot),
                            ("对手", lambda m: 1 - m.case.slot)):
            seen: dict[str, int] = {}
            for m in matches:
                types = (m._team_sample(pick(m)).get("types") or {})
                for name, count in types.items():
                    seen[name] = max(seen.get(name, 0), int(count))
            print(f"\n{label}末次采样的兵种（峰值计数）：")
            for name in sorted(seen, key=str.lower):
                print(f"  {name:<28} {seen[name]}")
    score = summarise(matches)
    print(f"\n汇总：{fmt_score(score)}")
    print(f"墙钟：{wall:.1f}s（{len(cases)} 局 / {args.workers} 并发 = {wall/max(1,len(cases)):.1f}s 每局摊薄）")
    for name, (wins, total) in score.by_map.items():
        print(f"  {name:<22} {wins}/{total}")
    if args.repeats > 1:
        agree = 0
        total = 0
        for key in sorted({(m.case.map, m.case.seed, m.case.slot) for m in matches}):
            group = [m for m in matches if (m.case.map, m.case.seed, m.case.slot) == key]
            won = {m.candidate_won for m in group if not m.error}
            total += 1
            agree += 1 if len(won) == 1 else 0
        print(f"重复一致性：{agree}/{total} 个 (地图,seed,座位) 的重复结果相同"
              f"（不一致=引擎 AI 随机性带来的噪声）")
    return 0


def reduce_config(pairs) -> dict[str, float]:
    """--param building.bankCredits=800 ... -> {path: value}"""
    params = {}
    for item in pairs or []:
        path, _, value = item.partition("=")
        path = path.strip()
        if path not in KNOBS:
            raise SystemExit(f"未知参数 {path}")
        knob = KNOBS[path]
        text = value.strip()
        if knob.kind == "bool":
            params[path] = text.lower() in ("1", "true", "yes")
        elif knob.kind in ("order", "mix"):
            if text in knob.options:
                params[path] = knob.options.index(text)
            else:
                params[path] = float(text)
        else:
            params[path] = float(text)
    return params


def cmd_screen(args) -> int:
    """One knob at a time, both directions, paired seatings."""
    base_doc = apply_sets(read_json(Path(args.ai)), args.sets)
    baseline_params = reduce_config(args.param)
    knobs = [KNOBS[p] for p in (args.only.split(",") if args.only else KNOBS)]
    seeds = [int(x) for x in args.seeds.split(",")] if args.seeds else [2026]
    maps = args.maps.split(",") if args.maps else ["Lake (2p)", "Two cold sides (2p)"]
    repeats = args.repeats
    ai_path = None if args.candidate == "rwx.original.hard" else Path(args.ai)
    runner = Runner(workers=args.workers, ai_config=ai_path,
                    sampling_ticks=args.sampling, keep=args.keep,
                    candidate=args.candidate)

    def evaluate(params: dict, tag: str) -> Score:
        doc = apply_params(base_doc, {**baseline_params, **params})
        write_json(Path(args.ai), doc) if args.inplace else None
        if not args.inplace:
            # each variant needs its own file; the AI reads exactly one per process
            variant = runner.run_dir / "ai" / f"{tag}.json"
            write_json(variant, doc)
            runner.ai_config = variant
        runner.clear_cache()
        cases = build_cases(maps, seeds, args.versus, args.income, reps=repeats,
                            max_ticks=args.max_ticks, fog=args.fog)
        matches = runner.run(cases, tag=tag)
        return summarise(matches)

    try:
        print(f"基线（{args.versus}，{len(maps)} 图 x {len(seeds)} 种子 x 2 座位 x {repeats} 次）")
        base = evaluate(baseline_params, "baseline")
        print(f"  {fmt_score(base)}\n")
        rows = []
        for knob in knobs:
            if knob.kind == "mix":
                current = 0
            else:
                current = get_param(apply_params(base_doc, baseline_params), knob.path)
            if knob.kind == "mix":
                candidates = list(range(1, len(knob.options)))
                names = {i: knob.options[i] for i in candidates}
            elif knob.kind == "order":
                candidates = [0, len(knob.options) - 1]
                names = {0: knob.options[0], len(knob.options) - 1: knob.options[-1]}
            elif knob.kind == "bool":
                candidates = [not bool(current)]
                names = {candidates[0]: str(candidates[0])}
            else:
                lo = current - (current - knob.lo) * 0.5
                hi = current + (knob.hi - current) * 0.5
                candidates = [knob.clamp(lo), knob.clamp(hi)]
                names = {candidates[0]: f"{candidates[0]:g}", candidates[1]: f"{candidates[1]:g}"}
            for value in candidates:
                if knob.kind == "int" and abs(value - float(current)) < 1e-9:
                    continue
                if knob.kind == "float" and abs(value - float(current)) < 1e-9:
                    continue
                score = evaluate({knob.path: value}, f"{knob.path.replace('.','_')}_{value}")
                rows.append((knob.path, names.get(value, value), score))
                print(f"  {knob.path:<38} -> {names.get(value, value):<16} {fmt_score(score)}")
        # rank by delta against baseline (win rate, then margin)
        ranked = sorted(rows, key=lambda r: (-(r[2].win_rate - base.win_rate),
                                             -(r[2].margin - base.margin)))
        print("\n按效果排序（胜率差 / 兵力差）：")
        for path, value, score in ranked[:args.top]:
            print(f"  {path:<38} {str(value):<16} "
                  f"Δ胜率 {score.win_rate - base.win_rate:+.2f}  "
                  f"Δ兵力 {score.margin - base.margin:+.3f}")
        return 0
    finally:
        runner.cleanup()




# --------------------------------------------------------------------------- duel

POLICY_SECTIONS = ("overrides", "building", "units", "upgrades", "tactics", "economy")


def duel_document(policy: dict, slot: int | None, definition: dict | None = None) -> dict:
    """One process, both teams on the configurable AI, equal income.

    Slot 0 is the local player, and the engine ignores the AI income multiplier for
    that team (`PlayerTeam.b`: only AI teams get `AiRegistry.incomeMultiplier`).
    Pinning the definition to 1.0 therefore makes both sides earn exactly the room
    multiplier, which is the only way a duel measures decisions instead of income.
    """
    document = {
        "schema": "rwx-rl-ai-v1",
        "meta": {
            "name": "duel",
            "id": "rwx.ai-rl-hard",
            "base": "rwx.original.hard",
            "baseDifficulty": 1,
            "strategyVersion": "rwx.ai-rl-hard.v1",
        },
        "definition": _duel_definition(definition),
        "slots": {},
    }
    if slot is not None:
        document["slots"][str(slot)] = {key: policy[key] for key in POLICY_SECTIONS if key in policy}
    return document


def _duel_definition(override: dict | None) -> dict:
    """Equal-income default, but an explicit definition in the document wins."""
    definition = copy.deepcopy(override or {})
    definition.setdefault("incomeMultiplier", 1.0)
    definition.setdefault("extendsOriginal", True)
    definition.setdefault("originalPhases", {
        "initialization": True,
        "economy": True,
        "tactics": True,
        "strategy": True,
    })
    definition.setdefault("cadence", {"economy": 25, "tactics": 80, "strategy": 250})
    return definition


def cmd_duel(args) -> int:
    tuned = apply_params(apply_sets(read_json(Path(args.ai)), args.sets), reduce_config(args.param))
    policy = {key: tuned[key] for key in POLICY_SECTIONS if key in tuned}
    maps = args.maps.split(",") if args.maps else ["Lake (2p)", "Small Island (2p)"]
    seeds = [int(x) for x in args.seeds.split(",")] if args.seeds else [2026]
    runner = Runner(workers=args.workers, ai_config=None, sampling_ticks=args.sampling,
                    keep=args.keep, candidate="rwx.ai-rl-hard")
    try:
        slot0_file = runner.run_dir / "ai" / "duel-candidate-slot0.json"
        slot1_file = runner.run_dir / "ai" / "duel-candidate-slot1.json"
        definition = tuned.get("definition")
        write_json(slot0_file, duel_document(policy, 0, definition))
        write_json(slot1_file, duel_document(policy, 1, definition))
        cases = []
        for rep in range(args.repeats):
            for map_name in maps:
                for seed in seeds:
                    cases.append(Case(map_name, seed, 0, "rwx.ai-rl-hard", args.income, rep,
                                      args.max_ticks, args.fog, str(slot0_file)))
                    cases.append(Case(map_name, seed, 1, "rwx.ai-rl-hard", args.income, rep,
                                      args.max_ticks, args.fog, str(slot1_file)))
        print(f"同收入对决：{len(cases)} 局，{args.workers} 并发，上限 {args.max_ticks} tick，"
              f"采样 {args.sampling or '关'}；两边定义收入都锁 1.0，槽位差异只剩出生位")
        started = time.time()
        matches = runner.run(cases, tag="duel")
        wall = time.time() - started
        matches.sort(key=lambda m: (m.case.map, m.case.seed, m.case.rep, m.case.slot))
        for m in matches:
            flag = "胜" if m.candidate_won else ("负" if m.decisive else "未决")
            print(f"  {m.case.map:<22} seed={m.case.seed:<5} r{m.case.rep} 候选槽{m.case.slot} "
                  f"{flag} {m.ticks/1000:5.1f}k 兵力 {m.units[0]}v{m.units[1]}"
                  f" 资金 {m.credits[0]:.0f}v{m.credits[1]:.0f}"
                  + (f" HP {m.own_hp:.0f}/{m.enemy_hp:.0f}" if m.last else ""))
        if args.dump_units:
            for label, pick in (("候选方", lambda m: m.case.slot),
                                ("对手", lambda m: 1 - m.case.slot)):
                seen: dict[str, int] = {}
                for m in matches:
                    for name, count in (m._team_sample(pick(m)).get("types") or {}).items():
                        seen[name] = max(seen.get(name, 0), int(count))
                print(f"\n{label}兵种：{', '.join(f'{k}x{v}' for k, v in sorted(seen.items()))}")
        score = summarise(matches)
        print(f"\n汇总：{fmt_score(score)}")
        # per-seat means: a real improvement must show in both seatings
        for slot in (0, 1):
            group = [m for m in matches if m.case.slot == slot and not m.error]
            if not group:
                continue
            margins = [(m.candidate_alive - m.enemy_alive) / (m.candidate_alive + m.enemy_alive + 1)
                       for m in group]
            hp = [(m.own_hp - m.enemy_hp) / (m.own_hp + m.enemy_hp + 1.0) for m in group if m.last]
            print(f"  槽{slot}：n={len(group)} 兵力差 {statistics.fmean(margins):+.3f}"
                  + (f" HP差 {statistics.fmean(hp):+.3f}" if hp else ""))
        pairs = {}
        for m in matches:
            if m.error:
                continue
            key = (m.case.map, m.case.seed, m.case.rep)
            pairs.setdefault(key, {})[m.case.slot] = (
                (m.candidate_alive - m.enemy_alive) / (m.candidate_alive + m.enemy_alive + 1))
        spread = [v[0] - v[1] for v in pairs.values() if 0 in v and 1 in v]
        if spread:
            print(f"  成对（槽0差 - 槽1差）：均值 {statistics.fmean(spread):+.3f}，"
                  f"n={len(spread)}；槽0 优于槽1 的样本 {sum(1 for d in spread if d > 0)}/{len(spread)}")
        print(f"墙钟：{wall:.1f}s（{wall/max(1, len(cases)):.1f}s 每局摊薄）")
        return 0
    finally:
        runner.cleanup()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--ai", default=str(AI_JSON), help="ai.json 变体")
        p.add_argument("--versus", default="rwx.original.hard", help="对手 AI 注册表 id")
        p.add_argument("--maps", default="", help="逗号分隔的地图名片段")
        p.add_argument("--seeds", default="", help="逗号分隔的 seed")
        p.add_argument("--income", type=float, default=2.0, help="房间收入倍率（双方相同）")
        p.add_argument("--fog", type=int, default=2, help="房间 fogMode（0=无雾 1=已探明 2=战争迷雾）")
        p.add_argument("--workers", type=int, default=12)
        p.add_argument("--candidate", default="rwx.ai-rl-hard",
                       help="候选方 AI id；用 rwx.original.hard 可跑原版对原版的控制组")
        p.add_argument("--param", action="append", help="key=value 覆盖，可重复")
        p.add_argument("--set", action="append", dest="sets", metavar="PATH=VALUE",
                       help="任意 JSON 字段覆盖（如 overrides.tactics=true），不进搜索空间")
        p.add_argument("--max-ticks", type=int, default=216000,
                       help="截断上限；小于 216000 时是代理对局，不是完整对局")
        p.add_argument("--sampling", type=int, default=0,
                       help="按该 tick 间隔采样（>0 时 result 里带 HP/建筑/兵种明细）")
        p.add_argument("--keep", action="store_true", help="保留临时目录")
        p.add_argument("--inplace", action="store_true", help="直接改写 --ai 文件")

    p = sub.add_parser("probe", help="跑一个配置的成对样本，看噪声与耗时")
    common(p)
    p.add_argument("--repeats", type=int, default=1, help="每个 (地图,seed,座位) 重复次数")
    p.add_argument("--dump-units", action="store_true", help="打印末次采样的兵种名")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("screen", help="单参数扫描，排出真正有效果的旋钮")
    common(p)
    p.add_argument("--only", default="", help="逗号分隔的参数路径；默认全部")
    p.add_argument("--repeats", type=int, default=1, help="每个 case 重复次数")
    p.add_argument("--top", type=int, default=15)
    p.set_defaults(func=cmd_screen)

    p = sub.add_parser("duel", help="同收入双槽对决：只比策略，不比收入")
    common(p)
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--dump-units", action="store_true", help="打印双方末次采样的兵种")
    p.set_defaults(func=cmd_duel)

    args = parser.parse_args(argv)
    WORK.mkdir(parents=True, exist_ok=True)
    global KNOBS
    KNOBS = load_knobs()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
