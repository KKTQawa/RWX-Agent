"""CASE1 public-state baseline: begin, attack-move the mechs, focus the nearest enemy.

Uses only the same observation/order commands available to an Agent. It does not read meta,
gateway, replay or engine evidence.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class Client:
    def __init__(self, port_file: Path):
        self.process = subprocess.Popen(
            [sys.executable, str(ROOT / "agent-operation/tools/rwx-cli.py"),
             "--port-file", str(port_file), "--stdio"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", cwd=ROOT)

    def call(self, command: str):
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise EOFError("case process ended; use result.json for outcome")
        reply = json.loads(line)
        if reply["error"]:
            raise RuntimeError(reply["reply"])
        data = reply["reply"]
        return json.loads(data) if data.startswith("{") else data

    def close(self):
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        self.process.stdout.close()


def _units(client: Client, owner: str) -> list[dict]:
    data = client.call(f"rwx-micro-1-units --owner {owner} --json")
    return data.get("units") or [] if isinstance(data, dict) else []


def play(client: Client, seed: int):
    state = None
    for _ in range(120):
        try:
            state = client.call("rwx-micro-1-state --json")
            break
        except RuntimeError as error:
            if "loading" not in str(error):
                raise
            time.sleep(0.5)
    if state is None:
        raise RuntimeError("case stayed in loading state")
    if state.get("phase") == "briefing":
        client.call("rwx-micro-1-begin")
    enemies = _units(client, "enemy")
    if not enemies:
        raise RuntimeError("CASE1 baseline found no enemy at start")
    anchor = (sum(float(unit["x"]) for unit in enemies) / len(enemies),
              sum(float(unit["y"]) for unit in enemies) / len(enemies))
    last_command = None
    while True:
        state = client.call("rwx-micro-1-state --json")
        if state.get("phase") == "ended" or state.get("outcome") in {"win", "defeat", "timeout"}:
            return
        own = _units(client, "self")
        enemies = _units(client, "enemy")
        if not own:
            return
        by_alias = {unit.get("alias"): unit for unit in enemies}
        threatened = set()
        # A mech that is inside a mammoth's range backs off one tile first; only the units that
        # are not threatened keep attacking. This is reactive kiting, not a change of posture.
        for unit in own:
            threats = [by_alias[name] for name in (unit.get("threatenedBy") or []) if name in by_alias]
            if not threats:
                continue
            nearest = min(threats, key=lambda enemy: (float(unit["x"]) - float(enemy["x"])) ** 2
                          + (float(unit["y"]) - float(enemy["y"])) ** 2)
            dx, dy = float(unit["x"]) - float(nearest["x"]), float(unit["y"]) - float(nearest["y"])
            length = (dx * dx + dy * dy) ** 0.5
            if length < 1e-6:
                continue
            target_x = float(unit["x"]) + dx / length * 20.0
            target_y = float(unit["y"]) + dy / length * 20.0
            client.call(f"rwx-micro-1-move --units {unit['alias']} --x {target_x:.0f} --y {target_y:.0f}")
            threatened.add(unit["alias"])
        safe = [unit["alias"] for unit in own if unit.get("alias") not in threatened]
        if enemies and safe:
            target = min(enemies, key=lambda unit: (
                (float(unit["x"]) - anchor[0]) ** 2 + (float(unit["y"]) - anchor[1]) ** 2,
                unit.get("id", 0)))
            command = (target.get("alias"), tuple(safe))
            if command != last_command:
                client.call(f"rwx-micro-1-attack --units {','.join(safe)} --target {target['alias']}")
                last_command = command
        elif not enemies:
            client.call(f"rwx-micro-1-attack-move --units all --x {anchor[0]:.0f} --y {anchor[1]:.0f}")
            last_command = None
        time.sleep(1.0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port-file", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1, help="only for the log label")
    args = parser.parse_args()
    client = Client(args.port_file)
    try:
        play(client, args.seed)
    except (EOFError, BrokenPipeError, ConnectionError):
        print("Case connection closed; evaluate the run for authoritative outcome.", flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
