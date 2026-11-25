import importlib.util
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

CASE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(CASE), str(CASE.parent)]
spec = importlib.util.spec_from_file_location("case4_score", CASE / "score.py")
score = importlib.util.module_from_spec(spec)
sys.modules["case4_score"] = score
spec.loader.exec_module(score)

TANK_ID = 1007
MAX_HP = 6000.0


def tank_row(unit_id, *, order="idle", bays=(), hp=MAX_HP, alive=True):
    return {"unitId": unit_id, "alias": f"T{unit_id - 1006}", "x": 1150.0, "y": 1290.0, "alive": alive,
            "order": order, "target": None, "hp": hp, "maxHp": MAX_HP,
            "repairBayIds": list(bays)}


def state(ms, *, order="idle", bays=(), hp=MAX_HP, alive=True):
    return {"kind": "state", "gameMs": ms, "tick": ms // 16,
            "tanks": [tank_row(TANK_ID, order=order, bays=bays, hp=hp, alive=alive)]}


def two_tanks(ms, *, second_hp):
    return {"kind": "state", "gameMs": ms, "tick": ms // 16,
            "tanks": [tank_row(1007, bays=[1005]), tank_row(1008, bays=[1005], hp=second_hp)]}


def ready(ms, hp=MAX_HP):
    return state(ms, bays=[1005], hp=hp)


def moving(ms):
    return state(ms, order="move")


class FakeRun:
    """Just the fields the scorer reads; no run directory needed."""

    def __init__(self, *, tanks=None, tank_state=None, final=None, game_ms=20000, task="4_1_1", type_=1, kills=None):
        tanks = tanks or [{ "id": TANK_ID, "alias": "T1", "team": 0, "type": "bugMeleeT31"}]
        self.tanks = {row["id"]: row for row in tanks}
        final = final if final is not None else {row["id"]: True for row in tanks}
        self.result = {"gameMs": game_ms, "kills": kills or [],
                       "tanks": [{"unitId": unit_id, "alive": alive} for unit_id, alive in final.items()],
                       "tanksAlive": sum(1 for alive in final.values() if alive), "tanksTotal": len(final)}
        self.meta = {"task": task, "type": type_, "tickDurationMs": 16, "limits": {"gameSeconds": 900.0}}
        self.tank_state = tank_state or []
        self.gateway = []
        self.directory = Path("case4-score-fixture-does-not-exist")


class TankLossTests(unittest.TestCase):
    def test_destroyed_share(self):
        run = FakeRun(tanks=[{"id": 1007, "team": 0}, {"id": 1008, "team": 0}],
                      final={1007: True, 1008: False}, game_ms=1000)
        item = score.tank_loss(run)
        self.assertEqual(item["detail"]["K1"], 0.5)
        self.assertAlmostEqual(item["raw"], 25.0)

    def test_missing_final_state_is_not_guessed(self):
        run = FakeRun()
        run.result = {"gameMs": 1000}
        self.assertEqual(score.tank_loss(run)["status"], "N/A")


