"""Launch the server-side Hard-up evaluation in tmux, with frozen inputs and resumable results.

python3 hardup_full_eval.py launch --repo REPO --pool POOL --weights WEIGHTS --out RUN
"""

import argparse
import concurrent.futures
import itertools
import json
import os
import random
import shlex
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from hardup_parity import (
    CANDIDATE, HARD, JDK, VERY_HARD, existing, pool_maps, read, run_match, sha, summarize, write,
)


ARMS = {
    "duel-hard": ("duel", 0),
    "duel-very-hard": ("duel", 1),
    "team-hard": ("team", 0),
    "team-1-very-hard": ("team", 1),
    "team-8p-plus-2-very-hard": ("large-team", 2),
}
GAMES_PER_ARM = 500
CONFIG = "candidate.json"
MAX_TICKS = 337500
SMOKE_TICKS = 1000


def make_schedule(pool):
    maps = pool_maps(pool)
    if len(maps) != 33 or len({item["map"] for item in maps}) != 33:
        raise ValueError("Expected the 33-map completition_full pool")
    team_maps = [
        item for item in maps if item["capacity"] >= 4
        and "环湖绝对平衡" not in item["name"]
        and "valleypass" not in item["name"].replace(" ", "").casefold()
    ]
    pools = {
        "duel": [item for item in maps if item["capacity"] <= 6],
        "team": team_maps,
        "large-team": [item for item in team_maps if item["capacity"] >= 8],
    }
    rng = random.Random(20261124700)
    schedule = []
    for pool_name, entries in pools.items():
        rng.shuffle(entries)
        n = GAMES_PER_ARM // 2
        visits = Counter()
        for index in range(n):
            item = entries[index % len(entries)]
            visit = visits[item["map"]]
            visits[item["map"]] += 1
            capacity = item["capacity"]
            if pool_name == "duel":
                seats = sorted(item["pairs"][visit % len(item["pairs"])])
                if len(set(seats)) != 2 or not all(1 <= seat <= capacity for seat in seats):
                    raise ValueError(f"Invalid duel seats: {item['name']} {seats}")
            else:
                seats = list(range(1, capacity + 1))
                if capacity not in (4, 6, 8, 10):
                    raise ValueError(f"Unsupported team map capacity: {item['name']}")
            seed = rng.randrange(1, 2_000_000_000)
            for side in (0, 1):
                mine = seats[side::2]
                enemy = seats[1 - side::2]
                for arm, (arm_pool, very_hard_count) in ARMS.items():
                    if arm_pool != pool_name:
                        continue
                    positions = list(itertools.combinations(enemy, very_hard_count))
                    schedule.append({
                        "id": f"{arm}-{index:03d}-{side}", "group": arm,
                        "map": item["map"], "map_name": item["name"], "capacity": capacity,
                        "seats": seats, "mine": mine, "seed": seed,
                        "very_hard": list(positions[visit % len(positions)]),
                    })
    rng.shuffle(schedule)
    return pools, schedule


def publish(path, data):
    staging = path.with_suffix(".part")
    write(staging, data)
    staging.replace(path)


def prepare(args):
    root = args.out / "input-tree"
    runtime = args.out / "runtime"
    pools, schedule = make_schedule(args.pool)
    inputs = root / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    for name in ("assets", "mods"):
        shutil.copytree(args.repo / name, root / name, dirs_exist_ok=True)
    shutil.copytree(args.repo / "lib", runtime / "lib", dirs_exist_ok=True)
    shutil.copytree(args.repo / JDK, runtime / JDK, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("legal"))
    shutil.copyfile(args.weights, inputs / CONFIG)
    shutil.copyfile(args.pool, inputs / "completition_full.json")
    for rows in pools.values():
        for item in rows:
            if not (root / item["map"]).is_file():
                raise FileNotFoundError(item["map"])
    write(inputs / "pools.json", pools)
    write(inputs / "schedule.json", schedule)
    write(inputs / "manifest.json", {
        "weights_source": str(args.weights),
        "weights_sha256": sha(inputs / CONFIG),
        "pool_sha256": sha(inputs / "completition_full.json"),
        "schedule_sha256": sha(inputs / "schedule.json"),
        "jars": {jar.name: sha(jar) for jar in sorted((runtime / "lib").glob("*.jar"))},
        "maps": {item["map"]: sha(root / item["map"]) for rows in pools.values() for item in rows},
        "room_income": 2.0, "max_ticks": MAX_TICKS, "max_wall_seconds": 1200,
    })
    for arm, (pool, _) in ARMS.items():
        print(f"{arm}: {len(pools[pool])} maps, {GAMES_PER_ARM} games", flush=True)


def result_stats(rows):
    valid = [row for row in rows if row["outcome"] != "error"]
    summary = summarize(valid)
    decisive = summary["wins"] + summary["losses"]
    return {**summary, "win_rate_excluding_draws": summary["wins"] / decisive if decisive else None,
            "errors": len(rows) - len(valid)}


def report(schedule, results):
    summary = {}
    for arm in ARMS:
        planned = [job for job in schedule if job["group"] == arm]
        rows = [results[job["id"]] for job in planned if job["id"] in results]
        sizes = sorted({len(job["mine"]) for job in planned})
        maps = sorted({job["map_name"] for job in planned})
        summary[arm] = {
            **result_stats(rows), "requested": GAMES_PER_ARM,
            "by_team_size": {f"{n}v{n}": result_stats([row for row in rows if len(row["mine"]) == n])
                             for n in sizes},
            "by_map": {name: result_stats([row for row in rows if row["map_name"] == name])
                       for name in maps},
        }
    return summary


