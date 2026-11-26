"""Hard-up v4 wide CMA-ES on Magma Island and Large Ice Outcrop."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import json
import math
from pathlib import Path
import random
import signal
import statistics

import numpy as np

from rlkit.config import TrainConfig
from rlkit.match import MatchSpec, candidate_seat
from rlkit.objective import ParamsObjective, register_objective
from rlkit.params import ParamCodec
from rlkit.paths import HERE
from rlkit.runner import aggregate
from rlkit.trainer import Trainer
from rlkit.util import atomic_json, read_json


class NormalizedCodec(ParamCodec):
    """Use each coordinate's full legal span as one CMA-ES unit."""

    initial_vector = None

    def bounds(self):
        lo, hi = super().bounds()
        return np.zeros_like(lo), np.ones_like(hi)

    def encode(self):
        if self.initial_vector is not None:
            return self.initial_vector.copy()
        lo, hi = super().bounds()
        grid = np.array(self.init + [x for g in self.groups for x in g.encode()])
        normalized = np.divide(grid - lo, hi - lo, out=np.zeros_like(lo), where=hi > lo)
        return np.clip(normalized, 0, 1)

    def decode(self, x):
        lo, hi = super().bounds()
        doc = super().decode(lo + np.clip(x, 0, 1) * (hi - lo))
        reference = doc["reference"]
        placement = reference["placementAttempts"]["value"]
        cluster = reference["fabricatorClusterAttempts"]
        # The engine reserves at least one attempt for ordinary placement.
        cluster["value"] = min(cluster["value"], placement - 1)
        return doc


def mirrored_specs(pairs, seeds, batch=0):
    return [
        MatchSpec(matchup, spawn, seed, batch, candidate_slot=slot)
        for matchup, seed in zip(pairs, seeds)
        for slot, spawn in enumerate(matchup.pair)
    ]


