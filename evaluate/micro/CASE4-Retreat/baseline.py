"""Play a CASE4-Retreat baseline through the game's public order commands."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
POLL_SECONDS = 0.5
RETREAT_RATIO = 0.65
FULL_RATIO = 0.999
REPAIR_RANGE = 230


class CommandError(RuntimeError):
    pass


class Client:
    def __init__(self, port_file):
        self.process = subprocess.Popen(
            [sys.executable, str(ROOT / "agent-operation/tools/rwx-cli.py"),
             "--port-file", str(port_file), "--stdio"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", cwd=ROOT)

    def call(self, command):
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise EOFError("Case CLI closed")
        reply = json.loads(line)
        if reply["error"]:
            raise CommandError(reply["reply"])
        data = reply["reply"]
        return json.loads(data) if data.startswith("{") else data

    def close(self):
        try:
            self.process.stdin.close()
        except BrokenPipeError:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        finally:
            self.process.stdout.close()


def position(unit):
    return unit["x"], unit["y"]


def units(client, owner):
    return client.call(f"rwx-game-unit-list --owner {owner} --full --json")["units"]


def point_order(action, unit_id, point):
    x, y = point
    return f"rwx-game-order-{action} --units {unit_id} --x {x:.2f} --y {y:.2f}"


def following(tank, order, point):
    x, y = tank.get("waypointX"), tank.get("waypointY")
    return tank.get("order") == order and x is not None and y is not None and math.dist((x, y), point) < 2


def play(client, meta, destroyed_file, result_path):
    homes = {tank["id"]: position(tank) for tank in meta["tanks"]}
    targets = {turret["id"]: turret for turret in meta["turrets"]}
    returning = set()
    state = client.call("rwx-micro-4-state --json")
    if state["task"] != meta["task"]:
        raise ValueError("The CLI and meta.json refer to different CASE4 tasks")
    if state["phase"] == "briefing":
        client.call("rwx-micro-4-begin")
    while not result_path.exists():
        state = client.call("rwx-micro-4-state --json")
        if state["phase"] == "ended":
            return
        own = units(client, "self")
        enemies = {unit["id"] for unit in units(client, "enemy")}
        # Read after the observations so a turret that just died drops out before target selection.
        # This stream is append-only and contains at most one small record per turret.
        for line in destroyed_file.read_text(encoding="utf-8").splitlines(keepends=True):
            if line.endswith("\n"):
                targets.pop(json.loads(line).get("turretId"), None)
        bays = [position(unit) for unit in own if unit["type"] == "repairbay"]
        for tank in own:
            unit_id = tank["id"]
            if unit_id not in homes or not targets:
                continue
            point = position(tank)
            hp_ratio = tank["hp"] / tank["maxHp"]
            if hp_ratio < RETREAT_RATIO:
                returning.add(unit_id)
            if unit_id in returning:
                if hp_ratio >= FULL_RATIO:
                    returning.remove(unit_id)
                else:
                    home = homes[unit_id]
                    if bays and not any(math.dist(home, bay) < REPAIR_RANGE for bay in bays):
                        home = min(bays, key=lambda bay: math.dist(point, bay))
                    if math.dist(point, home) > 18 and not following(tank, "move", home):
                        submit(client, point_order("move", unit_id, home))
                    continue

            # Commit to a live attack target until it dies or the tank needs to retreat.
            if tank.get("order") == "attack" and tank.get("targetId") in targets:
                continue
            target = min(targets.values(), key=lambda turret: (math.dist(point, position(turret)), turret["id"]))
            target_id = target["id"]
            if target_id in enemies:
                submit(client, f"rwx-game-order-attack --units {unit_id} --target {target_id}")
            elif not following(tank, "attackMove", position(target)):
                submit(client, point_order("attack-move", unit_id, position(target)))
        time.sleep(POLL_SECONDS)


def submit(client, command):
    try:
        client.call(command)
    except CommandError as error:
        # Unit lists and orders run on different ticks. A tank or target may die between them.
        if not any(reason in str(error) for reason in ("target_not_visible", "unit_not_owned", "not_running")):
            raise
        return
    print(command, flush=True)


def read_result(path):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.1)
    raise RuntimeError(f"CASE4 ended without a readable result: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port-file", type=Path, required=True)
    parser.add_argument("--meta-file", type=Path, required=True, help="the current run's private meta.json")
    args = parser.parse_args()
    meta = json.loads(args.meta_file.read_text(encoding="utf-8-sig"))
    result_path = args.meta_file.with_name("result.json")
    if result_path.exists():
        parser.error("--meta-file must refer to a live run")
    destroyed_file = args.meta_file.parent / "engine" / "turret_destroyed.jsonl"
    client = Client(args.port_file)
    try:
        play(client, meta, destroyed_file, result_path)
    except (EOFError, BrokenPipeError, ConnectionError):
        # The headless engine closes the CLI on exit. The recorded result decides success.
        pass
    finally:
        client.close()
    result = read_result(result_path)
    print(json.dumps({key: result[key] for key in (
        "outcome", "endReason", "gameMs", "turretsAlive", "turretsTotal", "tanksAlive")}), flush=True)
    return 0 if result["outcome"] == "success" and result["turretsAlive"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
