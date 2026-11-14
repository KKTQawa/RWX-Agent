"""`stamp_micro_meta.py` names the run directory after the declared participant.

These tests build throwaway run directories: the engine's own evidence is never touched. They cover
the three declarations (agent / baseline / human), the rename with its path fixes, the pointer in
`config.json`, and idempotency.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import stamp_micro_meta as stamp  # noqa: E402


class StampMicroMetaTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = self.root / "config"
        (self.config / "CASE2-LTE").mkdir(parents=True)
        self.previous_config = stamp.MICRO_CONFIG
        stamp.MICRO_CONFIG = self.config
        self.case = self.root / "micro" / "CASE2-LTE"
        self.case.mkdir(parents=True)

    def tearDown(self):
        stamp.MICRO_CONFIG = self.previous_config
        self.temporary.cleanup()

    def make_run(self, name="CASE2-LTE_2_7_4_realtime_s1331_20261114-175931", **overrides):
        run = self.case / name
        (run / "replay").mkdir(parents=True)
        (run / "eval").mkdir()
        meta = {
            "schema": "rwx-micro-evidence/1",
            "case": "CASE2-LTE",
            "task": "2_7_4",
            "seed": 1331,
            "track": "realtime",
            "mode": "agent",
            "replay": "match.replay",
            "map": {"file": str(run / "map.tmx")},
        }
        meta.update(overrides)
        (run / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        (run / "map.tmx").write_text("<map/>", encoding="utf-8")
        (run / "match.replay").write_bytes(b"not a replay")
        (run / "replay" / "match.summary.txt").write_text(
            f"文件        : {run / 'match.replay'}\n地图        : {run / 'map.tmx'}\n", encoding="utf-8")
        return run

    def run_tool(self, run, **kwargs):
        item = stamp.plan(run.resolve(), **kwargs)
        return item, stamp.apply(item)

    def test_agent_declaration_names_the_directory(self):
        run = self.make_run()
        item, actions = self.run_tool(run, runner="agent", provider="OpenCode",
                                      model="DeepSeek V4.1 Flash", thinking="high", tool="Pi",
                                      tool_detail=None, display_name=None)
        expected = "CASE2-LTE 2_7_4 realtime · 20261114 17-59 · DeepSeek V4.1 Flash - Pi · s1331"
        self.assertEqual(item["display"], expected)
        self.assertEqual(item["target"].name, expected)
        self.assertFalse(run.exists(), "the engine-named directory must be gone")
        meta = json.loads((item["target"] / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["display_name"], expected)
        self.assertEqual(meta["runner"], "agent")
        self.assertEqual(meta["models"], [{"provider": "OpenCode", "id": "DeepSeek V4.1 Flash",
                                           "thinking": "high"}])
        self.assertEqual(meta["tools"], [{"profile": "Pi", "detail": None}])
        self.assertEqual(meta["replay"], expected + ".replay")
        self.assertEqual(meta["map"]["file"], str(item["target"] / "map.tmx"))
        self.assertTrue((item["target"] / (expected + ".replay")).is_file())
        self.assertTrue(any(action.startswith("dir:") for action in actions))

    def test_baseline_declares_itself_and_needs_no_model(self):
        run = self.make_run(name="CASE2-LTE_2_7_3_realtime_s1331_20261113-100024", task="2_7_3")
        item, _ = self.run_tool(run, runner="baseline", provider=None, model=None, thinking=None,
                                tool=None, tool_detail=None, display_name=None)
        self.assertEqual(item["display"], "CASE2-LTE 2_7_3 realtime · 20261113 10-00 · baseline · s1331")
        meta = json.loads((item["target"] / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["runner"], "baseline")
        self.assertNotIn("models", meta)

    def test_script_is_accepted_as_a_baseline_synonym(self):
        self.assertEqual(stamp.RUNNER_ALIASES["script"], "baseline")

    def test_human_declares_itself(self):
        run = self.make_run(name="CASE2-LTE_2_7_4_human_s1_20261114-090000", mode="human")
        item, _ = self.run_tool(run, runner="human", provider=None, model=None, thinking=None,
                                tool=None, tool_detail=None, display_name=None)
        self.assertIn(" · human · s1", item["display"])
        meta = json.loads((item["target"] / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["runner"], "human")

    def test_agent_declaration_requires_its_identity(self):
        run = self.make_run()
        with self.assertRaises(ValueError):
            stamp.plan(run.resolve(), runner="agent", provider=None, model="m", thinking=None,
                       tool="Pi", tool_detail=None, display_name=None)

    def test_a_run_with_models_cannot_be_declared_a_baseline(self):
        run = self.make_run(models=[{"provider": "OpenCode", "id": "m"}])
        with self.assertRaises(ValueError):
            stamp.plan(run.resolve(), runner="baseline", provider=None, model=None, thinking=None,
                       tool=None, tool_detail=None, display_name=None)

    def test_case_config_baseline_pointer_follows_the_rename(self):
        run = self.make_run(name="CASE2-LTE_2_7_3_realtime_s1331_20261113-100024", task="2_7_3")
        config = self.config / "CASE2-LTE" / "config.json"
        config.write_text(json.dumps({"baselines": {"byTask": {"2_7_3": {"run": run.name}}}}),
                          encoding="utf-8")
        item, actions = self.run_tool(run, runner="baseline", provider=None, model=None,
                                      thinking=None, tool=None, tool_detail=None, display_name=None)
        recorded = json.loads(config.read_text(encoding="utf-8"))["baselines"]["byTask"]["2_7_3"]["run"]
        self.assertEqual(recorded, item["target"].name)
        self.assertTrue(any(action.startswith("config:") for action in actions))

    def test_summary_text_and_broken_replay_are_reported_not_fatal(self):
        run = self.make_run(name="CASE2-LTE_2_7_3_realtime_s1331_20261113-100024", task="2_7_3")
        item, actions = self.run_tool(run, runner="baseline", provider=None, model=None,
                                      thinking=None, tool=None, tool_detail=None, display_name=None)
        summary = (item["target"] / "replay" / "match.summary.txt").read_text(encoding="utf-8")
        self.assertNotIn(run.name, summary, "the recorded absolute path must follow the rename")
        self.assertIn(str(item["target"]), summary)
        self.assertTrue(any(action.startswith("text:") for action in actions))
        self.assertTrue(any("replay map path" in action for action in actions),
                        "an unreadable replay is reported instead of aborting the rename")

    def test_second_pass_is_a_no_op(self):
        run = self.make_run(name="CASE2-LTE_2_7_3_realtime_s1331_20261113-100024", task="2_7_3")
        item, _ = self.run_tool(run, runner="baseline", provider=None, model=None, thinking=None,
                                tool=None, tool_detail=None, display_name=None)
        again = stamp.plan(item["target"].resolve(), runner="baseline", provider=None, model=None,
                           thinking=None, tool=None, tool_detail=None, display_name=None)
        self.assertEqual(again["target"], item["target"])
        self.assertEqual(again["display"], item["display"])

    def test_explicit_display_name_wins(self):
        run = self.make_run()
        item, _ = self.run_tool(run, runner="baseline", provider=None, model=None, thinking=None,
                                tool=None, tool_detail=None, display_name="CASE2-LTE 手工命名")
        self.assertEqual(item["target"].name, "CASE2-LTE 手工命名")


if __name__ == "__main__":
    unittest.main()
