"""CASE4-Retreat baseline for every type and level.

The baseline is allowed to read the case's private turret layout (`--meta-file`), so it does not
depend on fog for target selection. It still issues real engine commands and does not teleport or
edit units.

Deterministic per-tank policy:

1. remember each tank's starting position as its home/repair point;
2. process every tank independently each 2 s cycle:
   - re-engage only at full HP while inside a repair bay;
   - once engaged, keep attacking until HP < 60 %, then return home and wait for the next
     full-HP cycle;
3. known turrets come from `meta["turrets"]`; visible ones get `order-attack`, hidden ones get
   `order-attack-move` to their exact coordinates;
4. the loop ends when `state` reports the goal as reached or the case ends.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
POLL_SECONDS = 2.0
RETREAT_HP_RATIO = 0.60
FULL_HP_EPSILON = 0.001
IN_BAY_RANGE = 220.0
HOME_EPSILON = 30.0
BAY_TYPE = "repairbay"


class Client:
    def __init__(self, port_file):
        self.process = subprocess.Popen(
            [sys.executable, str(ROOT / "agent-operation/tools/rwx-cli.py"), "--port-file", str(port_file), "--stdio"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", cwd=ROOT)

    def call(self, command):
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise EOFError("Case process ended; use result.json for outcome")
        reply = json.loads(line)
        if reply["error"]:
            raise RuntimeError(reply["reply"])
        data = reply["reply"]
        return json.loads(data) if data.startswith("{") else data

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=5)
        self.process.stdout.close()


def try_call(client, command):
    try:
        return client.call(command)
    except RuntimeError as error:
        print(json.dumps({"skipped": str(error), "command": command}), flush=True)
        return None


def own_units(client):
    return client.call("rwx-game-unit-list --owner self --full --json")["units"]


def visible_enemies(client):
    return client.call("rwx-game-unit-list --owner enemy --full --json")["units"]


def load_meta(path):
    if path is None:
        return {"tankType": "bugMeleeT31", "turrets": []}
    with open(path, encoding="utf-8-sig") as stream:
        return json.load(stream)


def load_turrets(meta):
    return [{"id": row["id"], "x": row["x"], "y": row["y"], "type": row.get("type")}
            for row in meta.get("turrets", [])]


def destroyed_ids(path):
    found = set()
    if path is None or not path.exists():
        return found
    try:
        with open(path, encoding="utf-8-sig") as stream:
            for line in stream:
                line = line.strip()
                if line:
                    row = json.loads(line)
                    if "turretId" in row:
                        found.add(row["turretId"])
    except (OSError, ValueError):
        pass
    return found


def play(client, tank_type, turrets, destroyed_path):
    state = client.call("rwx-micro-4-state --json")
    if state.get("phase") == "briefing":
        print(json.dumps({"begin": client.call("rwx-micro-4-begin")}), flush=True)
    homes = {}  # tank id -> the position where it started (inside the repair bays)
    engaged = set()  # tanks already allowed to keep fighting until HP < 60 %
    known = [dict(row) for row in turrets]  # current turrets, from the private layout
    while True:
        state = client.call("rwx-micro-4-state --json")
        if state.get("phase") == "ended" or (state.get("goal") or {}).get("reached"):
            return
        dead = destroyed_ids(destroyed_path)
        if dead:
            known = [row for row in known if row["id"] not in dead]
        units = own_units(client)
        tanks = [unit for unit in units if unit.get("type") == tank_type]
        bays = [unit for unit in units if unit.get("type") == BAY_TYPE]
        if not tanks or not bays:
            time.sleep(POLL_SECONDS)
            continue
        visible = [unit for unit in visible_enemies(client) if "turret" in (unit.get("type") or "")]
        visible_ids = {unit["id"] for unit in visible}
        for tank in sorted(tanks, key=lambda unit: unit["id"]):
            position = (tank["x"], tank["y"])
            home = homes.setdefault(tank["id"], position)
            hp_ratio = tank["hp"] / tank["maxHp"] if tank.get("maxHp") else 1.0
            in_bay = any(math.dist(position, (bay["x"], bay["y"])) <= IN_BAY_RANGE for bay in bays)
            at_home = math.dist(position, home) <= HOME_EPSILON
            nearest = min(known, key=lambda unit: (math.dist(position, (unit["x"], unit["y"])), unit["id"])) \
                if known else None

            def attack_or_home():
                if nearest is not None:
                    if nearest["id"] in visible_ids:
                        if tank.get("targetId") != nearest["id"]:
                            print(json.dumps({"attack": tank["id"], "target": nearest["id"]}), flush=True)
                            try_call(client, f'rwx-game-order-attack --units {tank["id"]} --target {nearest["id"]}')
                    else:
                        waypoint = (tank.get("waypointX"), tank.get("waypointY"))
                        if waypoint[0] is None or math.dist(waypoint, (nearest["x"], nearest["y"])) > 35.0:
                            print(json.dumps({"advance": tank["id"], "to": [round(nearest["x"]), round(nearest["y"])]}), flush=True)
                            try_call(client, f'rwx-game-order-attack-move --units {tank["id"]} '
                                             f'--x {nearest["x"]:.0f} --y {nearest["y"]:.0f}')
                    return
                if visible:
                    target = min(visible, key=lambda unit: (math.dist(position, (unit["x"], unit["y"])), unit["id"]))
                    if tank.get("targetId") != target["id"]:
                        print(json.dumps({"attack": tank["id"], "target": target["id"]}), flush=True)
                        try_call(client, f'rwx-game-order-attack --units {tank["id"]} --target {target["id"]}')
                    return
                if not at_home:
                    print(json.dumps({"return": tank["id"], "to": [round(home[0]), round(home[1])]}), flush=True)
                    try_call(client, f'rwx-game-order-move --units {tank["id"]} '
                                     f'--x {home[0]:.0f} --y {home[1]:.0f}')

            # Re-engage only after full HP in a bay. Once engaged, keep fighting until HP < 60 %,
            # then return home and wait for the next full-HP cycle.
            ready = hp_ratio >= 1.0 - FULL_HP_EPSILON
            if tank["id"] not in engaged:
                if ready and in_bay:
                    engaged.add(tank["id"])
                    attack_or_home()
                    continue
                if not at_home:
                    print(json.dumps({"retreat": tank["id"], "hp": tank["hp"],
                                      "to": [round(home[0]), round(home[1])]}), flush=True)
                    try_call(client, f'rwx-game-order-move --units {tank["id"]} '
                                     f'--x {home[0]:.0f} --y {home[1]:.0f}')
                continue
            if hp_ratio < RETREAT_HP_RATIO:
                engaged.discard(tank["id"])
                if not at_home:
                    print(json.dumps({"retreat": tank["id"], "hp": tank["hp"],
                                      "to": [round(home[0]), round(home[1])]}), flush=True)
                    try_call(client, f'rwx-game-order-move --units {tank["id"]} '
                                     f'--x {home[0]:.0f} --y {home[1]:.0f}')
                continue
            attack_or_home()
        time.sleep(POLL_SECONDS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port-file", type=Path, required=True)
    parser.add_argument("--meta-file", type=Path,
                        help="case meta.json; supplies private absolute turret coordinates")
    args = parser.parse_args()
    client = Client(args.port_file)
    try:
        meta = load_meta(args.meta_file)
        destroyed_path = args.meta_file.parent / "engine" / "turret_destroyed.jsonl" if args.meta_file else None
        play(client, meta.get("tankType", "bugMeleeT31"), load_turrets(meta), destroyed_path)
    except (EOFError, BrokenPipeError, ConnectionError):
        print("Case connection closed; evaluate the run for authoritative outcome.", flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
