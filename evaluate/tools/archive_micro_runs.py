"""Normalize micro evaluation runs into one self-contained folder per match.

Why this exists
---------------
A micro run is written to `evaluate/output/micro/<CASE>/<run>/` with `match.replay` at the run
root and the per-run HTML summary in `<CASE>/reports/`. Full matches instead keep every artifact
inside the match folder. After a few weeks of iteration the micro tree mixes both shapes: the
replay sits outside `replay/`, the HTML pages live one level up, and root `replays/` keeps a twin
of the archived replay.

This tool normalizes legacy runs to:

  * `replay/<run>.replay`           moved from `match.replay`; `meta.replay` is repointed
  * `replay/<run>.{jsonl,txt,summary.txt}`  renamed from `replay/match.*`
  * `eval/report-full.html`         per-run HTML moved in from `<CASE>/reports/<run>.html`
  * `replays/<run>.replay`          deleted only when byte-identical to the archived copy

A run stamped by `stamp_micro_meta.py` already has a display-named replay (for example
`CASE2-LTE 2_6_4 realtime · … · s1331.replay`) at the run root. The display name is the public
identity and also the replay filename, so this tool leaves that file and `meta.replay` alone and
only normalizes the remaining artifacts.

It is deliberately conservative: dry run by default, moves instead of copies, reports conflicts
instead of choosing one of two different files, and never renames a run directory.

Usage
-----
    python evaluate/tools/archive_micro_runs.py                 # dry run, prints the plan
    python evaluate/tools/archive_micro_runs.py --apply         # perform the moves
    python evaluate/tools/archive_micro_runs.py --case CASE1-duel
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MICRO = ROOT / "evaluate" / "output" / "micro"
REPLAYS = ROOT / "replays"
NON_RUN = {"reports"}
EXPORTS = (".summary.txt", ".jsonl", ".txt")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def same_file(left: Path, right: Path) -> bool:
    return (
        left.is_file()
        and right.is_file()
        and left.stat().st_size == right.stat().st_size
        and digest(left) == digest(right)
    )


def read_meta(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def replay_relative(run_name: str) -> str:
    return f"replay/{run_name}.replay"


def meta_action(run_dir: Path, current: str, wanted: str) -> dict | None:
    """Point `meta.replay` at the archived replay without reformatting the file."""
    path = run_dir / "meta.json"
    text = path.read_text(encoding="utf-8")
    old = f'"replay":{json.dumps(current, ensure_ascii=False)}'
    new = f'"replay":{json.dumps(wanted, ensure_ascii=False)}'
    if text.count(old) != 1:
        return None
    return {"kind": "meta", "path": path, "old": old, "new": new, "from": current, "to": wanted}


def plan_run(case_dir: Path, run_dir: Path) -> dict:
    actions: list[dict] = []
    conflicts: list[str] = []
    name = run_dir.name

    try:
        meta = read_meta(run_dir / "meta.json")
    except (OSError, json.JSONDecodeError) as exc:
        return {"case": case_dir.name, "run": name, "actions": [], "conflicts": [f"meta.json: {exc}"]}

    current = meta.get("replay") or "match.replay"
    wanted = replay_relative(name)
    source = run_dir / current
    target = run_dir / wanted
    display = meta.get("display_name")

    # `stamp_micro_meta.py` names the replay after the public display name; that is the intended
    # shape for new runs, so do not move it back to a machine-named `replay/<run>.replay`.
    if isinstance(display, str) and display and source.is_file() and source.stem == display:
        pass
    elif source.resolve() == target.resolve():
        if current != wanted and (fix := meta_action(run_dir, current, wanted)):
            actions.append(fix)
    elif source.is_file():
        if target.is_file():
            if same_file(source, target):
                actions.append({"kind": "drop", "path": source, "reason": "replay 已是同一份"})
            else:
                conflicts.append(f"两份回放内容不同：{source.name} 与 {wanted}")
        else:
            actions.append({"kind": "move", "from": source, "to": target})
            if (fix := meta_action(run_dir, current, wanted)):
                actions.append(fix)
            else:
                conflicts.append(f"meta.replay 里找不到唯一一处 {current!r}，未改写")
    elif target.is_file():
        if current != wanted and (fix := meta_action(run_dir, current, wanted)):
            actions.append(fix)
    else:
        conflicts.append("没有可归档的回放（match.replay 与 replay/<run>.replay 都不存在）")

    replay_dir = run_dir / "replay"
    for suffix in EXPORTS:
        legacy = replay_dir / f"match{suffix}"
        current_export = replay_dir / f"{name}{suffix}"
        if not legacy.is_file():
            continue
        if not current_export.exists():
            actions.append({"kind": "move", "from": legacy, "to": current_export})
        elif same_file(legacy, current_export):
            actions.append({"kind": "drop", "path": legacy, "reason": "解析产物已是同一份"})
        else:
            conflicts.append(f"两份解析产物内容不同：{legacy.name} 与 {current_export.name}")

    report = case_dir / "reports" / f"{name}.html"
    report_target = run_dir / "eval" / "report-full.html"
    if report.is_file():
        if not report_target.exists():
            actions.append({"kind": "move", "from": report, "to": report_target})
        elif same_file(report, report_target):
            actions.append({"kind": "drop", "path": report, "reason": "逐局 HTML 已收进材料目录"})
        else:
            conflicts.append("两份逐局 HTML 内容不同：reports/<run>.html 与 eval/report-full.html")
    # `render_run` writes a sibling link to `index.html`; from `eval/` the summary is two levels up.
    html_source = report_target if report_target.is_file() else (report if report.is_file() else None)
    if html_source and 'href="index.html"' in html_source.read_text(encoding="utf-8"):
        actions.append({"kind": "rewrite", "path": report_target,
                        "old": 'href="index.html"', "new": 'href="../../reports/index.html"'})

    root_replay = REPLAYS / f"{name}.replay"
    if root_replay.is_file():
        # The archived copy may still be `match.replay` at plan time; compare against whichever
        # copy will end up at `replay/<run>.replay` so the twin is dropped in the same pass.
        archived = target if target.is_file() else source
        if archived.is_file() and same_file(root_replay, archived):
            actions.append({"kind": "drop", "path": root_replay, "reason": "归档副本已在 replay/<run>.replay"})
        elif not target.is_file() and not source.is_file():
            # Only one copy exists and this run has no replay at all: moving it in is not a guess.
            actions.append({"kind": "move", "from": root_replay, "to": target})
            if (fix := meta_action(run_dir, current, wanted)):
                actions.append(fix)
        else:
            conflicts.append(f"根目录回放与归档副本不同或无法配对：{root_replay.name}")

    return {"case": case_dir.name, "run": name, "actions": actions, "conflicts": conflicts}


def index_updates(case_dir: Path) -> list[dict]:
    """Repoint the per-case summary page at the HTML that now lives inside each run folder."""
    index = case_dir / "reports" / "index.html"
    if not index.is_file():
        return []
    text = index.read_text(encoding="utf-8")
    updated = text
    for run_dir in sorted(p for p in case_dir.iterdir() if p.is_dir()):
        if run_dir.name in NON_RUN:
            continue
        old = f'href="{run_dir.name}.html"'
        new = f'href="../{run_dir.name}/eval/report-full.html"'
        updated = updated.replace(old, new)
    if updated == text:
        return []
    return [{"kind": "rewrite", "path": index, "text": updated}]


def collect(case_filter: str | None) -> list[dict]:
    plans = []
    if not MICRO.is_dir():
        return plans
    for case_dir in sorted(p for p in MICRO.iterdir() if p.is_dir()):
        if case_dir.name in NON_RUN or case_dir.name.startswith("_"):
            continue
        if case_filter and case_dir.name != case_filter:
            continue
        for run_dir in sorted(p for p in case_dir.iterdir() if p.is_dir()):
            if run_dir.name in NON_RUN or not (run_dir / "meta.json").is_file():
                continue
            plans.append(plan_run(case_dir, run_dir))
        for action in index_updates(case_dir):
            plans.append({"case": case_dir.name, "run": "(reports/index.html)", "actions": [action], "conflicts": []})
    return plans


def known_runs() -> set[str]:
    return {plan["run"] for plan in collect(None)}


def orphan_root_replays() -> list[Path]:
    if not REPLAYS.is_dir():
        return []
    runs = known_runs()
    return [
        path
        for path in sorted(REPLAYS.glob("*.replay"))
        if path.stem.startswith("CASE") and path.stem not in runs
    ]


def apply_actions(plan: dict) -> list[dict]:
    done = []
    for action in plan["actions"]:
        try:
            kind = action["kind"]
            if kind == "move":
                action["to"].parent.mkdir(parents=True, exist_ok=True)
                action["from"].rename(action["to"])
            elif kind == "drop":
                action["path"].unlink()
            elif kind == "meta":
                text = action["path"].read_text(encoding="utf-8")
                action["path"].write_text(text.replace(action["old"], action["new"]), encoding="utf-8")
            elif kind == "rewrite":
                if "text" in action:
                    action["path"].write_text(action["text"], encoding="utf-8")
                else:
                    text = action["path"].read_text(encoding="utf-8")
                    if action["old"] in text:
                        action["path"].write_text(text.replace(action["old"], action["new"]), encoding="utf-8")
            done.append({**action, "ok": True})
        except OSError as exc:
            done.append({**action, "ok": False, "error": str(exc)})
    return done


def describe(action: dict) -> str:
    relative = lambda value: str(value.relative_to(ROOT)).replace("\\", "/")
    if action["kind"] == "move":
        return f"move    {relative(action['from'])} -> {relative(action['to'])}"
    if action["kind"] == "drop":
        return f"drop    {relative(action['path'])}    ({action['reason']})"
    if action["kind"] == "meta":
        return f"meta    {relative(action['path'])}    replay {action['from']} -> {action['to']}"
    if action["kind"] == "rewrite":
        if "text" in action:
            return f"rewrite {relative(action['path'])}    汇总页链接 -> 各局 eval/report-full.html"
        return f"rewrite {relative(action['path'])}    {action['old']} -> {action['new']}"
    return action["kind"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform the plan (default: dry run)")
    parser.add_argument("--case", help="only this CASE directory, e.g. CASE1-duel")
    parser.add_argument("--json", action="store_true", help="emit the plan as JSON")
    args = parser.parse_args(argv)

    plans = collect(args.case)
    if not plans:
        print("no micro runs found", file=sys.stderr)
        return 2

    for plan in plans:
        for conflict in plan["conflicts"]:
            print(f"CONFLICT {plan['case']}/{plan['run']}: {conflict}", file=sys.stderr)

    if args.json:
        payload = [{**plan, "actions": [describe(a) for a in plan["actions"]]} for plan in plans]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        pending = 0
        for plan in plans:
            if not plan["actions"]:
                continue
            print(f"{plan['case']}/{plan['run']}")
            for action in plan["actions"]:
                pending += 1
                print(f"   {describe(action)}")
        print(f"\n{len(plans)} 条计划记录，待执行 {pending} 项动作。")
        if not args.apply:
            print("[dry run] 确认后加 --apply 执行。")

    if not args.apply:
        return 0

    applied = 0
    failed = 0
    for plan in plans:
        for action in apply_actions(plan):
            applied += 1
            if not action.get("ok"):
                failed += 1
                print(f"FAILED {describe(action)}: {action.get('error')}", file=sys.stderr)
    print(f"applied {applied} actions, {failed} failed.")
    for orphan in orphan_root_replays():
        print(f"ORPHAN  replays/{orphan.name} 没有对应 run 目录，保留未动", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