class TankIdleTests(unittest.TestCase):
    def setUp(self):
        # Existing fixtures intentionally start a window at t=0; disable the new boundary
        # filter so they keep exercising window construction. The filter has its own test.
        self._drop_begin = score.DROP_BEGIN
        self._drop_tail = score.DROP_TAIL
        score.DROP_BEGIN = False
        score.DROP_TAIL = False

    def tearDown(self):
        score.DROP_BEGIN = self._drop_begin
        score.DROP_TAIL = self._drop_tail

    def test_default_drops_a_window_that_starts_at_task_begin(self):
        score.DROP_BEGIN = True
        rows = [ready(ms) for ms in range(0, 5000, 1000)] + [moving(5000)]
        item = score.tank_idle(FakeRun(tank_state=rows, game_ms=20000))
        self.assertEqual(item["detail"]["windows"], [])
        self.assertEqual(item["detail"]["skippedBegin"], 1)
        self.assertEqual(item["raw"], 0.0)

    def test_ready_and_loiter_windows_and_weights(self):
        rows = [ready(ms) for ms in range(0, 5000, 1000)]          # ready [0, 5000) = 5 s
        rows += [moving(5000)]
        rows += [state(ms) for ms in range(6000, 15000, 1000)]     # loiter [6000, 15000) = 9 s
        rows += [state(15000, order="attack")]
        rows += [state(ms, order="attack") for ms in range(16000, 20001, 1000)]
        item = score.tank_idle(FakeRun(tank_state=rows, game_ms=20000))
        windows = {row["kind"]: row for row in item["detail"]["windows"] if row["counted"]}
        self.assertAlmostEqual(windows["ready"]["seconds"], 5.0)
        self.assertAlmostEqual(windows["loiter"]["seconds"], 9.0)
        self.assertAlmostEqual(item["detail"]["weightedSeconds"], (5 - 3) * 1.5 + (9 - 8) * 2)
        self.assertAlmostEqual(item["detail"]["ratio"], ((5 - 3) * 1.5 + (9 - 8) * 2) / 20)
        # R defaults to 5% (no baseline w/T yet), so the item saturates here.
        self.assertAlmostEqual(item["raw"], score.IDLE_SCALE * (((5 - 3) * 1.5 + (9 - 8) * 2) / 20) / score.IDLE_RATIO_DEFAULT)

    def test_thresholds_are_strict_and_short_windows_are_free(self):
        rows = [ready(ms) for ms in range(0, 4000, 1000)]          # 4 s: counted (> 3)
        rows += [moving(4000)]
        rows += [ready(4000 + 1000 * index) for index in range(1, 4)]   # 3 s: not counted at 3.0
        rows += [moving(8000)]
        rows += [state(9000 + 1000 * index) for index in range(0, 8)]   # 8 s: not counted at 8.0
        rows += [moving(17000)]
        rows += [state(18000 + 1000 * index, order="attack") for index in range(0, 3)]
        item = score.tank_idle(FakeRun(tank_state=rows, game_ms=20000))
        windows = [row for row in item["detail"]["windows"] if row["counted"]]
        self.assertEqual([row["kind"] for row in windows], ["ready"])
        self.assertAlmostEqual(windows[0]["seconds"], 4.0)

    def test_partial_hp_inside_a_bay_is_neither_ready_nor_loiter(self):
        rows = [state(ms, bays=[1005], hp=3000.0) for ms in range(0, 10000, 1000)]
        item = score.tank_idle(FakeRun(tank_state=rows, game_ms=20000))
        self.assertEqual(item["detail"]["windows"], [])
        self.assertEqual(item["raw"], 0.0)

    def test_a_full_tank_does_not_count_while_a_baymate_is_still_healing(self):
        tanks = [{"id": 1007, "alias": "T1", "team": 0}, {"id": 1008, "alias": "T2", "team": 0}]
        rows = [two_tanks(ms, second_hp=3000.0) for ms in range(0, 10000, 1000)]
        rows += [two_tanks(ms, second_hp=MAX_HP) for ms in range(10000, 15000, 1000)]
        rows.append({"kind": "state", "gameMs": 15000, "tick": 15000 // 16,
                     "tanks": [tank_row(1007, order="attack"), tank_row(1008, order="attack")]})
        item = score.tank_idle(FakeRun(tanks=tanks, tank_state=rows, game_ms=15000))
        counted = [row for row in item["detail"]["windows"] if row["counted"]]
        self.assertEqual({row["unitId"] for row in counted}, {1007, 1008})
        # Both tanks only enter A once the second tank is also full: [10000, 15000) = 5 s.
        self.assertTrue(all(row["kind"] == "ready" and row["seconds"] == 5.0 for row in counted))

    def test_outside_a_bay_idle_ignores_hp(self):
        rows = [state(ms, hp=10.0) for ms in range(0, 9000, 1000)]
        rows += [state(9000, order="attack")]
        item = score.tank_idle(FakeRun(tank_state=rows, game_ms=20000))
        counted = [row for row in item["detail"]["windows"] if row["counted"]]
        self.assertEqual(len(counted), 1)
        self.assertEqual(counted[0]["kind"], "loiter")
        self.assertAlmostEqual(counted[0]["seconds"], 9.0)

    def test_ready_is_cut_from_the_bay_full_interval(self):
        tanks = [{"id": 1007, "alias": "T1", "team": 0}, {"id": 1008, "alias": "T2", "team": 0}]
        rows = []
        for ms in range(0, 10000, 1000):
            second_hp = MAX_HP if ms >= 4000 else 3000.0
            rows.append(two_tanks(ms, second_hp=second_hp))
        rows.append({"kind": "state", "gameMs": 10000, "tick": 10000 // 16,
                     "tanks": [tank_row(1007, order="attack"), tank_row(1008, order="attack")]})
        item = score.tank_idle(FakeRun(tanks=tanks, tank_state=rows, game_ms=10000))
        self.assertEqual(item["detail"]["bayFullIntervals"], [[4000.0, 10000.0]])
        counted = [row for row in item["detail"]["windows"] if row["counted"]]
        self.assertEqual(len(counted), 2)
        self.assertTrue(all(row["kind"] == "ready" and row["seconds"] == 6.0 for row in counted))

    def test_ready_windows_do_not_merge_across_a_non_idle_gap(self):
        rows = [ready(ms) for ms in range(0, 4000, 1000)]       # ready [0, 4000) = 4 s
        rows += [moving(4000)]                                  # one 1 s non-idle gap
        rows += [ready(ms) for ms in range(5000, 10000, 1000)]  # ready [5000, 10000) = 5 s
        rows += [moving(10000)]
        item = score.tank_idle(FakeRun(tank_state=rows, game_ms=10000))
        ready_windows = [row for row in item["detail"]["windows"] if row["kind"] == "ready"]
        self.assertEqual([row["seconds"] for row in ready_windows], [4.0, 5.0])

    def test_ready_ends_when_the_tank_leaves_the_bay(self):
        rows = [ready(ms) for ms in range(0, 5000, 1000)]
        rows += [state(ms) for ms in range(5000, 9000, 1000)]   # outside bay: loiter, not ready
        rows += [state(9000, order="attack")]
        item = score.tank_idle(FakeRun(tank_state=rows, game_ms=9000))
        ready_windows = [row for row in item["detail"]["windows"] if row["kind"] == "ready"]
        loiter_windows = [row for row in item["detail"]["windows"] if row["kind"] == "loiter"]
        self.assertEqual([row["seconds"] for row in ready_windows], [5.0])
        self.assertEqual([row["seconds"] for row in loiter_windows], [4.0])

    def test_missing_tank_state_is_n_a(self):
        self.assertEqual(score.tank_idle(FakeRun())["status"], "N/A")

    def test_death_ends_the_alive_time(self):
        rows = [ready(ms) for ms in range(0, 5000, 1000)]
        rows += [state(5000, alive=False, hp=0.0)]
        item = score.tank_idle(FakeRun(tank_state=rows, final={TANK_ID: False}, game_ms=20000,
                                       kills=[{"unit": TANK_ID, "tick": 312}]))
        self.assertAlmostEqual(item["detail"]["aliveSeconds"], 4992 / 1000)
        # The 4.992 s ready window before death is still counted (it is longer than 3 s).
        self.assertAlmostEqual(item["detail"]["windows"][0]["seconds"], 4.992)
        self.assertTrue(item["detail"]["windows"][0]["counted"])


