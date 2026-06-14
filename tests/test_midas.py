import unittest
from types import SimpleNamespace

from src.exceptions import TaskFailedError
from src.tasks.midas import MidasTask
from src.task_runner import TaskState
from src.vision_matcher import MatchResult


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


class FakeMatcher:
    def match_template(self, *args, **kwargs):
        return None

    def best_template_match(self, screen, path, roi=None):
        return MatchResult(
            template_path=path,
            confidence=0.42,
            center=(111, 222),
            bbox=(100, 210, 22, 24),
            brightness_ratio=0.31,
        )


class FakeScreenshotController(FakeController):
    def screenshot(self):
        return object()


class DiagnosticMidasTask(MidasTask):
    def __init__(self):
        self.context = SimpleNamespace(
            controller=FakeScreenshotController(),
            matcher=FakeMatcher(),
            navigator=FakeNavigator(),
        )


class CleanupMidasTask(MidasTask):
    def __init__(self, active_buttons=(), close_matches=1, fail_after_dialog=False):
        self.active_buttons = set(active_buttons)
        self.close_matches = close_matches
        self.fail_after_dialog = fail_after_dialog
        self.context = SimpleNamespace(controller=FakeController(), navigator=FakeNavigator())

    def _dismiss_reward_overlay_if_present(self):
        return None

    def _require_midas_dialog(self):
        if self.fail_after_dialog:
            raise TaskFailedError("forced Midas failure")
        return FakeMatch()

    def _tap_if_active(self, label, asset_name, roi):
        if asset_name not in self.active_buttons:
            return False
        self.context.controller.tap(*FakeMatch.center)
        return True

    def _match_task_asset(self, asset_name, **kwargs):
        if asset_name != "midas_close_button.png" or self.close_matches <= 0:
            return None
        self.close_matches -= 1
        return FakeMatch()


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

    def test_require_task_asset_reports_best_confidence_on_failure(self):
        task = DiagnosticMidasTask()

        with self.assertRaises(TaskFailedError) as caught:
            task._require_task_asset(
                "Midas dialog",
                "midas_title.png",
                roi=task.TITLE_ROI,
                threshold=0.86,
                timeout_seconds=0.01,
            )

        message = str(caught.exception)
        self.assertIn("best_confidence=0.420", message)
        self.assertIn("threshold=0.860", message)
        self.assertIn("brightness_ratio=0.310", message)
        self.assertIn("roi=(360, 45, 250, 70)", message)
        self.assertIn("center=(111, 222)", message)

    def test_execute_closes_midas_dialog_after_failure(self):
        task = CleanupMidasTask(close_matches=1, fail_after_dialog=True)

        with self.assertRaises(TaskFailedError) as caught:
            task.execute()

        self.assertEqual(str(caught.exception), "forced Midas failure")
        self.assertEqual(task.context.controller.taps, [(123, 456)])

    def test_close_dialog_taps_until_close_button_disappears(self):
        task = CleanupMidasTask(close_matches=3)

        task._close_dialog()

        self.assertEqual(task.context.controller.taps, [(123, 456), (123, 456), (123, 456)])


if __name__ == "__main__":
    unittest.main()
