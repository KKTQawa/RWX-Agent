"""Record the model/tool identity of a micro run in its `meta.json` and name its replay.

The engine writes only gameplay evidence; which model and harness produced a run is administrator
knowledge. Full matches keep this in `models`, `tools` and `display_name`; micro runs use the same
field names and a display name shaped like a full match:

    <case> <task> [<track>] · <YYYYMMDD HH-MM> · <model> - <tool> · s<seed>

The replay is renamed to the same display name (`<display_name>.replay`) and `meta.replay` follows.
`/` is not used between model and tool because the display name doubles as a Windows filename.

Usage
-----
    python evaluate/tools/stamp_micro_meta.py --run evaluate/output/micro/CASE2-LTE/<run> \
        --provider OpenCode --model "DeepSeek V4.1 Flash" --thinking high --tool Pi --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

FORBIDDEN_FILENAME = '<>:"/\\|?*'
RUN_STAMP = re.compile(r"_(\d{8})-(\d{6})(?:-\d+)?$")


def _run_time(run: Path) -> str:
    """`YYYYMMDD HH-MM` from the run directory stamp, falling back to its mtime."""
    match = RUN_STAMP.search(run.name)
    if match:
        day, clock = match.groups()
        return f"{day} {clock[:2]}-{clock[2:4]}"
    return datetime.fromtimestamp(run.stat().st_mtime).strftime("%Y%m%d %H-%M")


def _display_name(meta: dict, run: Path, model: str, provider: str, tool: str) -> str:
    parts = [str(meta.get("case") or "?"), str(meta.get("task") or "?")]
    if meta.get("track"):
        parts.append(str(meta["track"]))
    seed = meta.get("seed")
    run_id = f"s{seed}" if seed is not None else ""
    tail = f" · {run_id}" if run_id else ""
    # `provider` stays in models[]; the display keeps the full-match "model / tool" shape. ASCII `/`
    # would make the same string an invalid filename, so the separator is `-`.
    return f"{' '.join(parts)} · {_run_time(run)} · {model} - {tool}{tail}"


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


def _display_for(meta: dict, run: Path, model: str, provider: str, tool: str, override: str | None) -> str:
    return override or _display_name(meta, run, model, provider, tool)


def stamp(run: Path, provider: str, model: str, thinking: str | None,
          tool: str, tool_detail: str | None, display_name: str | None) -> tuple[dict, Path, Path | None]:
    meta_path = run / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    entry = {"provider": provider, "id": model}
    if thinking:
        entry["thinking"] = thinking
    meta["models"] = [entry]
    meta["tools"] = [{"profile": tool, "detail": tool_detail}]
    meta["display_name"] = _display_for(meta, run, model, provider, tool, display_name)
    source = _find_replay(run, meta)
    target = None
    if source is not None:
        target = run / f"{_filename_stem(meta['display_name'])}.replay"
        meta["replay"] = target.name
    return meta, source or run / "match.replay", target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, action="append", required=True,
                        help="run directory containing meta.json; repeat for several runs")
    parser.add_argument("--provider", required=True, help="for example OpenCode")
    parser.add_argument("--model", required=True, help="for example DeepSeek V4.1 Flash")
    parser.add_argument("--thinking", help="reasoning strength, for example high")
    parser.add_argument("--tool", required=True, help="agent harness, for example Pi")
    parser.add_argument("--tool-detail", help="optional detail for tools[].detail")
    parser.add_argument("--display-name", help="override the generated display name")
    parser.add_argument("--apply", action="store_true", help="write meta.json and rename the replay")
    args = parser.parse_args(argv)
    failed = False
    for run in args.run:
        run = run.resolve()
        try:
            meta, source, target = stamp(run, args.provider, args.model, args.thinking, args.tool,
                                         args.tool_detail, args.display_name)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"error: {run / 'meta.json'}: {exc}", file=sys.stderr)
            failed = True
            continue
        print(f"{meta['display_name']}: {run / 'meta.json'}")
        if target is not None and source.resolve() != target.resolve():
            print(f"  replay: {source.name} -> {target.name}")
            if target.exists():
                print(f"error: replay target already exists: {target}", file=sys.stderr)
                failed = True
                continue
            if args.apply:
                source.replace(target)
        if args.apply:
            temporary = run / "meta.json.tmp"
            temporary.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")) + "\n",
                                 encoding="utf-8")
            temporary.replace(run / "meta.json")
    if not args.apply:
        print("[dry run] re-run with --apply to write.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
