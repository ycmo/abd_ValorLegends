import unittest
from types import SimpleNamespace

from src.tasks.midas import MidasTask
from src.task_runner import TaskState


class FakeMatch:
    center = (123, 456)


class FakeController:
    def __init__(self):
        self.taps = []

    def tap(self, x, y):
        self.taps.append((x, y))


class FakeNavigator:
    def __init__(self):
        self.return_calls = 0

    def return_to_daily_tasks(self):
        self.return_calls += 1
        return True


class FakeMidasTask(MidasTask):
    def __init__(self, active_assets):
        self.active_assets = set(active_assets)
        self.context = SimpleNamespace(controller=FakeController(), navigator=FakeNavigator())

    def _match_task_asset(self, asset_name, **kwargs):
        return FakeMatch() if asset_name in self.active_assets else None


class MidasSafetyTests(unittest.TestCase):
    def test_tap_if_active_does_not_tap_missing_button(self):
        task = FakeMidasTask(active_assets=())

        tapped = task._tap_if_active("free", "free_button.png", task.FREE_BUTTON_ROI)

        self.assertFalse(tapped)
        self.assertEqual(task.context.controller.taps, [])

    def test_tap_if_active_taps_active_button_once(self):
        task = FakeMidasTask(active_assets=("free_button.png",))

        tapped = task._tap_if_active("free", "free_button.png", task.FREE_BUTTON_ROI)

        self.assertTrue(tapped)
        self.assertEqual(task.context.controller.taps, [(123, 456)])

    def test_execute_and_return_does_not_navigate_after_closing_midas(self):
        task = FakeMidasTask(active_assets=())
        task.execute_from_current_scene = lambda: "Midas taps: free"

        result = task._execute_and_return(started=0.0)

        self.assertEqual(result.state, TaskState.COMPLETED)
        self.assertEqual(result.message, "Midas taps: free")
        self.assertEqual(task.context.navigator.return_calls, 0)


if __name__ == "__main__":
    unittest.main()
