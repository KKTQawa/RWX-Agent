from __future__ import annotations

import gzip
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path


UTILS = Path(__file__).parents[2] / "utils"
sys.path.insert(0, str(UTILS))
from replay import encode_modified_utf8  # noqa: E402
from replay_map import replay_map_path  # noqa: E402

SCRIPT = Path(__file__).parents[1] / "collect_runs.py"
SPEC = importlib.util.spec_from_file_location("collect_runs", SCRIPT)
collect_runs = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(collect_runs)


def _utf(text: str) -> bytes:
    encoded = encode_modified_utf8(text)
    return struct.pack(">H", len(encoded)) + encoded


def _block(name: str, payload: bytes) -> bytes:
    return _utf(name) + struct.pack(">i", len(payload)) + payload


def make_replay(path: Path, map_path: str) -> None:
    """A structurally valid container with the initial-save map path only."""
    body = (
        _block("customUnitsBlock", b"")
        + _block("gameSetup", b"")
        + _utf(map_path)
        + lookalike_tail()
    )
    save = (
        _utf("rustedWarfareSave")
        + struct.pack(">i", 0)
        + struct.pack(">i", 96)
        + b"\x00"
        + _block("saveCompression", gzip.compress(body, mtime=0))
    )
    data = (
        _utf("rustedWarfareReplay")
        + struct.pack(">i", 0)
        + struct.pack(">i", 96)
        + _utf("1.15")
        + b"\x00"
        + _block("gamesave", save)
    )
    path.write_bytes(data)


def lookalike_tail() -> bytes:
    return b"\x00\x00\x00\x00"


class CollectRunsTest(unittest.TestCase):
    def make_completed(self, root: Path, name: str = "CASE1-duel_1_2_2_realtime_s1") -> Path:
        result = root / "micro-output" / name
        result.mkdir(parents=True)
        (result / "meta.json").write_text(json.dumps({"case": "CASE1-duel"}), encoding="utf-8")
        (result / "result.json").write_text("{}", encoding="utf-8")
        (result / "map.tmx").write_bytes(b"<map/>")
        make_replay(result / "match.replay", str(result / "map.tmx"))
        return result

    def test_plan_and_move(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = self.make_completed(base / "run")
            planned_source, target = collect_runs.collection_plan(base / "run", base / "output")
            self.assertEqual(planned_source, source)
            self.assertFalse(target.exists())
            self.assertEqual(collect_runs.main(["--run", str(base / "run"), "--destination", str(base / "output"), "--apply"]), 0)
            self.assertFalse(source.exists())
            self.assertTrue((target / "result.json").is_file())
            self.assertEqual(replay_map_path(target / "match.replay"), str((target / "map.tmx").resolve()))

    def test_rejects_unfinished_or_ambiguous_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            incomplete = self.make_completed(base / "run")
            (incomplete / "result.json").unlink()
            with self.assertRaises(collect_runs.CollectionError):
                collect_runs.collection_plan(base / "run", base / "output")
            self.make_completed(base / "run", "second")
            with self.assertRaises(collect_runs.CollectionError):
                collect_runs.collection_plan(base / "run", base / "output")

    def test_rebases_the_recorded_map_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = self.make_completed(base / "run")
            (source / "map.tmx").write_text("map", encoding="utf-8")
            meta = json.loads((source / "meta.json").read_text(encoding="utf-8"))
            meta["map"] = {"file": str(source / "map.tmx"), "sha256": "abc"}
            (source / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
            _, target = collect_runs.collection_plan(base / "run", base / "output")
            self.assertEqual(collect_runs.main(["--run", str(base / "run"), "--destination", str(base / "output"), "--apply"]), 0)
            moved = json.loads((target / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(moved["map"], {"file": str((target / "map.tmx").resolve()), "sha256": "abc"})

    def test_rejects_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = self.make_completed(base / "run")
            target = base / "output" / "CASE1-duel" / source.name
            target.mkdir(parents=True)
            with self.assertRaises(collect_runs.CollectionError):
                collect_runs.collection_plan(base / "run", base / "output")


if __name__ == "__main__":
    unittest.main()
