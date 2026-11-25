import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "RL" / "AI Hard-up"))

from rlkit.config import TrainConfig
from rlkit.scoring import GameRecord, parse_final_board, score


def record(outcome, minutes=90):
    return GameRecord("fixture", (2, 5), 5, 1, 0, outcome=outcome, game_ms=minutes * 60_000)


class HardupRewardsTest(unittest.TestCase):
    def test_v1_and_v2_keep_legacy_formulas_and_overrides(self):
        for scenario, base in (("hardupv1", 0.30), ("hardupv2", 0.20)):
            cfg = TrainConfig(scenario=scenario)
            draw = record("draw", 30)
            score(draw, cfg)
            self.assertAlmostEqual(draw.reward, base + 0.035)
            loss = record("loss", 60)
            score(loss, cfg)
            self.assertAlmostEqual(loss.reward, 0.22)
        override = record("draw")
        score(override, TrainConfig(scenario="hardupv2", w_draw=0.25))
        self.assertEqual(override.reward, 0.25)

    def test_v3_draw_clamps_both_terms_and_uses_terminal_values(self):
        cfg = TrainConfig(scenario="hardupv3", w_draw=0.30)
        for income, buildings, expected in ((0.0, 1.0, 0.20), (0.5, 0.5, 0.275), (1.0, 0.0, 0.35),
                                             (0.65, 0.60, 0.275)):
            game = record("draw", 30)
            game.end_income_share = income
            game.end_building_share = buildings
            game.income_self = 1_000
            score(game, cfg)
            self.assertAlmostEqual(game.reward, expected)

    def test_v3_uses_different_win_and_loss_time_limits(self):
        cfg = TrainConfig(scenario="hardupv3")
        win, loss = record("win", 30), record("loss", 60)
        score(win, cfg)
        score(loss, cfg)
        self.assertAlmostEqual(win.reward, 1.035)
        self.assertAlmostEqual(loss.reward, 0.08 + 0.14 * (2 / 3))

    def test_v4_reuses_v3_reward_for_every_outcome(self):
        for outcome in ("win", "loss", "draw"):
            with self.subTest(outcome=outcome):
                results = []
                for scenario in ("hardupv3", "hardupv4"):
                    game = record(outcome, 45)
                    game.end_income_share = 0.8
                    game.end_building_share = 0.3
                    score(game, TrainConfig(scenario=scenario))
                    results.append(game.reward)
                self.assertEqual(*results)

    def test_terminal_values_aggregate_by_real_spawn_and_role(self):
        slots = [{"spawn": 5, "side": 0}, {"spawn": 2, "side": 1}, {"spawn": 4, "side": 0}]
        game = record("draw")
        parse_final_board({"teams": [
            {"teamId": 1, "incomePerSecond": 10.0, "buildingCost": 90},
            {"teamId": 3, "incomePerSecond": 10.0, "buildingCost": 5},
            {"teamId": 4, "incomePerSecond": 20.0, "buildingCost": 5},
        ]}, game, slots)
        self.assertEqual(game.end_income_share, 0.75)
        self.assertEqual(game.end_building_share, 0.10)

    def test_empty_total_is_neutral_and_missing_metrics_are_rejected(self):
        game = record("draw")
        slots = [{"spawn": 5, "side": 0}, {"spawn": 2, "side": 1}]
        with self.assertRaisesRegex(ValueError, "terminal"):
            parse_final_board({"teams": []}, game, slots)
        parse_final_board({"teams": [
            {"teamId": 1, "incomePerSecond": 0.0, "buildingCost": 0},
            {"teamId": 4, "incomePerSecond": 0.0, "buildingCost": 0},
        ]}, game, slots)
        score(game, TrainConfig(scenario="hardupv3"))
        self.assertAlmostEqual(game.reward, 0.275)


if __name__ == "__main__":
    unittest.main()