class DurationTests(unittest.TestCase):
    def test_quadratic_in_normalized_space(self):
        with patch.object(score, "_baselines", return_value={"byType": {"2": 100.0}}):
            item = score.duration_score(FakeRun(game_ms=100000, task="4_2_1", type_=2), 0.0)
        self.assertEqual(item["detail"]["baselineSource"], "per-type baseline")
        self.assertAlmostEqual(item["detail"]["baselineSeconds"], 100.0)
        # Exactly at T the normalized position is (1-0.5)/(2.5-0.5).
        self.assertAlmostEqual(item["raw"], score.curve(0.25, 0, 1, 0, 30, "quadratic", -3), places=4)

    def test_fast_and_slow_ends(self):
        self.assertGreater(score.duration_score(FakeRun(game_ms=10000), 0.0)["raw"], 20.0)
        self.assertEqual(score.duration_score(FakeRun(game_ms=3000000), 0.0)["raw"], 30.0)

    def test_unknown_type_falls_back_to_the_game_limit(self):
        item = score.duration_score(FakeRun(game_ms=300000, task="4_9_9", type_=9), 0.0)
        self.assertEqual(item["detail"]["baselineSource"], "0.55 x game limit")
        self.assertAlmostEqual(item["detail"]["baselineSeconds"], 495.0)

class DocumentTests(unittest.TestCase):
    def test_compute_returns_three_capped_items(self):
        rows = [state(ms) for ms in range(0, 5000, 1000)] + [moving(5000)]
        document = score.compute(FakeRun(tank_state=rows, game_ms=53616))
        self.assertEqual(document["version"], "case4-score-v1")
        self.assertEqual([item["id"] for item in document["items"]], ["tank_loss", "tank_idle", "duration"])
        self.assertEqual([item["cap"] for item in document["items"]], [50, 30, 30])
        self.assertAlmostEqual(document["deduction"], sum(item["points"] for item in document["items"]))
        self.assertEqual(document["total"], max(0.0, 100 - document["deduction"]))


if __name__ == "__main__":
    unittest.main()
