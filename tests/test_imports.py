import unittest
import importlib.util


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
        from src.config import TASK_ORDER
        from src.tasks import TASK_CLASSES

        self.assertEqual(set(TASK_ORDER), set(TASK_CLASSES))

    def test_task_specs_are_configured(self):
        from src.config import TASK_ORDER, TASK_SPECS, TESTED_DAILY_TASK_ORDER

        self.assertEqual(set(TASK_ORDER), set(TASK_SPECS))
        self.assertIn("midas", TASK_SPECS)
        self.assertIn("gem_50", TASK_SPECS["midas"].policy.allowed_actions)
        self.assertLessEqual(set(TESTED_DAILY_TASK_ORDER), set(TASK_SPECS))
        self.assertNotIn("bounty", TESTED_DAILY_TASK_ORDER)
        self.assertNotIn("guild_dungeon", TESTED_DAILY_TASK_ORDER)


if __name__ == "__main__":
    unittest.main()
