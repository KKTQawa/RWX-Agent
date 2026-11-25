"""Search one Hardupv3 model across the approved three-map spawn layouts."""

import argparse
from collections import defaultdict
import hashlib
from pathlib import Path
import random
import time

import numpy as np

from rlkit.config import TrainConfig
from rlkit.match import MatchSpec, Matchup
from rlkit.params import ParamCodec
from rlkit.util import atomic_json
from search_crossing import ModelPool, SearchRunner, read, summarize


INCUMBENT = "gen345"
HARD = "rwx.original.hard"
VERY_HARD = "rwx.original.very-hard"
TEAM = "Volcano 4v4"
MAPS = {
    "Crossing": ("[p6]Crossing (6p).tmx", ((1, 2), (3, 6), (4, 5)),
                 "549c90e1573dceb5bccce1c1c6b5efd03029c9cf9087c2ae566a6ff8f78ff4af"),
    "Large Ice Outcrop": ("[p8]Large Ice Outcrop (8p).tmx", ((3, 6), (4, 5)),
                          "c5142649fd879bff0166c583e54e9a7f5b56714208a5bea2fbc6bff14bb9424c"),
    "Volcano 1v1": ("[p8]Volcano (8p).tmx", ((1, 2), (3, 4), (5, 6), (7, 8)),
                    "db3b420e082bdbe1612de7618e44f7798a34ce7d688aa564e597b1d1eb368ecc"),
}
STAGES = ("pilot-duel", "pilot-team", "screen", "rescreen", "rescreen-team", "refine",
          "refine-duel", "refine-team", "final-duel", "final-team")
PLANNED = 3640
GROUPS = ("economy-production", "land", "naval", "tactics")
NAVAL = {"battleship", "missileship", "attacksubmarine", "gunboat", "heavy battleship"}


def map_path(name):
    return f"assets/maps/skirmish/{MAPS[name][0]}"


def stage_seeds(stage, size):
    index = STAGES.index(stage)
    start = 2_050_000_000 + 1_000_000 * index
    return iter(random.Random(2026112502 + index).sample(range(start, start + 1_000_000), size))


