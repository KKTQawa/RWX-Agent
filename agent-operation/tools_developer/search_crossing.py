"""Run the staged Crossing 1v1 search from a completed v3 checkpoint."""

import argparse
from collections import Counter
import copy
from dataclasses import replace
import json
from itertools import combinations
from pathlib import Path
import random
import statistics
from threading import Lock
import time

import numpy as np

from rlkit.config import TrainConfig
from rlkit.match import MatchSpec, load_pool
from rlkit.params import ParamCodec
from rlkit.runner import Runner
from rlkit.scoring import GameRecord
from rlkit.util import atomic_json


SEED = 2026112501
REFERENCE_IDS = ("gen345", "gen148", "gen115")
STAGES = {"screen": (0, 10), "rescreen": (10, 30), "refine": (40, 20),
          "final": (60, 120), "extra": (180, 120), "smoke": (300, 1)}
TOTAL_GAMES = 3160


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class SearchRunner(Runner):
    def __init__(self, cfg, out):
        super().__init__(cfg, out / "runtime")
        self.out = out
        self.lock = Lock()

    def _command(self, env, slots, spec, params_path, game_dir, spec_path):
        command = super()._command(env, slots, spec, params_path, game_dir, spec_path)
        return [command[0], "-XX:ActiveProcessorCount=1", *command[1:]]

    def game(self, spec, params_doc, worker):
        path = self.cache / f"{spec.batch:06d}.json"
        if path.exists():
            return GameRecord(**read(path))
        # Keep rollout evidence distinct even when models share seed and spawn.
        scoped_worker = copy.copy(worker)
        scoped_worker.index = f"{worker.index}-{self.cache.name}-{spec.batch}"
        record = super().game(spec, params_doc, scoped_worker)
        worker._hash = scoped_worker._hash
        if not record.error and record.outcome in {"win", "draw", "loss"}:
            atomic_json(path, record.to_json())
            with self.lock:
                self.completed += 1
                if self.completed % 20 == 0 or self.completed == self.target:
                    self.progress()
        return record

    def progress(self):
        atomic_json(self.out / "status.json", {
            "stage": self.cache.name, "completed": self.offset + self.completed,
            "stage_completed": self.completed, "stage_total": self.target,
            "planned_total": self.planned_total, "workers": self.cfg.n_workers,
            "updated_at": time.time(),
        })

    def evaluate(self, stage, model_ids, docs, matchup, seeds, offset):
        specs = [MatchSpec(matchup, spawn, seed, 0, candidate_slot=slot)
                 for seed in seeds for slot, spawn in enumerate(matchup.pair)]
        total = {"smoke": 6, "extra": TOTAL_GAMES + 480}.get(stage, TOTAL_GAMES)
        return self.evaluate_specs(stage, model_ids, docs, specs, offset, total)

    def evaluate_specs(self, stage, model_ids, docs, specs, offset, total):
        self.cache = self.out / "records" / stage
        self.cache.mkdir(parents=True, exist_ok=True)
        layouts = [{"map": spec.matchup.name, "path": spec.matchup.map,
                    "pair": list(spec.matchup.pair), "teams": [list(team) for team in spec.matchup.teams or ()],
                    "seed": spec.seed, "spawn": spec.candidate_spawn, "slot": spec.candidate_slot}
                   for spec in specs]
        manifest = {"models": model_ids, "layouts": layouts}
        path = self.cache / "manifest.json"
        if path.exists():
            previous = read(path)
            legacy = {"models": model_ids, "seeds": list(dict.fromkeys(s.seed for s in specs)),
                      "spawns": list(specs[0].matchup.pair)}
            if previous != manifest and (
                    len({s.matchup for s in specs}) != 1 or previous != legacy):
                raise RuntimeError(f"Resume manifest differs for {stage}")
        else:
            atomic_json(path, manifest)
        jobs = [(docs[model], replace(spec, batch=index))
                for index, (model, spec) in enumerate((model, spec) for model in model_ids for spec in specs)]
        self.target = len(jobs)
        self.offset = offset
        self.completed = sum((self.cache / f"{i:06d}.json").is_file() for i in range(self.target))
        self.planned_total = total
        self.progress()
        started = time.monotonic()
        records = self.run_jobs(jobs)
        for record, (_, spec) in zip(records, jobs, strict=True):
            if (record.error or record.outcome not in {"win", "draw", "loss"}
                    or (record.map, tuple(record.pair), record.seed, record.candidate_spawn, record.batch)
                    != (spec.matchup.name, spec.matchup.pair, spec.seed, spec.candidate_spawn, spec.batch)):
                atomic_json(self.out / f"failure-{stage}.json", record.to_json())
                raise RuntimeError(f"{stage} has an invalid result for job {spec.batch}")
        results = {model: records[i * len(specs):(i + 1) * len(specs)]
                   for i, model in enumerate(model_ids)}
        atomic_json(self.out / f"{stage}.json", {model: summarize(rows) for model, rows in results.items()})
        print(f"{stage}: {self.target} games, {time.monotonic() - started:.1f}s", flush=True)
        return results


