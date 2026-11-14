"""Declare who produced a micro run and make the run directory its public name.

The engine writes only gameplay evidence; which model and harness produced a run is administrator
knowledge. Full matches keep this in `models`, `tools` and `display_name`; micro runs use the same
field names and a display name shaped like a full match:

    <case> <task> [<track>] · <YYYYMMDD HH-MM> · <model> - <tool> · s<seed>

A run that no model drove declares what ran instead in the same slot: `baseline` for the greedy
script, `human` for a hand-played match. `meta.runner` records that fact as one of
`agent` / `baseline` / `human`, so a reader never has to infer a script run from a missing field.

The run directory is renamed to the display name, so the archived path reads
`evaluate/output/micro/<CASE>/<display_name>` instead of the engine's environment-only stamp. Every
place that stored the old directory name is fixed in the same pass: `meta.map.file`, the absolute
map path inside each replay, the summary text under `replay/`, and `baselines.byTask[*].run` in the
CASE `config.json`.

Usage
-----
    python evaluate/tools/stamp_micro_meta.py --run evaluate/output/micro/CASE2-LTE/<run> \
        --provider OpenCode --model "DeepSeek V4.1 Flash" --thinking high --tool Pi --apply
    python evaluate/tools/stamp_micro_meta.py --run evaluate/output/micro/CASE2-LTE/<run> \
        --runner baseline --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

_UTILS = Path(__file__).resolve().parents[1] / "utils"
if str(_UTILS) not in sys.path:
    sys.path.insert(0, str(_UTILS))

from replay_map import ReplayMapError, patch_replay  # noqa: E402
from replay import ReplayError  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MICRO_CONFIG = ROOT / "evaluate" / "micro"

FORBIDDEN_FILENAME = '<>:"/\\|?*'
RUN_STAMP = re.compile(r"_(\d{8})-(\d{6})(?:-\d+)?$")
RUNNERS = ("agent", "baseline", "human")
# `script` is the wording some tasks use; `baseline` is what the CASE configs call these runs.
RUNNER_ALIASES = {"script": "baseline"}


def _run_time(run: Path) -> str:
    """`YYYYMMDD HH-MM` from the engine run stamp, falling back to its mtime."""
    match = RUN_STAMP.search(run.name)
    if match:
        day, clock = match.groups()
        return f"{day} {clock[:2]}-{clock[2:4]}"
    return datetime.fromtimestamp(run.stat().st_mtime).strftime("%Y%m%d %H-%M")


def _participant(runner: str, model: str | None, tool: str | None) -> str:
    if runner == "agent":
        return f"{model} - {tool}"
    return runner


def _display_name(meta: dict, run: Path, runner: str, model: str | None, tool: str | None) -> str:
    parts = [str(meta.get("case") or "?"), str(meta.get("task") or "?")]
    if meta.get("track"):
        parts.append(str(meta["track"]))
    seed = meta.get("seed")
    run_id = f"s{seed}" if seed is not None else ""
    tail = f" · {run_id}" if run_id else ""
    # `provider` stays in models[]; the display keeps the full-match "model / tool" shape. ASCII `/`
    # would make the same string an invalid filename, so the separator is `-`.
    return f"{' '.join(parts)} · {_run_time(run)} · {_participant(runner, model, tool)}{tail}"


def _with_attempt(display: str, attempt: int | None) -> str:
    """Append ` · 0N` for a repeat run, so two attempts of the same match are distinguishable."""
    if not attempt:
        return display
    marker = f" · {attempt:02d}"
    return display if display.endswith(marker) else display + marker


def _filename_stem(display: str) -> str:
    return "".join("-" if char in FORBIDDEN_FILENAME else char for char in display).strip(" .")


def _find_replay(run: Path, meta: dict) -> Path | None:
    current = meta.get("replay")
    candidates: list[Path] = []
    if isinstance(current, str) and current:
        candidates.append(run / current)
    candidates.append(run / "match.replay")
    replay_dir = run / "replay"
    if replay_dir.is_dir():
        candidates.extend(sorted(replay_dir.glob("*.replay")))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _rebase_meta(meta: dict, old_run: Path, new_run: Path, replay_name: str | None) -> None:
    """Point the recorded absolute paths at the renamed directory."""
    if replay_name:
        meta["replay"] = replay_name
    recorded = (meta.get("map") or {}).get("file")
    if isinstance(recorded, str) and recorded:
        prefix = str(old_run)
        if recorded.startswith(prefix):
            meta["map"]["file"] = str(new_run) + recorded[len(prefix):]


def _rewrite_texts(run: Path, replacements: list[tuple[str, str]]) -> list[str]:
    """Rewrite the old directory/replay names in the derived text artifacts.

    Only the replay exports and the evaluation report carry recorded paths; `meta.json`,
    `result.json` and the engine streams are left alone so the evidence keeps its own wording.
    """
    changed: list[str] = []
    for root in (run / "replay", run / "eval"):
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in {".txt", ".jsonl"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            updated = text
            for old, new in replacements:
                if old:
                    updated = updated.replace(old, new)
            if updated != text:
                path.write_text(updated, encoding="utf-8")
                changed.append(str(path.relative_to(run)).replace("\\", "/"))
    return changed


def _repoint_case_config(case: str, old_name: str, new_name: str) -> bool:
    """`config.json` baselines record their run directory; keep that pointer valid."""
    path = MICRO_CONFIG / case / "config.json"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    updated = text.replace(f'"{old_name}"', f'"{new_name}"')
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def plan(run: Path, runner: str, provider: str | None, model: str | None, thinking: str | None,
         tool: str | None, tool_detail: str | None, display_name: str | None,
         attempt: int | None = None) -> dict:
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    if runner == "agent":
        missing = [flag for flag, value in (("--provider", provider), ("--model", model),
                                            ("--tool", tool)) if not value]
        if missing:
            raise ValueError(f"runner=agent needs {', '.join(missing)}")
    elif meta.get("models") and not display_name:
        raise ValueError("this run already records models; pass --runner agent to restate them")
    display = display_name or meta.get("display_name") or _display_name(meta, run, runner, model, tool)
    display = _with_attempt(display, attempt)
    stem = _filename_stem(display)
    if not stem:
        raise ValueError(f"display name has no filename-safe characters: {display!r}")
    target_run = run.with_name(stem)
    if target_run != run and target_run.exists():
        raise ValueError(f"target directory already exists: {target_run}")
    replay = _find_replay(run, meta)
    replay_name = f"{stem}.replay" if replay is not None else None
    return {"run": run, "meta": meta, "display": display, "runner": runner, "target": target_run,
            "replay": replay, "replayName": replay_name, "provider": provider, "model": model,
            "thinking": thinking, "tool": tool, "toolDetail": tool_detail, "attempt": attempt}


def apply(item: dict) -> list[str]:
    run: Path = item["run"]
    meta: dict = item["meta"]
    display: str = item["display"]
    runner: str = item["runner"]
    target: Path = item["target"]
    actions: list[str] = []

    if runner == "agent":
        entry = {"provider": item["provider"], "id": item["model"]}
        if item["thinking"]:
            entry["thinking"] = item["thinking"]
        meta["models"] = [entry]
        meta["tools"] = [{"profile": item["tool"], "detail": item["toolDetail"]}]
    meta["runner"] = runner
    meta["display_name"] = display
    if item.get("attempt"):
        meta["attempt"] = int(item["attempt"])

    replay: Path | None = item["replay"]
    replay_name: str | None = item["replayName"]
    if replay is not None and replay_name and replay.name != replay_name:
        destination = run / replay_name
        if destination.exists():
            raise ValueError(f"replay target already exists: {destination}")
        replay.replace(destination)
        actions.append(f"replay: {replay.name} -> {replay_name}")
        replay = destination

    if target != run:
        run.rename(target)
        actions.append(f"dir:    {run.name} -> {target.name}")
        if replay is not None:
            # The replay moved with the directory; keep pointing at the file itself.
            replay = target / replay.name

    _rebase_meta(meta, run, target, replay_name)
    replacements = [(str(run), str(target)), (run.name, target.name)]
    if replay is not None:
        replacements.append(("match.replay", replay.name))
    actions += [f"text:   {name}" for name in _rewrite_texts(target, replacements)]

    map_file = target / "map.tmx"
    if replay is not None and map_file.is_file():
        try:
            result = patch_replay(replay, map_file, apply=True)
        except (ReplayMapError, ReplayError) as exc:
            actions.append(f"replay map path: {exc}")
        else:
            if result.get("changed"):
                actions.append("replay: map path -> " + str(map_file))

    if _repoint_case_config(str(meta.get("case") or ""), run.name, target.name):
        actions.append(f"config: {meta.get('case')}/config.json baselines.byTask[*].run")

    temporary = target / "meta.json.tmp"
    temporary.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")) + "\n",
                         encoding="utf-8")
    temporary.replace(target / "meta.json")
    return actions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, action="append", required=True,
                        help="run directory containing meta.json; repeat for several runs")
    parser.add_argument("--runner", choices=RUNNERS + tuple(RUNNER_ALIASES),
                        help="who drove the run: agent (model), baseline (greedy script), human")
    parser.add_argument("--provider", help="for example OpenCode")
    parser.add_argument("--model", help="for example DeepSeek V4.1 Flash")
    parser.add_argument("--thinking", help="reasoning strength, for example high")
    parser.add_argument("--tool", help="agent harness, for example Pi")
    parser.add_argument("--tool-detail", help="optional detail for tools[].detail")
    parser.add_argument("--display-name", help="override the generated display name")
    parser.add_argument("--attempt", type=int, choices=range(1, 100), metavar="N",
                        help="repeat-run marker: appends ' · 0N' to the display name and records meta.attempt")
    parser.add_argument("--apply", action="store_true", help="write meta.json, rename and fix paths")
    args = parser.parse_args(argv)

    runner = RUNNER_ALIASES.get(args.runner or "", args.runner)
    if runner is None:
        parser.error("--runner is required: a run without models must declare baseline or human")

    failed = False
    for run in args.run:
        run = run.resolve()
        try:
            item = plan(run, runner, args.provider, args.model, args.thinking, args.tool,
                        args.tool_detail, args.display_name, args.attempt)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"error: {run}: {exc}", file=sys.stderr)
            failed = True
            continue
        print(f"{item['display']}")
        print(f"  runner={runner} dir={item['target'].name}")
        if item["replayName"]:
            print(f"  replay={item['replayName']}")
        if not args.apply:
            continue
        try:
            for action in apply(item):
                print(f"  {action}")
        except (OSError, ValueError) as exc:
            print(f"error: {item['target']}: {exc}", file=sys.stderr)
            failed = True
    if not args.apply:
        print("[dry run] re-run with --apply to write.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