class MirroredObjective(ParamsObjective):
    next_generation = 1

    def start_generation(self):
        offset = (self.next_generation - 1) % 2
        pairs = (self.entries[offset], self.entries[2 + offset])
        seeds = [self.rng.randrange(1, 1_000_000_000) for _ in pairs]
        self._specs = mirrored_specs(pairs, seeds)
        self.next_generation += 1

    def screen_specs(self, games, rng):
        specs = []
        for batch in range(games // (2 * len(self.entries))):
            seeds = rng.sample(range(1_000_000_000, 2_000_000_000), len(self.entries))
            specs.extend(mirrored_specs(self.entries, seeds, batch))
        return specs

    def evaluate_many(self, X):
        docs = [self.codec.decode(x) for x in X]
        records = self.runner.run_jobs([(doc, spec) for doc in docs for spec in self._specs])
        count = len(self._specs)
        results = []
        for index, (x, doc) in enumerate(zip(X, docs)):
            games = records[index * count:(index + 1) * count]
            result = aggregate([game for game in games if not game.error])
            result.update(x=x.tolist(), params=doc, records=games, fitness=-result["reward"])
            results.append(result)
        return results


@register_objective("v4-mirrored")
def make_objective(cfg, codec, rng, runner):
    return MirroredObjective(cfg, codec, runner, rng)


class TeamObjective(MirroredObjective):
    def _panel(self, rng, seed_range, batch=0):
        specs = []
        for layout in self.entries:
            seed = rng.randrange(*seed_range)
            mirror = replace(layout, teams=tuple(
                (spawn, "opponent" if role == "candidate" else "candidate")
                for spawn, role in layout.teams))
            for matchup in (layout, mirror):
                spawn, slot = candidate_seat(matchup, 0, 0)
                specs.append(MatchSpec(matchup, spawn, seed, batch, candidate_slot=slot))
        return specs

    def start_generation(self):
        self._specs = self._panel(self.rng, (1, 1_000_000_000))

    def screen_specs(self, games, rng):
        return [
            spec
            for batch in range(games // (2 * len(self.entries)))
            for spec in self._panel(rng, (1_000_000_000, 2_000_000_000), batch)
        ]


@register_objective("v4-mirrored-team")
def make_team_objective(cfg, codec, rng, runner):
    return TeamObjective(cfg, codec, runner, rng)


def summarize(records):
    counts = Counter(record.outcome for record in records)
    return {
        "games": len(records),
        "wins": counts["win"],
        "draws": counts["draw"],
        "losses": counts["loss"],
        "win_rate": statistics.fmean(record.win for record in records),
        "reward": statistics.fmean(record.reward for record in records),
    }


class WideTrainer(Trainer):
    codec_class = NormalizedCodec

    def __init__(self, cfg, *, codec=None):
        super().__init__(cfg, codec=codec)
        if cfg.objective == "v4-mirrored-team" and not cfg.resume:
            self.gen = 100
        self.objective.next_generation = self.gen + 1

    def train(self):
        # A checkpoint precedes screening, so an interruption here can replay the same panel.
        if self.cfg.resume and self.gen and self.gen % self.cfg.validation_every == 0:
            self.validate()
        super().train()

    def mean_vector(self):
        return self.optimizer.phenotype_mean

    def _penalise(self, results):
        complete = [result for result in results if result["valid"] == 4]
        failed = [result for result in results if result["valid"] != 4]
        if failed:
            atomic_json(self.run_dir / f"incomplete-{self.gen:04d}.json", [
                {"params": result["params"], "games": [game.to_json() for game in result["records"]]}
                for result in failed
            ])
            print(f"gen {self.gen}: {len(failed)} incomplete candidates", flush=True)
        if len(complete) < math.ceil(len(results) / 2):
            raise RuntimeError(f"gen {self.gen}: too few complete mirrored scores; resume latest checkpoint")
        penalty = max(result["fitness"] for result in complete) + 0.05
        for result in failed:
            result["fitness"] = penalty
            result["penalized"] = True
        return [result["fitness"] for result in results]

    def _append_candidates(self, results):
        super()._append_candidates(results)
        if self.gen <= 40:
            docs = {json.dumps(r["params"], sort_keys=True) for r in results}
            start = self.codec.encode()
            moves = [np.abs(np.asarray(r["x"]) - start) for r in results]
            atomic_json(self.run_dir / f"coverage-{self.gen:04d}.json", {
                "unique_configs": len(docs),
                "candidates": len(results),
                "mean_axes_moved_by_10pct": statistics.fmean(np.sum(move >= 0.10) for move in moves),
                "near_boundary_fraction": statistics.fmean(
                    np.mean((np.asarray(r["x"]) < 0.02) | (np.asarray(r["x"]) > 0.98)) for r in results),
            })
        if self.gen % self.cfg.validation_every == 0:
            best = max((r for r in results if not r.get("penalized")), key=lambda r: r["reward"])
            atomic_json(self.params_dir / f"candidate_gen{self.gen:04d}.json", best["params"])

    def validate(self):
        screen = self.run_dir / f"screen-{self.gen:04d}.json"
        if screen.exists():
            atomic_json(self.params_dir / "best_val.json", read_json(Path(read_json(screen)["winner"])))
            return

        contenders = [
            self.params_dir / f"mean_gen{self.gen:04d}.json",
            self.params_dir / f"candidate_gen{self.gen:04d}.json",
        ]
        previous = self.run_dir / f"screen-{self.gen - self.cfg.validation_every:04d}.json"
        if previous.exists():
            contenders.insert(0, Path(read_json(previous)["winner"]))
        elif self.cfg.objective == "v4-mirrored-team":
            contenders.insert(0, self.cfg.params)

        specs = self.objective.screen_specs(self.cfg.validation_games,
                                            random.Random(self.cfg.seed + self.gen))
        docs = [read_json(path) for path in contenders]
        records = self.runner.run_jobs([(doc, spec) for doc in docs for spec in specs])
        scores = []
        for i, path in enumerate(contenders):
            games = records[i * len(specs):(i + 1) * len(specs)]
            failures = [record.to_json() for record in games if record.error]
            if failures:
                scores.append({"params": str(path), "failures": failures})
                continue
            scores.append({
                "params": str(path),
                **summarize(games),
                "per_map": {name: summarize([record for record in games if record.map == name])
                            for name in sorted({record.map for record in games})},
                "results": [record.to_json() for record in games],
            })
        complete = [score for score in scores if "win_rate" in score]
        if not complete:
            atomic_json(self.run_dir / f"screen-failed-{self.gen:04d}.json", scores)
            raise RuntimeError(f"gen {self.gen}: no complete screening panel; resume latest checkpoint")
        best = max(complete, key=lambda score: (score["win_rate"], score["reward"]))
        atomic_json(screen, {"gen": self.gen, "winner": best["params"], "contenders": scores})
        atomic_json(self.params_dir / "best_val.json", read_json(Path(best["params"])))
        print(f"筛选 gen{self.gen}: {Path(best['params']).stem} {best['win_rate']:.1%} "
              f"({best['wins']}/{best['draws']}/{best['losses']}, n={best['games']})", flush=True)

    def finalize(self):
        super().finalize()
        if self.gen == self.cfg.max_generations:
            atomic_json(self.params_dir / "final.json", read_json(self.params_dir / "best_val.json"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--team-from", type=Path, help="Start generation 101 from screened weights")
    parser.add_argument("--team-vector", type=Path, help="Archived search vector of the screened weights")
    parser.add_argument("--stop-after-generation", type=int, choices=(100,))
    args = parser.parse_args()
    run = args.out.resolve()
    if (run / "config.json").exists() and not args.resume:
        parser.error("run exists; use --resume")
    checkpoint = run / "checkpoints" / "latest.pkl"
    if args.resume and not checkpoint.is_file():
        parser.error("no checkpoint for --resume")
    if args.team_from and (args.stop_after_generation or not args.team_from.is_file()):
        parser.error("--team-from requires an existing parameter file and runs past generation 100")
    team = args.team_from is not None
    if team != (args.team_vector is not None):
        parser.error("--team-from and --team-vector must be used together")
    if args.resume:
        previous = read_json(run / "config.json")
        expected = "v4-mirrored-team" if team else "v4-mirrored"
        if previous["objective"] != expected or (team and args.team_from.resolve() != Path(previous["params"])):
            parser.error("resume requires the original training stage and input configuration")
    pool = "pool-v4-kingdoms-crossing-team.json" if team else "pool-v4-magma-ice.json"
    last_generation = (102 if team else 2) if args.smoke else (args.stop_after_generation or 200)
    cfg = TrainConfig(
        scenario="hardupv4", params=args.team_from.resolve() if team else HERE / "params_Hardupv4.json",
        pool=HERE / "pools" / pool, out_dir=run.parent, run_name=run.name,
        objective="v4-mirrored-team" if team else "v4-mirrored",
        opponent_id="rwx.original.very-hard", income=2.0,
        seed=1331, sigma0=0.15 if team else 0.25,
        popsize=4 if args.smoke else (7 if team else 20),
        max_generations=last_generation, n_workers=28 if team else 20,
        games_per_batch=4, n_batches=1, min_valid_games=4,
        retry_wall_limit=True,
        validation_every=2 if args.smoke else 50, validation_games=8 if args.smoke else 64,
        permanent_every=50, resume=checkpoint if args.resume else None,
    )
    codec = None
    if team:
        codec = NormalizedCodec(HERE / "params_Hardupv4.json")
        vector = np.asarray(read_json(args.team_vector), dtype=float)
        if (vector.shape != (codec.dim,) or not np.all(np.isfinite(vector))
                or np.any(vector < 0) or np.any(vector > 1)):
            parser.error("invalid archived vector")
        if codec.decode(vector) != read_json(cfg.params):
            parser.error("archived vector does not reproduce the screened parameters")
        codec.initial_vector = vector
    trainer = WideTrainer(cfg, codec=codec)
    signal.signal(signal.SIGINT, lambda *_: setattr(trainer, "stop_requested", True))
    trainer.train()


if __name__ == "__main__":
    main()
