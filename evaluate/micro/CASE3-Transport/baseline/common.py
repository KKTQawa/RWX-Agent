"""CASE3-Transport public-state-only baseline shared by type1..type4.

Deterministic transport state machine (only public observations; never meta/evidence/replays):

1. factories keep producing every type whose target-island count is below the requirement;
2. a transport that is idle near the target island for > 6 s:
   - with cargo: move to the target-island centre and unload;
   - empty: return to the start-island centre;
3. a transport at the start island carrying units for > 10 s: fly to the target-island centre
   and unload; while it is still inside the start island it can take more units first;
4. a stranded/hovering transport (idle, neither near the start nor the target) moves back to the
   start-island centre after 6 s; every other state stays put;
5. the loop polls public observations every 1 s.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
CASE = Path(__file__).resolve().parents[1]
TILE_SIZE = 20.0
with (CASE / "config.json").open(encoding="utf-8-sig") as stream:
    _CONFIG = json.load(stream)


def _centre(section):
    """World centre of an island configured in tile coordinates."""
    return ((float(section["centerX"]) + 0.5) * TILE_SIZE,
            (float(section["centerY"]) + 0.5) * TILE_SIZE)


# Forced endpoints: the middle of each island, not a coast tile.
BASE = _centre(_CONFIG["map"]["baseIsland"])
TARGET_CENTRE = _centre(_CONFIG["map"]["targetIsland"])
POLL_SECONDS = 1.0
NEAR_BASE = 40.0
NEAR_TARGET_CENTRE = 60.0
TARGET_AREA = 320.0
TARGET_IDLE_SECONDS = 6.0
START_LOADED_SECONDS = 10.0
HOVER_SECONDS = 6.0
BOARD_TIMEOUT = 20.0


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


def near(point, target, radius):
    return abs(point[0] - target[0]) <= radius and abs(point[1] - target[1]) <= radius


def try_call(client, command):
    """B commands race with the game (a unit may board while we look at it); skip and retry later."""
    ok, payload = attempt(client, command)
    if ok:
        return payload
    print(json.dumps({"skipped": payload, "command": command}), flush=True)
    return None


def attempt(client, command):
    """(True, reply) or (False, error text) without raising, so the caller can react to the reason."""
    try:
        return True, client.call(command)
    except RuntimeError as error:
        return False, str(error)


def load_into(client, transport, idle):
    """Load as many idle units as really fit; the engine rejects a hold whose slots are too small.

    Slot weights are per unit type and are not public, so the request size descends until the
    engine accepts it. Returns the units that were ordered aboard, or [] when nothing fits.
    """
    free = transport["freeSlots"]
    for count in range(min(free, len(idle)), 0, -1):
        take = idle[:count]
        ids = ",".join(str(unit["id"]) for unit in take)
        ok, payload = attempt(client, f'rwx-micro-3-load --transport {transport["id"]} --units {ids}')
        if ok:
            print(json.dumps({"load": {"transport": transport["id"], "units": ids}}), flush=True)
            return take
        if "insufficient_capacity" not in payload:
            print(json.dumps({"skipped": payload, "units": ids}), flush=True)
            return []
    return []


def load_meta(path):
    """Private baseline input: absolute AA positions and the target-island tile bounds."""
    if path is None:
        return [], None
    with open(path, encoding="utf-8-sig") as stream:
        data = json.load(stream)
    aa = [{"id": row["id"], "x": row["x"], "y": row["y"]} for row in data.get("antiAirTurrets", [])]
    raw = data.get("targetIslandBounds")
    bounds = None
    if raw is not None:
        # min/max are tile indices; world span is [tile*20, (tile+1)*20].
        bounds = {"minX": float(raw["minX"]) * 20.0,
                  "maxX": (float(raw["maxX"]) + 1.0) * 20.0,
                  "minY": float(raw["minY"]) * 20.0,
                  "maxY": (float(raw["maxY"]) + 1.0) * 20.0}
    return aa, bounds


def play(client, aa_turrets, target_bounds, no_aa=False):
    boarding = {}   # transport id -> {"units": [ids], "deadline": monotonic}
    unloading = {}  # transport id -> monotonic deadline
    target_idle = {}  # transport id -> monotonic first idle observation near the target island
    start_loaded = {}  # transport id -> monotonic first observation of cargo at the start island
    hover_since = {}   # transport id -> monotonic first idle observation away from both islands
    inflight = {}   # unit type -> orders issued but not yet visible as a live unit
    seen = {}       # unit type -> live count observed last poll
    attacking = {}  # ground unit id -> last AA target id
    attack_time = {}  # ground unit id -> monotonic time the attack order was last issued
    while True:
        state = client.call("rwx-micro-3-state --json")
        if state.get("phase") == "ended" or state.get("targetReached"):
            return
        goal = client.call("rwx-micro-3-goal --json")
        production = client.call("rwx-micro-3-production --json")
        fleet = client.call("rwx-micro-3-fleet --json")["transports"]
        units = client.call("rwx-game-unit-list --owner self --full --json")["units"]
        requirements = goal["requirements"]
        remaining = {row["type"]: row["remaining"] for row in requirements}
        required = {row["type"]: row["required"] for row in requirements}
        produced = production["producedCounts"]

        # Reconcile outstanding orders with units that actually appeared. The engine rejects a
        # production order beyond the remaining goal gap, so keep the local in-flight count.
        for need in requirements:
            kind = need["type"]
            grew = max(0, produced.get(kind, 0) - seen.get(kind, 0))
            inflight[kind] = max(0, inflight.get(kind, 0) - grew)
            seen[kind] = produced.get(kind, 0)

        # 1) Factories keep producing every type whose target-island count is still short.
        # Factories are specialized (mech factory vs tank factory), and `allowedUnitTypes` is the
        # goal-wide set, so a rejected order must fall through to the next factory/type instead of
        # retrying the same invalid request forever.
        placed = False
        for factory in sorted(production["factories"], key=lambda row: row["factoryId"]):
            if not factory["alive"] or factory["busy"]:
                continue
            for need in requirements:
                kind = need["type"]
                ordered = produced.get(kind, 0) + inflight.get(kind, 0)
                if need["remaining"] > 0 and ordered < required[kind] and kind in production["allowedUnitTypes"]:
                    print(json.dumps({"produce": {"factory": factory["factoryId"], "unit": kind}}), flush=True)
                    if try_call(client, f'rwx-micro-3-produce --factory {factory["factoryId"]} --unit {kind}') is not None:
                        inflight[kind] = inflight.get(kind, 0) + 1
                        placed = True
                        break
            if placed:
                break

        # 1b) Ground attack units standing on the target island attack an AA turret by id. The
        # baseline reads the private AA coordinates; this is a deliberate privileged baseline input.
        now = time.monotonic()
        if aa_turrets and target_bounds and not no_aa:
            for unit in sorted(units, key=lambda row: row["id"]):
                if unit.get("type") not in required or unit.get("alive") is False:
                    continue
                x, y = unit["x"], unit["y"]
                if not (target_bounds["minX"] <= x <= target_bounds["maxX"]
                        and target_bounds["minY"] <= y <= target_bounds["maxY"]):
                    continue
                for target in sorted(aa_turrets, key=lambda row: (math.dist((x, y), (row["x"], row["y"])), row["id"])):
                    if attacking.get(unit["id"]) == target["id"] and now - attack_time.get(unit["id"], 0.0) < 3.0:
                        break
                    if try_call(client, f'rwx-game-order-attack --units {unit["id"]} --target {target["id"]}') is not None:
                        attacking[unit["id"]] = target["id"]
                        attack_time[unit["id"]] = now
                        print(json.dumps({"attack": {"unit": unit["id"], "target": target["id"]}}), flush=True)
                        break
                    attacking.pop(unit["id"], None)
                    attack_time.pop(unit["id"], None)

        # 2) Cargo bookkeeping: a remembered load ends when the units really boarded or timed out.
        carried = {unit for transport in fleet for unit in transport["cargo"]}
        for transport_id in list(boarding):
            row = boarding[transport_id]
            if now > row["deadline"] or all(unit in carried for unit in row["units"]):
                boarding.pop(transport_id, None)
        for transport_id in list(unloading):
            if now > unloading[transport_id]:
                unloading.pop(transport_id, None)
        pending = {unit for row in boarding.values() for unit in row["units"]}
        idle = sorted((unit for unit in units
                       if unit["type"] in remaining and unit["id"] not in carried
                       and unit["id"] not in pending
                       and not (target_bounds
                                and target_bounds["minX"] <= unit["x"] <= target_bounds["maxX"]
                                and target_bounds["minY"] <= unit["y"] <= target_bounds["maxY"])
                       and not near((unit["x"], unit["y"]), TARGET_CENTRE, TARGET_AREA)),
                      key=lambda unit: unit["id"])

        for transport in sorted(fleet, key=lambda row: row["id"]):
            tid = transport["id"]
            if not transport["alive"]:
                target_idle.pop(tid, None)
                start_loaded.pop(tid, None)
                hover_since.pop(tid, None)
                continue
            if tid in boarding:
                continue  # never move a transport whose units are still walking over
            position = (transport["x"], transport["y"])
            cargo = len(transport["cargo"])
            near_target = near(position, TARGET_CENTRE, TARGET_AREA)
            near_base = near(position, BASE, NEAR_BASE)

            if near_target:
                start_loaded.pop(tid, None)
                hover_since.pop(tid, None)
                if transport["order"] != "idle":
                    target_idle.pop(tid, None)
                    continue
                first = target_idle.setdefault(tid, now)
                if now - first < TARGET_IDLE_SECONDS:
                    continue
                if cargo:
                    if near(position, TARGET_CENTRE, NEAR_TARGET_CENTRE):
                        if tid not in unloading:
                            print(json.dumps({"unload": tid}), flush=True)
                            try_call(client, f'rwx-micro-3-unload --transport {tid}')
                            unloading[tid] = now + 8.0
                    else:
                        print(json.dumps({"move": {"transport": tid, "to": TARGET_CENTRE}}), flush=True)
                        try_call(client, f'rwx-micro-3-move --transport {tid} '
                                         f'--x {TARGET_CENTRE[0]:.0f} --y {TARGET_CENTRE[1]:.0f}')
                else:
                    print(json.dumps({"move": {"transport": tid, "to": BASE}}), flush=True)
                    try_call(client, f'rwx-micro-3-move --transport {tid} --x {BASE[0]:.0f} --y {BASE[1]:.0f}')
                continue

            target_idle.pop(tid, None)
            if near_base:
                hover_since.pop(tid, None)
                if cargo:
                    first = start_loaded.setdefault(tid, now)
                    if now - first >= START_LOADED_SECONDS:
                        print(json.dumps({"move": {"transport": tid, "to": TARGET_CENTRE}}), flush=True)
                        try_call(client, f'rwx-micro-3-move --transport {tid} '
                                         f'--x {TARGET_CENTRE[0]:.0f} --y {TARGET_CENTRE[1]:.0f}')
                    elif transport["freeSlots"] > 0 and idle:
                        take = load_into(client, transport, idle)
                        if take:
                            idle = idle[len(take):]
                            boarding[tid] = {"units": [unit["id"] for unit in take],
                                             "deadline": now + BOARD_TIMEOUT}
                    continue
                start_loaded.pop(tid, None)
                if transport["freeSlots"] > 0 and idle:
                    take = load_into(client, transport, idle)
                    if take:
                        idle = idle[len(take):]
                        boarding[tid] = {"units": [unit["id"] for unit in take],
                                         "deadline": now + BOARD_TIMEOUT}
                continue

            # Not at either island: a stationary idle transport is hovering/stranded.
            start_loaded.pop(tid, None)
            if transport["order"] == "idle":
                first = hover_since.setdefault(tid, now)
                if now - first >= HOVER_SECONDS:
                    print(json.dumps({"move": {"transport": tid, "to": BASE}}), flush=True)
                    try_call(client, f'rwx-micro-3-move --transport {tid} --x {BASE[0]:.0f} --y {BASE[1]:.0f}')
            else:
                hover_since.pop(tid, None)
        time.sleep(POLL_SECONDS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port-file", type=Path, required=True)
    parser.add_argument("--meta-file", type=Path,
                        help="case meta.json; supplies private AA coordinates and target bounds")
    parser.add_argument("--no-aa", action="store_true",
                        help="diagnostic only: skip the target-island AA attack step")
    args = parser.parse_args()
    client = Client(args.port_file)
    try:
        aa_turrets, target_bounds = load_meta(args.meta_file)
        play(client, aa_turrets, target_bounds, args.no_aa)
    except (EOFError, BrokenPipeError, ConnectionError):
        print("Case connection closed; evaluate the run for authoritative outcome.", flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
