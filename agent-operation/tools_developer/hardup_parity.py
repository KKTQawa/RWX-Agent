"""Deploy, run and collect the five-model Hard-up comparison on WSL and the training server."""

import argparse
import concurrent.futures
import hashlib
import json
import os
import random
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path


HARD = "rwx.original.hard"
VERY_HARD = "rwx.original.very-hard"
CANDIDATE = "rwx.ai-rl-hard"
JDK = "jdk-25.0.5+8"
SERVER_ROOT = "/home/aqf/codes/rwx-rl"
JARS = ("libs-core-1.1.4.jar", "desktop-1.1.4.jar")
GROUPS = ("duel19", "duel-non2p", "team-full")
MODELS = {
    "hard": None,
    "v1": "params_Hardupv1.json",
    "v2": "params_Hardupv2.json",
    "v3": "params_Hardupv3.json",
    "v1-gen200": "mean_gen0200.json",
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    with path.open("rb") as file:
        checksum = hashlib.sha256()
        for block in iter(lambda: file.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def pool_maps(path):
    maps = read(path)["maps"]
    for item in maps:
        file = Path(item["map"])
        if file.name == "(4p)_Core of the Power_[byercer].tmx":
            item["map"] = str(file.with_name("(4p)_Core of the Power_[by Mercer].tmx")).replace("\\", "/")
        tag = re.search(r"(?i)(?<!\d)(\d+)p(?![a-z0-9])|\[(\d+)\]", item["name"] + " " + file.name)
        if not tag and item["name"] != "火桥F":
            raise ValueError(f"Cannot identify map capacity: {item}")
        item["capacity"] = int(next(group for group in tag.groups() if group)) if tag else 2
    return maps


def schedule(maps, group, seed, team=False):
    rng = random.Random(seed)
    order = maps[:]
    rng.shuffle(order)
    cells = []
    visits = Counter()
    for item in order:
        pairs = [list(range(1, item["capacity"] + 1))] if team else item["pairs"]
        cells.extend((item, pair) for pair in pairs)
        visits[item["name"]] = len(pairs)
    while len(cells) < 50:
        item = min(order, key=lambda entry: visits[entry["name"]])
        pairs = [list(range(1, item["capacity"] + 1))] if team else item["pairs"]
        cells.append((item, pairs[visits[item["name"]] % len(pairs)]))
        visits[item["name"]] += 1
    assert len(cells) == 50
    rng.shuffle(cells)
    specs = []
    for index, (item, seats) in enumerate(cells):
        game_seed = rng.randrange(1, 2_000_000_000)
        for arm in (0, 1):
            specs.append({
                "id": f"{group}-{index:02d}-{arm}",
                "group": group, "map": item["map"], "map_name": item["name"],
                "capacity": item["capacity"], "seats": seats,
                "mine": seats[arm::2], "seed": game_seed,
            })
    return specs


def prepare(repo, root):
    inputs = root / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    origin = repo / "evaluate" / "RL" / "AI Hard-up"
    shutil.copytree(repo / "assets", root / "assets", dirs_exist_ok=True)
    if (repo / "mods" / "units").is_dir():
        shutil.copytree(repo / "mods" / "units", root / "mods" / "units", dirs_exist_ok=True)
    for name, source in MODELS.items():
        if source:
            base = origin if name != "v1-gen200" else origin / "runs" / "cma-g3" / "params"
            shutil.copyfile(base / source, inputs / source)
    pool19 = pool_maps(origin / "completition_v1-19.json")
    pool_full = pool_maps(origin / "completition.json")
    assert len(pool19) == 19
    pool_non2 = [item for item in pool19 if item["capacity"] > 2]
    pool_team = [item for item in pool_full
                 if item["capacity"] > 2 and "环湖绝对平衡" not in item["name"]]
    pools = {"duel19": pool19, "duel-non2p": pool_non2, "team-full": pool_team}
    specs = [
        *schedule(pool19, "duel19", 202611231),
        *schedule(pool_non2, "duel-non2p", 202611232),
        *schedule(pool_team, "team-full", 202611233, team=True),
    ]
    write(inputs / "pools.json", pools)
    write(inputs / "schedule.json", specs)
    for path in sorted({item["map"] for entries in pools.values() for item in entries}):
        source = repo / path
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        # TMX references absent from the map folder resolve against the frozen asset tree.
        for node in ET.parse(source).getroot().iter():
            ref = node.get("source")
            if ref and (source.parent / ref).is_file():
                extra = (target.parent / ref).resolve()
                if root not in extra.parents:
                    raise ValueError(f"Map dependency escapes snapshot: {path} {ref}")
                extra.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source.parent / ref, extra)
    for group, entries in pools.items():
        sizes = Counter(len(spec["mine"]) for spec in specs if spec["group"] == group)
        print(f"{group}: {len(entries)} maps, {dict(sizes)} games by team size", flush=True)


def match_row(model, match):
    mine = [spawn - 1 for spawn in match["mine"]]
    return {
        **match, "model": model, "winCondition": "commandCenter",
        "perspective": {"mode": "team", "slot": mine[0], "teamId": mine[0]},
    }


def checked_result(result, row, tick_limit, seconds, attempt, *, roster=None):
    mine = {spawn - 1 for spawn in row["mine"]}
    opponents = {spawn - 1 for spawn in row["seats"]} - mine
    view = result["perspective"]
    expected = row["perspective"]
    if any(view.get(key) != value for key, value in expected.items()):
        raise ValueError(f"perspective mismatch: {view} expected {expected}")
    if set(view["allies"]) != mine or set(view["enemies"]) != opponents:
        raise ValueError(f"incorrect participants: {view}")
    teams = {team["teamId"]: team for team in result["teams"]}
    if set(teams) != mine | opponents:
        raise ValueError(f"incorrect final teams: {teams.keys()}")
    if result["winCondition"] != "commandCenter" or result["effective"]["incomeMultiplier"] != 2:
        raise ValueError("unexpected effective rules")
    difficulty = {HARD: 1, VERY_HARD: 2, CANDIDATE: 20}
    for team, record in teams.items():
        code = (difficulty[roster[team + 1]] if roster is not None else
                20 if row["model"] != "hard" and team in mine else 1)
        if record["aiDifficulty"] != code:
            raise ValueError(f"incorrect configured AI: {record}")
    outcome = result["outcome"]
    ticks = result["ticks"]
    losers = opponents if outcome == "victory" else mine if outcome == "defeat" else set()
    if any(teams[team]["commandCenters"] != 0 for team in losers):
        raise ValueError("decisive result with a losing-side command center still alive")
    if any("commandCenters" not in team for team in teams.values()):
        raise ValueError("result did not report live command centers")
    if tick_limit == 1000 and any(team["commandCenters"] < 1 for team in teams.values()):
        raise ValueError("smoke match participant has no command center")
    if outcome in ("active", "draw", "max-ticks") and ticks < tick_limit:
        raise ValueError(f"non-decisive match ended before tick limit: {outcome} {ticks}/{tick_limit}")
    if outcome not in ("active", "draw", "max-ticks", "victory", "defeat"):
        raise ValueError(f"unexpected outcome: {outcome}")
    return {**row, "outcome": {"victory": "win", "defeat": "loss"}.get(outcome, "draw"),
            "ticks": ticks, "teams": result["teams"], "perspective": view,
            "seconds": seconds, "attempts": attempt}


def run_match(root, runtime, scratch, model, match, tick_limit, failures, *,
              roster=None, config=None, processors=2):
    mine = [spawn - 1 for spawn in match["mine"]]
    opponents = [spawn - 1 for spawn in match["seats"] if spawn not in match["mine"]]
    seats = sorted(mine + opponents)
    if config is None:
        config = MODELS[model] or MODELS["v1"]
    if roster is None:
        roster = {team + 1: CANDIDATE if model != "hard" and team in mine else HARD
                  for team in seats}
    result_row = match_row(model, match)
    started = time.monotonic()
    for attempt in range(1, 3):
        with tempfile.TemporaryDirectory(dir=scratch, prefix="rwx-") as name:
            out = Path(name)
            spec = {
                "schema": "rwx-rollout-v1", "out": str(out), "map": str(root / match["map"]),
                "teams": [{"slot": index, "spawn": team_id + 1, "side": int(team_id not in mine),
                           "ai": roster[team_id + 1],
                           "name": f"p{team_id + 1}"} for index, team_id in enumerate(seats)],
                "room": {"incomeMultiplier": 2.0, "seed": match["seed"]},
                "limits": {"maxTicks": tick_limit, "maxWallSeconds": 1200},
                "perspective": {"mode": "team", "slot": mine[0]},
                "record": False, "telemetry": False, "winCondition": "commandCenter",
                "aiConfig": str(root / "inputs" / config),
            }
            write(out / "spec.json", spec)
            command = [
                str(runtime / JDK / "bin" / "java"), "-Xms128m", "-Xmx1024m",
                f"-XX:ActiveProcessorCount={processors}", "-Dfile.encoding=UTF-8",
                "--enable-native-access=ALL-UNNAMED", "--sun-misc-unsafe-memory-access=allow",
                "-Dorg.lwjgl.opengl.contextAPI=native",
                f"-Drwx.repoDir={root}", f"-Drwx.assetsDir={root / 'assets'}",
                "-cp", str(runtime / "lib" / "*"), "io.github.rwx.DesktopMain",
                "--no-steam", f"--rollout-config={out / 'spec.json'}", f"--data-dir={out}",
            ]
            try:
                with (out / "stdout.log").open("wb") as log:
                    process = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                             timeout=1240)
                if process.returncode not in (0, 3):
                    raise ValueError(f"Java exit code {process.returncode}")
                return checked_result(read(out / "result.json"), match_row(model, match), tick_limit,
                                      round(time.monotonic() - started, 2), attempt, roster=roster)
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                for file in ("spec.json", "stdout.log", "result.json"):
                    if (out / file).is_file():
                        shutil.copyfile(out / file, failures / f"{model}-{match['id']}-{attempt}-{file}")
                result_row["error"] = f"{type(error).__name__}: {error}"
    return {**result_row, "outcome": "error", "seconds": round(time.monotonic() - started, 2),
            "attempts": 2}


