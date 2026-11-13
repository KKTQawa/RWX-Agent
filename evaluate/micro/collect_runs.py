#!/usr/bin/env python3
"""Move one completed managed micro run into the canonical per-case evidence root."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

_UTILS = Path(__file__).resolve().parents[1] / "utils"
if str(_UTILS) not in sys.path:
    sys.path.insert(0, str(_UTILS))

from replay_map import ReplayMapError, patch_replay  # noqa: E402


CASE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")


class CollectionError(ValueError):
    pass


def completed_run(run_root: Path) -> tuple[Path, str]:
    output_root = run_root / "micro-output"
    if not output_root.is_dir():
        raise CollectionError(f"managed output directory is missing: {output_root}")
    candidates = sorted(path for path in output_root.iterdir() if path.is_dir() and (path / "meta.json").is_file())
    if len(candidates) != 1:
        raise CollectionError(f"expected exactly one micro result under {output_root}, found {len(candidates)}")
    source = candidates[0]
    if not (source / "result.json").is_file():
        raise CollectionError(f"micro run is not complete (result.json is missing): {source}")
    try:
        meta = json.loads((source / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CollectionError(f"cannot read {source / 'meta.json'}: {exc}") from exc
    case = meta.get("case")
    if not isinstance(case, str) or not CASE_NAME.fullmatch(case):
        raise CollectionError(f"invalid meta.case in {source / 'meta.json'}: {case!r}")
    return source, case


def rebase_map_path(source: Path, target: Path) -> bool:
    """Point `meta.map.file` at the moved map so the archived run no longer references the old tree."""
    meta_path = target / "meta.json"
    map_file = target / "map.tmx"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False
    recorded = (meta.get("map") or {}).get("file")
    if not isinstance(recorded, str) or not map_file.is_file():
        return False
    try:
        Path(recorded).resolve().relative_to(source.resolve())
    except ValueError:
        return False
    meta["map"]["file"] = str(map_file.resolve())
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return True


def rebase_replay_map(target: Path) -> list[dict[str, object]]:
    """Point collected replays at the archived `map.tmx` instead of the old external run tree."""
    map_file = target / "map.tmx"
    if not map_file.is_file():
        return []
    replays: list[Path] = sorted(target.glob("*.replay"))
    replay_dir = target / "replay"
    if replay_dir.is_dir():
        replays.extend(sorted(replay_dir.glob("*.replay")))
    results = []
    for replay in replays:
        results.append(patch_replay(replay, map_file, apply=True))
    return results


def collection_plan(run_root: Path, destination_root: Path) -> tuple[Path, Path]:
    source, case = completed_run(run_root)
    destination_base = destination_root.resolve()
    target = (destination_base / case / source.name).resolve()
    try:
        target.relative_to(destination_base)
    except ValueError as exc:
        raise CollectionError(f"destination escapes output root: {target}") from exc
    if target.exists():
        raise CollectionError(f"destination already exists; refusing to overwrite: {target}")
    return source, target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path, help="managed external run directory")
    parser.add_argument("--destination", type=Path, default=Path("evaluate/output/micro"), help="canonical micro output root")
    parser.add_argument("--apply", action="store_true", help="move the completed directory; without it, only print the plan")
    parser.add_argument("--json", action="store_true", help="emit the plan as JSON")
    args = parser.parse_args(argv)
    try:
        source, target = collection_plan(args.run.resolve(), args.destination)
        payload = {"action": "move", "source": str(source), "destination": str(target), "applied": args.apply}
        warnings: list[str] = []
        if args.apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            rebase_map_path(source, target)
            try:
                patched = rebase_replay_map(target)
            except ReplayMapError as exc:
                warnings.append(str(exc))
                patched = []
            payload["replayMapPatched"] = len(patched)
        if warnings:
            payload["warnings"] = warnings
        print(json.dumps(payload, ensure_ascii=False) if args.json else f"MOVE {source} -> {target}")
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 0
    except CollectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
