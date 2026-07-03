import unittest
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory


class ImportTests(unittest.TestCase):
    @unittest.skipIf(importlib.util.find_spec("cv2") is None, "opencv-python is not installed")
    def test_core_imports(self):
        import src.adb_controller
        import src.battle_handler
        import src.config
        import src.daily_runner
        import src.daily_task_finder
        import src.main
        import src.manual_screenshots
        import src.navigator
        import src.scene_detector
        import src.task_runner
        import src.vision_matcher

    @unittest.skipIf(importlib.util.find_spec("cv2") is None, "opencv-python is not installed")
    def test_task_registry(self):
        from src.config import TASK_ORDER, TASK_SPECS
        from src.tasks import TASK_CLASSES

        independent = {key for key, spec in TASK_SPECS.items() if spec.kind == "independent"}
        self.assertEqual(set(TASK_ORDER), set(TASK_CLASSES) - independent)
        self.assertEqual(independent, {"abyss", "advanced_arena", "hero_contest"})

    def test_task_specs_are_configured(self):
        from src.config import (
            RUN_ALL_GO_FIRST_TASK_ORDER,
            RUN_ALL_TASK_ORDER,
            TASK_ORDER,
            TASK_SPECS,
            TESTED_DAILY_TASK_ORDER,
        )

        independent = {key for key, spec in TASK_SPECS.items() if spec.kind == "independent"}
        self.assertEqual(set(TASK_ORDER), set(TASK_SPECS) - independent)
        self.assertEqual(independent, {"abyss", "advanced_arena", "hero_contest"})
        self.assertLessEqual(set(RUN_ALL_TASK_ORDER), set(TASK_ORDER))
        self.assertLessEqual(set(RUN_ALL_GO_FIRST_TASK_ORDER), set(TASK_ORDER))
        self.assertNotIn("endless_trial", RUN_ALL_TASK_ORDER)
        self.assertNotIn("bounty", RUN_ALL_GO_FIRST_TASK_ORDER)
        self.assertNotIn("campaign", RUN_ALL_GO_FIRST_TASK_ORDER)
        self.assertNotIn("endless_trial", RUN_ALL_GO_FIRST_TASK_ORDER)
        self.assertIn("guild_dungeon", RUN_ALL_GO_FIRST_TASK_ORDER)
        self.assertIn("magic_shop", RUN_ALL_GO_FIRST_TASK_ORDER)
        self.assertIn("midas", TASK_SPECS)
        self.assertIn("gem_50", TASK_SPECS["midas"].policy.allowed_actions)
        self.assertLessEqual(set(TESTED_DAILY_TASK_ORDER), set(TASK_SPECS))
        self.assertNotIn("bounty", TESTED_DAILY_TASK_ORDER)
        self.assertNotIn("guild_dungeon", TESTED_DAILY_TASK_ORDER)

    def test_run_all_task_order_can_load_user_config(self):
        from src.config import load_run_all_task_order

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_all_tasks.jsonc"
            path.write_text(
                """
{
  "tasks": [
    "midas",        // 點金手
    // "campaign",  // 戰役關卡
    "magic_shop"    // 魔法商店
  ]
}
""",
                encoding="utf-8",
            )

            self.assertEqual(load_run_all_task_order(path), ("midas", "magic_shop"))

    def test_run_all_task_order_rejects_unknown_or_duplicate_tasks(self):
        from src.config import load_run_all_task_order

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_all_tasks.jsonc"
            path.write_text('{"tasks": ["midas", "missing_task"]}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown task"):
                load_run_all_task_order(path)

            path.write_text('{"tasks": ["midas", "midas"]}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate task"):
                load_run_all_task_order(path)

    def test_arena_mode_argument_is_available_on_run_commands(self):
        from src.main import _build_parser

        parser = _build_parser()

        args = parser.parse_args(["run-task", "arena", "--arena-mode", "tickets_20"])
        self.assertEqual(args.arena_mode, "tickets_20")

        args = parser.parse_args(["run-all", "--arena-mode", "tickets_20"])
        self.assertEqual(args.arena_mode, "tickets_20")


if __name__ == "__main__":
    unittest.main()