def play(args, schedule, workers, *, smoke=False):
    path = args.out / ("smoke.jsonl" if smoke else "games.jsonl")
    results = {row["id"]: row for row in existing(path)}
    todo = [job for job in schedule if results.get(job["id"], {}).get("outcome") in (None, "error")]
    root, runtime = args.out / "input-tree", args.out / "runtime"
    scratch = args.out / "scratch"
    failures = args.out / "failures"
    scratch.mkdir(exist_ok=True)
    failures.mkdir(exist_ok=True)
    phase = "smoke" if smoke else "running"
    done = len(schedule) - len(todo)
    if not smoke:
        publish(args.out / "status.json", {"phase": phase, "valid": done, "planned": len(schedule)})
    print(f"{phase}: {done}/{len(schedule)} valid, {workers} workers", flush=True)
    with path.open("a", encoding="utf-8", buffering=1) as output:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            pending = []
            for job in todo:
                roster = {seat: CANDIDATE if seat in job["mine"] else
                          VERY_HARD if seat in job["very_hard"] else HARD for seat in job["seats"]}
                pending.append(executor.submit(
                    run_match, root, runtime, scratch, "candidate", job,
                    SMOKE_TICKS if smoke else MAX_TICKS, failures,
                    roster=roster, config=CONFIG, processors=1,
                ))
            for index, future in enumerate(concurrent.futures.as_completed(pending), 1):
                row = future.result()
                results[row["id"]] = row
                output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                if row["outcome"] == "error":
                    print(f"{row['id']} {row['map_name']}: {row['error']}", flush=True)
                else:
                    done += 1
                if index % 25 == 0 or index == len(todo):
                    print(f"{phase}: {done}/{len(schedule)} valid", flush=True)
                    if not smoke:
                        publish(args.out / "summary.json", report(schedule, results))
                        publish(args.out / "status.json",
                                {"phase": phase, "valid": done, "planned": len(schedule)})
    return results


def batch(args):
    cpu_ids = sorted(os.sched_getaffinity(0))
    selected = args.cpus if args.cpus is not None else cpu_ids[:round(len(cpu_ids) * args.cpu_share)]
    if len(set(selected)) != len(selected) or not set(selected).issubset(cpu_ids):
        raise ValueError(f"Invalid CPU list for this process: {selected}")
    workers = len(selected)
    os.sched_setaffinity(0, selected)
    print(f"CPU allocation: {workers}/{len(cpu_ids)}, affinity {selected}", flush=True)
    started = time.monotonic()
    inputs = args.out / "input-tree" / "inputs"
    manifest = read(inputs / "manifest.json")
    for path, key in ((inputs / CONFIG, "weights_sha256"), (inputs / "schedule.json", "schedule_sha256")):
        if sha(path) != manifest[key]:
            raise ValueError(f"Frozen input changed: {path}")
    schedule = read(inputs / "schedule.json")
    counts = Counter(job["group"] for job in schedule)
    if counts != {arm: GAMES_PER_ARM for arm in ARMS} or len({job["id"] for job in schedule}) != len(schedule):
        raise ValueError(f"Invalid fixed schedule: {counts}")
    smoke = {}
    for job in schedule:
        key = (job["group"], job["map"], tuple(job["seats"]), tuple(job["mine"]))
        smoke.setdefault(key, job)
    publish(args.out / "status.json", {"phase": "smoke", "planned": len(schedule), "valid": 0})
    smoke_results = play(args, list(smoke.values()), workers, smoke=True)
    if any(row["outcome"] != "draw" for row in smoke_results.values()):
        raise RuntimeError("A smoke match failed to reach the short tick limit with all command centers alive")
    for _ in range(3):
        results = play(args, schedule, workers)
        valid = sum(row["outcome"] != "error" for row in results.values())
        if valid == len(schedule):
            publish(args.out / "summary.json", report(schedule, results))
            publish(args.out / "status.json", {"phase": "complete", "valid": valid, "planned": len(schedule),
                                              "elapsed_seconds": round(time.monotonic() - started, 1)})
            return
    raise RuntimeError(f"Only {valid}/{len(schedule)} valid games after retries")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("launch", "batch"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--pool", type=Path)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--cpu-share", type=float, default=0.875)
    parser.add_argument("--cpus", type=int, nargs="+", help="Pin one worker to the shared set per listed CPU")
    args = parser.parse_args()
    if not 0.80 <= args.cpu_share <= 0.90:
        parser.error("--cpu-share must be between 0.80 and 0.90")
    args.out = args.out.resolve()
    if args.mode == "batch":
        try:
            batch(args)
        except Exception as error:
            status = args.out / "status.json"
            publish(status, {**(read(status) if status.exists() else {}), "phase": "failed",
                             "error": str(error)})
            raise
        return
    args.out.mkdir(parents=True, exist_ok=True)
    if (args.out / "status.json").exists() and read(args.out / "status.json")["phase"] == "complete":
        print(f"Already complete: {args.out}")
        return
    session = args.out.name
    if subprocess.run(["tmux", "has-session", "-t", f"={session}"], capture_output=True).returncode == 0:
        print(f"Already running: {session}")
        return
    if not (args.out / "input-tree" / "inputs" / "manifest.json").exists():
        if args.pool is None or args.weights is None:
            parser.error("a new run also requires --pool and --weights")
        args.weights = args.weights.resolve()
        prepare(args)
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "batch",
               "--out", str(args.out), "--cpu-share", str(args.cpu_share)]
    if args.cpus is not None:
        command.extend(("--cpus", *map(str, args.cpus)))
    log = shlex.quote(str(args.out / "run.log"))
    subprocess.run(["tmux", "new-session", "-d", "-s", session,
                    f"{shlex.join(command)} >> {log} 2>&1"], check=True)
    print(f"Started {session}: {args.out}", flush=True)


if __name__ == "__main__":
    main()
