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
    def __init__(self, scene, page_match_sequence=None):
        self.tapped = []
        self.blank_taps = []
        self.page_match_sequence = list(page_match_sequence or [])
        self.context = SimpleNamespace(
            controller=FakeController(),
            detector=FakeDetector(scene),
            navigator=FakeNavigator(),
        )

    def _match_task_asset(self, asset_name, **kwargs):
        if asset_name == "advanced_contract_label.png" and self.page_match_sequence:
            return object() if self.page_match_sequence.pop(0) else None
        return object() if asset_name == "advanced_contract_label.png" else None

    def _tap_task_asset(self, label, asset_name, **kwargs):
        self.tapped.append((label, asset_name))
        return object()


class SummonReturnTests(unittest.TestCase):
    def test_return_uses_leave_button_then_stops_on_daily_tasks(self):
        task = FakeSummonTask(Scene.DAILY_TASKS)

        task._return_to_daily_tasks()

        self.assertEqual(task.tapped, [("leave summon page", "leave_button.png")])
        self.assertEqual(task.context.navigator.go_calls, 0)

    def test_return_uses_navigator_when_not_daily_tasks_after_leave(self):
        task = FakeSummonTask(Scene.MAIN)

        task._return_to_daily_tasks()

        self.assertEqual(task.tapped, [("leave summon page", "leave_button.png")])
        self.assertEqual(task.context.navigator.go_calls, 1)

    def test_post_confirm_reward_blank_taps_until_page_visible(self):
        task = FakeSummonTask(Scene.DAILY_TASKS, page_match_sequence=[False, True])

        task._dismiss_post_confirm_reward_if_present()

        self.assertEqual(task.context.controller.taps, [(80, 500)])


if __name__ == "__main__":
    unittest.main()
