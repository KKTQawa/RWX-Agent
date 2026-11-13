"""Point micro-run replays at their current map file so the game can play them.

A `.replay` records the absolute path of the map it was recorded on. Moving a run directory leaves
that path dangling: the replay itself is complete, but loading it fails at the map and the game shows
a "quit?" dialog. This tool rewrites only the recorded map path (see `evaluate/utils/replay_map.py`).

Usage
-----
    python evaluate/tools/patch_replay_map.py --run evaluate/output/micro/CASE2-LTE/<run>        # dry run
    python evaluate/tools/patch_replay_map.py --run evaluate/output/micro/CASE2-LTE/<run> --apply
    python evaluate/tools/patch_replay_map.py --root evaluate/output/micro                       # all runs
    python evaluate/tools/patch_replay_map.py --replay <file.replay> --map <map.tmx> --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluate" / "utils"))

from replay_map import ReplayMapError, patch_replay  # noqa: E402


def run_replays(run: Path) -> list[Path]:
    found = sorted(run.glob("*.replay"))
    if (run / "replay").is_dir():
        found.extend(sorted((run / "replay").glob("*.replay")))
    return found


def patch_run(run: Path, apply: bool) -> list[dict[str, object]]:
    map_file = run / "map.tmx"
    if not map_file.is_file():
        raise ReplayMapError(f"run has no map.tmx: {run}")
    replays = run_replays(run)
    if not replays:
        raise ReplayMapError(f"run has no replay: {run}")
    return [patch_replay(replay, map_file, apply=apply) for replay in replays]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run", type=Path, help="one run directory containing map.tmx and a replay")
    source.add_argument("--root", type=Path, help="scan every directory under this root for map.tmx + replay")
    source.add_argument("--replay", type=Path, help="one replay file; requires --map")
    parser.add_argument("--map", type=Path, help="map.tmx to record in the replay")
    parser.add_argument("--apply", action="store_true", help="rewrite in place; without it, only print the plan")
    parser.add_argument("--json", action="store_true", help="emit results as JSON")
    args = parser.parse_args(argv)
    try:
        results: list[dict[str, object]] = []
        if args.run:
            results.extend(patch_run(args.run.resolve(), args.apply))
        elif args.root:
            root = args.root.resolve()
            seen: set[Path] = set()
            for map_file in sorted(root.rglob("map.tmx")):
                for replay in run_replays(map_file.parent):
                    if replay in seen:
                        continue
                    seen.add(replay)
                    results.append(patch_replay(replay, map_file, apply=args.apply))
        else:
            if args.map is None:
                parser.error("--replay requires --map")
            results.append(patch_replay(args.replay.resolve(), args.map.resolve(), apply=args.apply))
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            for result in results:
                state = "changed" if result["changed"] else "unchanged"
                print(f"{state}: {result['replay']}")
                if result["changed"]:
                    print(f"  map: {result['previousMap']} -> {result['map']}")
            if not results:
                print("no replays found")
            if not args.apply:
                print("[dry run] re-run with --apply to rewrite.")
        return 0
    except ReplayMapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
