import unittest
from types import SimpleNamespace

from src.scene_detector import Scene, SceneDetection
from src.tasks.summon import SummonTask


class FakeDetector:
    def __init__(self, scene):
        self.scene = scene

    def detect(self, screen):
        return SceneDetection(self.scene)


class FakeController:
    def __init__(self):
        self.taps = []

    def screenshot(self):
        return object()

    def tap(self, x, y):
        self.taps.append((x, y))


class FakeNavigator:
    def __init__(self):
        self.go_calls = 0

    def go_to_daily_tasks(self, max_steps=3):
        self.go_calls += 1
        return True


class FakeSummonTask(SummonTask):
    def __init__(self, scene, page_match_sequence=None, daily_sequence=None, confirm_match_sequence=None):
        self.tapped = []
        self.blank_taps = []
        self.page_match_sequence = list(page_match_sequence or [])
        self.daily_sequence = list(daily_sequence or [])
        self.confirm_match_sequence = list(confirm_match_sequence or [])
        self.context = SimpleNamespace(
            controller=FakeController(),
            detector=FakeDetector(scene),
            navigator=FakeNavigator(),
        )

    def _match_task_asset(self, asset_name, **kwargs):
        if asset_name == "advanced_contract_label.png" and self.page_match_sequence:
            return object() if self.page_match_sequence.pop(0) else None
        if asset_name == "confirm_button.png" and self.confirm_match_sequence:
            return object() if self.confirm_match_sequence.pop(0) else None
        return object() if asset_name == "advanced_contract_label.png" else None

    def _tap_task_asset(self, label, asset_name, **kwargs):
        self.tapped.append((label, asset_name))
        return object()

    def _is_daily_tasks_visible(self):
        if self.daily_sequence:
            return self.daily_sequence.pop(0)
        return self.context.detector.scene == Scene.DAILY_TASKS


class SummonReturnTests(unittest.TestCase):
    def test_return_uses_leave_button_then_stops_on_daily_tasks(self):
        task = FakeSummonTask(Scene.DAILY_TASKS)

        task._return_to_daily_tasks()

        self.assertEqual(task.tapped, [("leave summon page", "leave_button.png")])
        self.assertEqual(task.context.navigator.go_calls, 0)

    def test_return_uses_navigator_when_not_daily_tasks_after_leave(self):
        task = FakeSummonTask(Scene.MAIN, page_match_sequence=[True, False, False, False, False, False])

        task._return_to_daily_tasks()

        self.assertEqual(task.tapped, [("leave summon page", "leave_button.png")])
        self.assertEqual(task.context.navigator.go_calls, 1)

    def test_post_confirm_reward_blank_taps_until_page_visible(self):
        task = FakeSummonTask(Scene.DAILY_TASKS, page_match_sequence=[False, True])

        task._dismiss_post_confirm_reward_if_present()

        self.assertEqual(task.context.controller.taps, [(80, 500)])

    def test_return_retries_leave_when_first_tap_only_clears_overlay(self):
        task = FakeSummonTask(
            Scene.UNKNOWN,
            page_match_sequence=[True, True],
            daily_sequence=[False, True],
        )

        task._return_to_daily_tasks()

        self.assertEqual(
            task.tapped,
            [
                ("leave summon page", "leave_button.png"),
                ("leave summon page", "leave_button.png"),
            ],
        )

    def test_page_requirement_accepts_ocr_fallback(self):
        task = FakeSummonTask(Scene.DAILY_TASKS, page_match_sequence=[False])
        task._screen_ocr_indicates_advanced_contract = lambda _screen: True

        task._require_summon_page()

    def test_current_scene_can_resume_from_result_confirm_button(self):
        task = FakeSummonTask(
            Scene.UNKNOWN,
            page_match_sequence=[False, True, True],
            daily_sequence=[True],
            confirm_match_sequence=[True],
        )

        result = task.execute_from_current_scene()

        self.assertEqual(result, "summon result confirmed and returned")
        self.assertEqual(
            task.tapped,
            [
                ("confirm summon result", "confirm_button.png"),
                ("leave summon page", "leave_button.png"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