def existing(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run(root, runtime, state, workers, smoke):
    state.mkdir(parents=True, exist_ok=True)
    failures = state / "failures"
    failures.mkdir(exist_ok=True)
    scratch = Path(os.environ.get("TMPDIR", "/tmp"))
    specs = read(root / "inputs" / "schedule.json")
    order = list(MODELS)
    rng = random.Random(20261123)
    rng.shuffle(specs)
    filename = "smoke.jsonl" if smoke else "games.jsonl"
    path = state / filename
    prior = {(row["model"], row["id"]): row for row in existing(path)}
    done = {key for key, row in prior.items() if row["outcome"] != "error"}
    if smoke:
        teams = {spec["map"]: spec for spec in specs if spec["group"] == "team-full" and spec["id"].endswith("-1")}
        jobs = [("v3", spec) for spec in teams.values()]
        duel = next(spec for spec in specs if spec["group"] == "duel19" and min(spec["seats"]) > 2)
        jobs.extend((model, duel) for model in order)
    else:
        jobs = [(model, spec) for spec in specs for model in order]
    todo = [(model, spec) for model, spec in jobs if (model, spec["id"]) not in done]
    print(f"start {len(todo)} remaining / {len(jobs)} total, workers={workers}", flush=True)
    with path.open("a", encoding="utf-8", buffering=1) as output:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            pending = [executor.submit(run_match, root, runtime, scratch, model, spec,
                                       1000 if smoke else 337500, failures) for model, spec in todo]
            count = Counter()
            for index, future in enumerate(concurrent.futures.as_completed(pending), len(jobs) - len(todo) + 1):
                row = future.result()
                output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                count[row["outcome"]] += 1
                if index % 15 == 0 or smoke or row["outcome"] == "error" or index == len(jobs):
                    print(f"{index}/{len(jobs)} {dict(count)} {row['model']} {row['map_name']} "
                          f"{row.get('error', '')}", flush=True)
    report(path, state / ("smoke-summary.json" if smoke else "summary.json"))
    if count["error"]:
        raise SystemExit(1)


def report(path, output):
    rows = {(row["model"], row["id"]): row for row in existing(path)}.values()
    groups = {}
    for row in rows:
        bucket = groups.setdefault(row["model"], {}).setdefault(row["group"], [])
        bucket.append(row)
    summary = {}
    for model, model_groups in groups.items():
        summary[model] = {}
        for group, bucket in model_groups.items():
            counts = Counter(row["outcome"] for row in bucket)
            valid = [row for row in bucket if row["outcome"] != "error"]
            summary[model][group] = {
                **summarize(valid), "errors": counts["error"],
                "by_map": {name: summarize([row for row in valid if row["map_name"] == name])
                           for name in sorted({row["map_name"] for row in valid})},
            }
            if group == "team-full":
                summary[model][group]["by_team_size"] = {
                    f"{size}v{size}": summarize([row for row in valid if len(row["mine"]) == size])
                    for size in sorted({len(row["mine"]) for row in valid})
                }
    write(output, summary)
    return summary


def summarize(rows):
    counts = Counter(row["outcome"] for row in rows)
    count = len(rows)
    return {"wins": counts["win"], "draws": counts["draw"], "losses": counts["loss"], "valid": count,
            "win_rate": counts["win"] / count if count else None,
            "median_ticks": statistics.median(row["ticks"] for row in rows) if count else None}


def manifest(root, runtime):
    for base, dirs in ((root, ("assets", "mods", "inputs")), (runtime, ("lib", JDK))):
        for directory in dirs:
            for file in sorted((base / directory).rglob("*"), key=lambda item: item.relative_to(base).as_posix()):
                if file.is_file():
                    print(f"{sha(file)}  {file.relative_to(base).as_posix()}")


def finished(log):
    return log.is_file() and log.read_text(encoding="utf-8").rstrip().split("\n")[-1].startswith("complete ")


def launch(args):
    args.state.mkdir(parents=True, exist_ok=True)
    session = f"rwx-{args.name}"
    if finished(args.state / "run.log") or subprocess.run(
        ["tmux", "has-session", "-t", f"={session}"], capture_output=True
    ).returncode == 0:
        return
    command = shlex.join([
        sys.executable, "-B", str(Path(__file__).resolve()), "batch",
        "--root", str(args.root.resolve()), "--runtime", str(args.runtime.resolve()),
        "--state", str(args.state.resolve()), "--workers", str(args.workers),
    ])
    command += " >> " + shlex.quote(str(args.state.resolve() / "run.log")) + " 2>&1"
    subprocess.run(["tmux", "new-session", "-d", "-s", session, command], check=True)


def batch(args):
    for retry in range(3):
        try:
            run(args.root.resolve(), args.runtime.resolve(), args.state.resolve(), args.workers, smoke=False)
        except SystemExit as error:
            print(f"sweep {retry + 1}: {error}", flush=True)
        else:
            print(f"complete {datetime.now().isoformat()}", flush=True)
            return
    print(f"failed {datetime.now().isoformat()}", flush=True)
    raise SystemExit(1)


def load_ssh(repo):
    sys.path.insert(0, str(repo / "agent-tmp"))
    import srv
    return srv


def remote_run(ssh, command):
    code, stdout, stderr = ssh.run(command, timeout=1800, quiet=True)
    if code:
        raise RuntimeError(f"Server command failed ({code})\n{stdout}\n{stderr}")
    return stdout.strip()


def wsl_path(path):
    return f"/mnt/{path.drive[0].lower()}/" + Path(*path.parts[1:]).as_posix()


def wsl_run(distro, output, command):
    with tempfile.NamedTemporaryFile(dir=output, suffix=".sh", delete=False) as file:
        script = Path(file.name)
        file.write(("set -eu\n" + command + "\n").encode("utf-8"))
    try:
        return subprocess.check_output(["wsl.exe", "-d", distro, "--", "bash", wsl_path(script)],
                                       encoding="utf-8", errors="replace").strip()
    finally:
        script.unlink()


def deploy(args):
    repo = args.repo.resolve()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,58}", args.name):
        raise ValueError("Invalid run name")
    output = repo / "evaluate" / "RL" / "out" / args.name
    output.mkdir(parents=True, exist_ok=True)
    remote = f"{args.server_root}/runs/{args.name}"
    local = f'$HOME/{args.name}'
    quote = shlex.quote
    ssh = load_ssh(repo)
    out_wsl = quote(wsl_path(output))
    entry = "python3 -B hardup_parity.py"
    shared = "--root input-tree --runtime runtime"

    def local_call(action):
        return wsl_run(args.distro, output, f'cd "{local}"\n{entry} {action} {shared} '
                       f"--state {out_wsl}/local --workers {args.local_workers} --name {args.name}")

    def server_call(action):
        return remote_run(ssh, f"cd {quote(remote)} && {entry} {action} {shared} "
                          f"--state results --workers {args.server_workers} --name {args.name}")

    local_manifest = output / "local-manifest.sha256"
    server_manifest = output / "server-manifest.sha256"
    if args.resume:
        if not local_manifest.is_file() or local_manifest.read_bytes() != server_manifest.read_bytes():
            raise ValueError("No verified snapshot to resume")
    else:
        if (output / "local" / "run.log").is_file():
            raise ValueError("Run name already started. Use --resume or choose a different name")
        if not args.skip_build:
            subprocess.run(["cmd.exe", "/c", "gradlew.bat", ":core:test", ":desktop:headlessDist",
                            "--console=plain"], cwd=repo, check=True)
        prepare(repo, output / "input-tree")
        archive = output / "inputs.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(output / "input-tree", arcname="input-tree")
            tar.add(Path(__file__).resolve(), arcname="hardup_parity.py")
            for jar in JARS:
                tar.add(repo / "desktop/build/headless/lib" / jar, arcname=f"overlay/{jar}")
        remote_run(ssh, f"mkdir -p {quote(remote)} && test ! -f {quote(remote + '/results/run.log')}")
        local_runtime = args.runtime_cache.resolve() if args.runtime_cache else output / "runtime.tar.gz"
        remote_runtime = args.server_runtime_cache or f"{remote}/runtime.tar.gz"
        if not local_runtime.is_file():
            if not args.server_runtime_cache:
                remote_run(ssh, f"cd {quote(args.server_root)} && tar -czf {quote(remote_runtime)} lib {JDK}")
            ssh.get(remote_runtime, str(local_runtime))
        if sha(local_runtime) != remote_run(ssh, f"sha256sum {quote(remote_runtime)}").split()[0]:
            raise ValueError("Cached runtime archives differ")
        ssh.put(str(archive), f"{remote}/inputs.tar.gz")

        def unpack(cache, manifest_path):
            return ("tar -xzf inputs.tar.gz\nmkdir -p runtime\n"
                    f"tar -xzf {quote(cache)} -C runtime\ncp overlay/*.jar runtime/lib/\n"
                    f"{entry} manifest {shared} > {manifest_path}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            stage_local = pool.submit(wsl_run, args.distro, output,
                                      f'mkdir -p "{local}"\ncd "{local}"\ncp {out_wsl}/inputs.tar.gz .\n'
                                      + unpack(wsl_path(local_runtime), f"{out_wsl}/local-manifest.sha256"))
            stage_server = pool.submit(remote_run, ssh, f"set -eu\ncd {quote(remote)}\n"
                                       + unpack(remote_runtime, "manifest.sha256"))
            stage_local.result()
            stage_server.result()
        ssh.get(f"{remote}/manifest.sha256", str(server_manifest))
        if local_manifest.read_bytes() != server_manifest.read_bytes():
            raise ValueError("Game binaries, runtime or inputs differ across machines")
        print(f"Matched input manifest {sha(local_manifest)}", flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            smokes = [pool.submit(local_call, "smoke"), pool.submit(server_call, "smoke")]
            for smoke in smokes:
                print(smoke.result(), flush=True)
    local_call("launch")
    server_call("launch")
    with (output / "collect.log").open("ab") as log:
        subprocess.Popen([sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()), "collect",
                          "--repo", str(repo), "--state", str(output), "--remote-dir", remote],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    print(f"Started rwx-{args.name} on both machines. Results: {output}", flush=True)


def collect(args):
    from paramiko import SSHException

    ssh = load_ssh(args.repo.resolve())
    server = args.state / "server"
    server.mkdir(exist_ok=True)
    local_log = args.state / "local/run.log"
    remote_log = server / "run.log"
    while True:
        try:
            with ssh.client() as client, client.open_sftp() as transfer:
                with transfer.open(f"{args.remote_dir}/results/run.log") as file:
                    remote_log.write_bytes(file.read())
                if finished(remote_log) and not (server / "games.jsonl").is_file():
                    for filename in ("summary.json", "smoke.jsonl", "games.jsonl"):
                        pending = server / f"{filename}.part"
                        transfer.get(f"{args.remote_dir}/results/{filename}", str(pending))
                        pending.replace(server / filename)
        except (OSError, EOFError, SSHException) as error:
            print(f"Server read retry: {error}", flush=True)
        for log in (local_log, remote_log):
            if log.is_file() and log.read_text(encoding="utf-8").rstrip().split("\n")[-1].startswith("failed "):
                raise RuntimeError(f"Evaluation stopped with unsuccessful jobs: {log}")
        if finished(local_log) and (server / "games.jsonl").is_file():
            compare(args.state)
            return
        time.sleep(60)


def compare(state):
    specs = {spec["id"]: spec for spec in read(state / "input-tree/inputs/schedule.json")}
    expected = {(model, spec) for model in MODELS for spec in specs}
    results = {}
    for site in ("local", "server"):
        output = state / site
        rows = {(row["model"], row["id"]): row for row in existing(output / "games.jsonl")}
        if len(rows) != 1500 or set(rows) != expected:
            raise ValueError(f"Incomplete fixed schedule: {site}")
        for (_, spec_id), row in rows.items():
            if row["outcome"] not in ("win", "loss", "draw") or any(
                row[key] != value for key, value in specs[spec_id].items()
            ):
                raise ValueError(f"Invalid game: {site} {row['model']} {spec_id}")
            losing = (row["perspective"]["enemies"] if row["outcome"] == "win"
                      else row["perspective"]["allies"] if row["outcome"] == "loss" else ())
            if any(team["commandCenters"] for team in row["teams"] if team["teamId"] in losing):
                raise ValueError(f"Incorrect team defeat: {site} {row['model']} {spec_id}")
        results[site] = report(output / "games.jsonl", output / "summary.json")
    write(state / "comparison.json", results)
    print(f"Completed comparison: {state / 'comparison.json'}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("deploy", "collect", "prepare", "smoke", "run", "batch",
                                         "launch", "report", "manifest", "compare"))
    parser.add_argument("--root", type=Path, default=Path("input-tree"))
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--local-workers", type=int, default=5)
    parser.add_argument("--server-workers", type=int, default=10)
    parser.add_argument("--server-root", default=SERVER_ROOT)
    parser.add_argument("--remote-dir")
    parser.add_argument("--distro", default="Ubuntu-22.04")
    parser.add_argument("--name", default="hardup-five-parity-cc")
    parser.add_argument("--runtime-cache", type=Path)
    parser.add_argument("--server-runtime-cache")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.mode == "deploy":
        deploy(args)
    elif args.mode == "collect":
        collect(args)
    elif args.mode == "compare":
        compare(args.state.resolve())
    elif args.mode == "prepare":
        prepare(args.repo.resolve(), root)
    elif args.mode == "manifest":
        manifest(root, args.runtime.resolve())
    elif args.mode == "report":
        report(args.state / "games.jsonl", args.state / "summary.json")
    elif args.mode == "launch":
        launch(args)
    elif args.mode == "batch":
        batch(args)
    else:
        run(root, args.runtime.resolve(), args.state.resolve(), args.workers, args.mode == "smoke")


if __name__ == "__main__":
    main()