def duel_specs(stage, games):
    seeds = stage_seeds(stage, sum(games) // 2)
    specs = []
    for (name, (_, pairs, _)), count in zip(MAPS.items(), games, strict=True):
        rounds, remainder = divmod(count, 2 * len(pairs))
        if remainder:
            raise ValueError(f"{stage} cannot balance {count} games on {name}")
        for _ in range(rounds):
            for pair in pairs:
                seed = next(seeds)
                matchup = Matchup(name, map_path(name), pair)
                specs.extend(MatchSpec(matchup, spawn, seed, 0, slot) for slot, spawn in enumerate(pair))
    return specs


def team_specs(stage, games):
    if games % 8:
        raise ValueError("Volcano requires eight games per full rotation")
    specs = []
    for index, seed in enumerate(stage_seeds(stage, games // 2)):
        for home_parity in (1, 0):
            opponents = tuple(spawn for spawn in range(1, 9) if spawn % 2 != home_parity)
            very_hard_spawn = opponents[index % 4]
            layout = tuple((spawn, "candidate" if spawn not in opponents else
                            VERY_HARD if spawn == very_hard_spawn else HARD)
                           for spawn in range(1, 9))
            first = 1 if home_parity else 2
            matchup = Matchup(TEAM, map_path("Volcano 1v1"), (1, 2), layout)
            specs.append(MatchSpec(matchup, first, seed, 0, first - 1))
    return specs


def parameter_groups(codec):
    groups = {name: [] for name in GROUPS}
    for index, knob in enumerate(codec.knobs):
        path = ".".join(knob.path).lower()
        if any(key in path for key in ("seafactory", "waterunits", "seagroup", "naval")):
            group = "naval"
        elif any(key in path for key in ("economy", "extractor", "upgrades.", "bankcredits", "reservecredits",
                                         "attemptinterval", "maxpercycle")):
            group = "economy-production"
        elif path.startswith(("building.", "buildingscore.", "units.")):
            group = "land"
        else:
            group = "tactics"
        groups[group].append(index)
    offset = len(codec.knobs)
    for weights in codec.groups:
        for index, name in enumerate(weights.names, offset):
            key = name.lower()
            group = "naval" if key in NAVAL or any(term in key for term in
                                                  ("ship", "submarine", "gunboat", "missileboat")) else "land"
            if key in {"gunship", "dropship", "heavygunship", "airship"}:
                group = "land"
            groups[group].append(index)
        offset += weights.dim
    return {name: np.asarray(indices) for name, indices in groups.items()}


def samples(rows):
    buckets = defaultdict(lambda: defaultdict(list))
    for row in rows:
        buckets[(row.map, tuple(row.pair))][row.seed].append(int(row.outcome == "win"))
    return {key: {seed: float(np.mean(wins)) for seed, wins in seeds.items()}
            for key, seeds in buckets.items()}


def weights(keys):
    team_enabled = any(name == TEAM for name, _ in keys)
    return {key: (1 / 6 if team_enabled and key[0] in {TEAM, "Volcano 1v1"} else 1 / 3)
            / sum(name == key[0] for name, _ in keys) for key in keys}


def score(rows):
    groups = samples(rows)
    return sum(weight * np.mean(list(groups[key].values())) for key, weight in weights(groups).items())


def ranked(results, names):
    return sorted(names, key=lambda name: (-score(results[name]), -summarize(results[name])["reward"], name))


def promote(results, names, count, reserved):
    ordered = ranked(results, names)
    leaders = ordered[:count - reserved]
    alternatives = [name for name in ordered if name not in leaders and
                    ("naval" in name or "tactics" in name)]
    leaders.extend(alternatives[:reserved])
    leaders.extend(name for name in ordered if name not in leaders)
    return leaders[:count]


def paired(rows, baseline, challengers):
    own, control = samples(rows), samples(baseline)
    if own.keys() != control.keys() or any(own[k].keys() != control[k].keys() for k in own):
        raise RuntimeError("Final decision requires identical map, pairing and seed coverage")
    rng = np.random.default_rng(2026112503)
    estimates = np.zeros(10000)
    difference = 0.0
    for key, weight in weights(own).items():
        delta = np.array([own[key][seed] - control[key][seed] for seed in own[key]])
        difference += weight * delta.mean()
        estimates += weight * rng.choice(delta, size=(len(estimates), len(delta))).mean(axis=1)
    alpha = 0.05 / (2 * challengers)
    return {"difference": float(difference), "adjusted_interval": np.quantile(estimates, [alpha, 1-alpha]).tolist()}


def combined(duels, teams):
    return {name: duels[name] + rows for name, rows in teams.items()}


def preserve(path, contents):
    if path.exists():
        if read(path) != contents:
            raise RuntimeError(f"Resume inputs differ: {path}")
    else:
        atomic_json(path, contents)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=20)
    args = parser.parse_args()
    out, previous = args.out.resolve(), args.previous.resolve()
    if (out / "summary.json").exists():
        print("Already complete", flush=True)
        return
    for name, (_, _, digest) in MAPS.items():
        if hashlib.sha256(Path(map_path(name)).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Unverified map: {name}")
    cfg = TrainConfig.load(Path("runs/hardupv3-magma-vh/config.json"))
    if cfg.opponent_id != VERY_HARD or cfg.income != 2.0:
        raise RuntimeError("Unexpected opponent or room income")
    cfg.out_dir, cfg.run_name, cfg.n_workers = out.parent, out.name, args.workers
    codec = ParamCodec(cfg.params, frozen_units=cfg.frozen_units)
    saved = read(previous / "models-initial.json")
    references = (INCUMBENT, "gen148", "gen115")
    pool = ModelPool(codec, {name: saved[name] for name in references})
    if pool.docs[INCUMBENT] != read(previous / "selected.json"):
        raise RuntimeError("gen345 checkpoint does not match the selected model")
    pool.groups = parameter_groups(codec)
    pool.rng = np.random.default_rng(2026112502)
    runner = SearchRunner(cfg, out)
    start_file = out / "clock.json"
    if not start_file.exists():
        atomic_json(start_file, {"started_at": time.time(), "budget_minutes": 180})
    started = read(start_file)["started_at"]
    if time.time() - started >= 180 * 60:
        raise RuntimeError("The three-hour wall-clock budget has expired")
    completed = 0
    elapsed = {}

    def evaluate(stage, names, specs):
        nonlocal completed
        names = list(dict.fromkeys(names))
        begun = time.monotonic()
        results = runner.evaluate_specs(stage, names, pool.docs, specs, completed, PLANNED)
        completed += len(names) * len(specs)
        metrics_path = out / f"{stage}-timing.json"
        if not metrics_path.exists():
            atomic_json(metrics_path, {"elapsed_s": time.monotonic() - begun,
                                       "games": len(names) * len(specs)})
        elapsed[stage] = read(metrics_path)
        return results

    def variants(parents, each, label):
        return [pool.mutate(f"{label}-{group}-{i:02d}-{parent}", parent, group,
                            (0.035, 0.07, 0.11, 0.16)[(i // 4) % 4])
                for parent in parents for i in range(each) for group in (GROUPS[i % 4],)]

    def capacity():
        def rate(stages, ceiling):
            observed = [elapsed[stage] for stage in stages if stage in elapsed]
            return min(ceiling, sum(row["games"] for row in observed) /
                       max(1, sum(row["elapsed_s"] for row in observed)) * 60)
        return (rate(("pilot-duel", "screen", "rescreen", "refine", "refine-duel"), 38),
                rate(("pilot-team", "rescreen-team", "refine-team"), 8))

    initial = variants((INCUMBENT,), 64, "screen")
    preserve(out / "models-initial.json", {name: vector.tolist() for name, vector in pool.vectors.items()})
    evaluate("pilot-duel", references, duel_specs("pilot-duel", (12, 12, 16)))
    evaluate("pilot-team", references, team_specs("pilot-team", 8))
    print("Approved spawn layouts and both Volcano team sides passed the pilot", flush=True)
    screen = evaluate("screen", (INCUMBENT, *initial), duel_specs("screen", (6, 4, 8)))
    survivors = promote(screen, initial, 12, 3)
    rescreen = evaluate("rescreen", (INCUMBENT, *survivors), duel_specs("rescreen", (12, 8, 16)))
    team_survivors = promote(rescreen, survivors, 8, 2)
    team = evaluate("rescreen-team", (INCUMBENT, *team_survivors), team_specs("rescreen-team", 8))
    scores = combined(rescreen, team)
    parents = ranked(scores, team_survivors)[:2]

    duel_rate, team_rate = capacity()
    choice = out / "refine-plan.json"
    if choice.exists():
        count = read(choice)["per_parent"]
    else:
        available = 125 - (time.time() - started) / 60
        count = next((n for n in (16, 8) if ((2 * n + 3) * 18 + 252) / duel_rate + 40 / team_rate + 3
                                              <= available), 0)
        atomic_json(choice, {"per_parent": count, "parents": parents})
    shortlist = ranked(scores, team_survivors)
    if count:
        new = variants(parents, count, "refine")
        preserve(out / "models-refined.json", {name: vector.tolist() for name, vector in pool.vectors.items()})
        refined = evaluate("refine", (INCUMBENT, *parents, *new), duel_specs("refine", (6, 4, 8)))
        contenders = promote(refined, [*parents, *new], 6, 1)
        duel = evaluate("refine-duel", (INCUMBENT, *contenders), duel_specs("refine-duel", (12, 8, 16)))
        teams = promote(duel, contenders, 4, 1)
        team = evaluate("refine-team", (INCUMBENT, *teams), team_specs("refine-team", 8))
        shortlist = ranked(combined(duel, team), teams)

    selection = out / "final-plan.json"
    if not selection.exists():
        duel_rate, team_rate = capacity()
        remaining = 180 - (time.time() - started) / 60
        per_model = 256 / duel_rate + 32 / team_rate
        finalists = shortlist[:2 if 3 * per_model + 5 <= remaining else 1]
        if 2 * per_model + 3 > remaining:
            raise RuntimeError("Insufficient time for the planned independent final")
        atomic_json(selection, {"challengers": finalists})
    finalists = read(selection)["challengers"]
    final_duels = evaluate("final-duel", (INCUMBENT, *finalists), duel_specs("final-duel", (96, 96, 64)))
    final_teams = evaluate("final-team", (INCUMBENT, *finalists), team_specs("final-team", 32))
    final = combined(final_duels, final_teams)
    comparisons = {name: paired(final[name], final[INCUMBENT], len(finalists)) for name in finalists}
    selected = next((name for name in ranked(final, finalists)
                     if comparisons[name]["difference"] >= 0.03
                     and comparisons[name]["adjusted_interval"][0] > 0), INCUMBENT)
    summary = {name: {"weighted_win_rate": score(rows),
                      "strata": {mode: summarize([r for r in rows if r.map == mode])
                                 for mode in (*MAPS, TEAM)}}
               for name, rows in final.items()}
    atomic_json(out / "selected.json", pool.docs[selected])
    atomic_json(out / "summary.json", {"selected": selected, "games": completed,
                "seconds": time.time() - started, "comparisons": comparisons, "final": summary})
    atomic_json(out / "status.json", {"stage": "done", "completed": completed, "selected": selected})
    print(f"Selected {selected} after {completed} games", flush=True)


if __name__ == "__main__":
    main()