def summarize(rows):
    count = Counter(row.outcome for row in rows)
    return {"wins": count["win"], "draws": count["draw"], "losses": count["loss"],
            "games": len(rows), "win_rate": count["win"] / len(rows),
            "reward": statistics.fmean(row.reward for row in rows),
            "by_spawn": {spawn: dict(Counter(r.outcome for r in rows if r.candidate_spawn == spawn))
                         for spawn in sorted({r.candidate_spawn for r in rows})}}


def parameter_groups(codec):
    groups = {name: [] for name in ("economy", "buildings", "units", "tactics")}
    for i, knob in enumerate(codec.knobs):
        root, *tail = knob.path
        if root == "upgrades" or tail == ["cadence", "economy"] or any("extractor" in key.lower() for key in tail):
            group = "economy"
        elif root in {"building", "buildingScore"}:
            group = "buildings"
        elif root == "units":
            group = "units"
        else:
            group = "tactics"
        groups[group].append(i)
    groups["units"].extend(range(len(codec.knobs), codec.dim))
    return {name: np.asarray(indices) for name, indices in groups.items()}


class ModelPool:
    def __init__(self, codec, vectors):
        self.codec = codec
        self.vectors = {name: np.asarray(vector) for name, vector in vectors.items()}
        self.docs = {name: codec.decode(vector) for name, vector in self.vectors.items()}
        self.groups = parameter_groups(codec)
        self.low, self.high = codec.bounds()
        self.rng = np.random.default_rng(SEED)
        self.seen = {self.signature(doc) for doc in self.docs.values()}

    @staticmethod
    def signature(doc):
        return json.dumps(doc, sort_keys=True)

    def mutate(self, name, parent, group, scale):
        dims = self.groups[group]
        for _ in range(200):
            active = self.rng.choice(dims, size=min(6, len(dims)), replace=False)
            vector = self.vectors[parent].copy()
            step = np.maximum(1.0, scale * (self.high[active] - self.low[active]))
            step[active >= len(self.codec.knobs)] = (
                scale * (self.high[active] - self.low[active]))[active >= len(self.codec.knobs)]
            vector[active] += self.rng.choice([-1, 1], size=len(active)) * step
            vector = np.clip(vector, self.low, self.high)
            doc = self.codec.decode(vector)
            signature = self.signature(doc)
            if signature not in self.seen:
                self.seen.add(signature)
                self.vectors[name] = vector
                self.docs[name] = doc
                return name
        raise RuntimeError(f"No distinct mutation for {parent}/{group}")


def rank(results):
    stats = {model: summarize(rows) for model, rows in results.items()}
    return sorted(stats, key=lambda model: (-stats[model]["win_rate"], -stats[model]["reward"], model))


