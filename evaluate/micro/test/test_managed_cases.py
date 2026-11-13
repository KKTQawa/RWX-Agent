from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[3]
MICRO = ROOT / "evaluate" / "micro"
LAUNCHER = ROOT / "agent-operation" / "server" / "start-micro-evaluation-run.ps1"


def managed_cases() -> list[Path]:
    return sorted(path for path in MICRO.glob("CASE*") if path.is_dir())


def launcher_cases() -> set[str]:
    text = LAUNCHER.read_text(encoding="utf-8")
    match = re.search(r"\[ValidateSet\(([^)]*)\)\]", text)
    if match is None:
        raise AssertionError("start-micro-evaluation-run.ps1 has no ValidateSet for -Case")
    return {item.strip().strip("'\"") for item in match.group(1).split(",") if item.strip()}


class ManagedCasesTest(unittest.TestCase):
    def test_every_case_ships_a_managed_prompt(self) -> None:
        cases = managed_cases()
        self.assertTrue(cases)
        for case in cases:
            prompt = case / "prompt_single.md"
            self.assertTrue(prompt.is_file(), f"missing managed prompt: {prompt}")
            text = prompt.read_text(encoding="utf-8")
            self.assertIn("{{RUN}}", text, prompt)
            self.assertIn("rwx-micro-lobby-status", text, prompt)
            self.assertIn("rwx-micro-lobby-enter", text, prompt)
            self.assertTrue(
                f"{case.name}\\START.md" in text or f"{case.name}/START.md" in text,
                f"{prompt} does not link its case START.md",
            )

    def test_launcher_accepts_exactly_the_cases_with_prompts(self) -> None:
        with_prompt = {case.name for case in managed_cases() if (case / "prompt_single.md").is_file()}
        self.assertEqual(launcher_cases(), with_prompt)


if __name__ == "__main__":
    unittest.main()