def paired_comparisons(results, incumbent):
    samples = {}
    for model, rows in results.items():
        by_seed = {}
        for row in rows:
            by_seed.setdefault(row.seed, {})[row.candidate_spawn] = row.outcome == "win"
        samples[model] = {seed: statistics.mean(spawns.values()) for seed, spawns in by_seed.items()}
    # Up to three challengers, each with up to two looks at the data.
    alpha = 0.05 / 6
    comparisons = {}
    for a, b in combinations(results, 2):
        if incumbent not in (a, b) and "gen115" not in (a, b):
            continue
        if incumbent in (a, b):
            model, base = (b, a) if a == incumbent else (a, b)
        else:
            model, base = (b, a) if a == "gen115" else (a, b)
        delta = np.array([value - samples[base][seed] for seed, value in samples[model].items()])
        rng = np.random.default_rng(SEED)
        boot = rng.choice(delta, size=(20000, len(delta)), replace=True).mean(axis=1)
        comparisons[f"{model}:{base}"] = {"difference": float(delta.mean()),
            "ci95": np.quantile(boot, [0.025, 0.975]).tolist(),
            "selection_lower": float(np.quantile(boot, alpha))}
    return comparisons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    source, out = args.source.resolve(), args.out.resolve()
    cfg = TrainConfig.load(Path("runs/hardupv3-magma-vh/config.json"))
    cfg.out_dir, cfg.run_name, cfg.n_workers = out.parent, out.name, args.workers
    matchup, = load_pool(source / "pool.json")
    if matchup.pair != (1, 2) or cfg.opponent_id != "rwx.original.very-hard" or cfg.income != 2.0:
        raise RuntimeError("Unexpected Crossing evaluation settings")
    codec = ParamCodec(cfg.params, frozen_units=cfg.frozen_units)
    vectors = {name: read(source / "checkpoints" / f"gen-{generation:04d}.json")["x"]
               for name, generation in (("gen345", 350), ("gen148", 150))}
    vectors["gen115"] = read(source / "start_x.json")
    if (read(source / "checkpoints/gen-0350.json")["champion_from"] != 345
            or read(source / "checkpoints/gen-0150.json")["champion_from"] != 148
            or codec.decode(vectors["gen115"]) != read(source / "start.json")):
        raise RuntimeError("Crossing reference checkpoints do not match the planned models")
    model_pool = ModelPool(codec, vectors)
    runner = SearchRunner(cfg, out)
    all_seeds = random.Random(SEED).sample(range(2_001_000_000, 2_146_000_000), 301)
    completed = 0

    def evaluate(stage, ids):
        nonlocal completed
        start, count = STAGES[stage]
        result = runner.evaluate(stage, list(ids), model_pool.docs, matchup,
                                 all_seeds[start:start + count], completed)
        completed += sum(map(len, result.values()))
        return result

    groups = tuple(model_pool.groups)
    candidates = {}
    for group in groups:
        candidates[group] = [
            model_pool.mutate(f"{group}-{parent}-{i}", parent, group, (0.04, 0.10)[i % 2])
            for parent in REFERENCE_IDS[:2] for i in range(4)]
    atomic_json(out / "models-initial.json", {name: vector.tolist() for name, vector in model_pool.vectors.items()})
    if args.smoke:
        evaluate("smoke", (*REFERENCE_IDS[:2], candidates["economy"][0]))
        return

    screen = evaluate("screen", (*REFERENCE_IDS, *sum(candidates.values(), [])))
    survivors = [model for ids in candidates.values() for model in rank({m: screen[m] for m in ids})[:2]]
    rescreen = evaluate("rescreen", (*REFERENCE_IDS, *survivors))
    parents = rank({model: rescreen[model] for model in survivors})[:2]
    variants = [model_pool.mutate(f"refined-{parent}-{i}", parent, group, (0.02, 0.05)[i % 2])
                for parent in parents for i, group in enumerate(
                    (parent.split("-")[0], parent.split("-")[0], *groups))]
    atomic_json(out / "models-refined.json", {name: vector.tolist() for name, vector in model_pool.vectors.items()})
    refined = evaluate("refine", (REFERENCE_IDS[0], *parents, *variants))
    finalists = rank({model: rows for model, rows in refined.items() if model not in REFERENCE_IDS})[:2]
    final = evaluate("final", (*REFERENCE_IDS, *finalists))
    incumbent = REFERENCE_IDS[0]
    comparisons = paired_comparisons(final, incumbent)
    challenger = rank({name: rows for name, rows in final.items() if name not in {incumbent, "gen115"}})[0]
    comparison = comparisons[f"{challenger}:{incumbent}"]
    if comparison["difference"] >= 0.02 and comparison["selection_lower"] <= 0:
        extra = evaluate("extra", (incumbent, challenger))
        extended = {name: final[name] + extra[name] for name in extra}
        comparison = paired_comparisons(extended, incumbent)[f"{challenger}:{incumbent}"]
        atomic_json(out / "extra-comparison.json", comparison)
    selected = challenger if comparison["difference"] >= 0.02 and comparison["selection_lower"] > 0 else incumbent
    atomic_json(out / "selected.json", model_pool.docs[selected])
    atomic_json(out / "summary.json", {"selected": selected, "games": completed, "challenge": challenger,
        "decision_comparison": comparison, "final_comparisons": comparisons,
        "final": {name: summarize(rows) for name, rows in final.items()}})
    atomic_json(out / "status.json", {"stage": "done", "completed": completed, "selected": selected})
    print(f"selected={selected} games={completed}", flush=True)


if __name__ == "__main__":
    main()
