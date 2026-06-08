import unittest

from src.config import TASK_SPECS
from src.exceptions import TaskFailedError, TaskSkippedError
from src.navigator import OpenTaskResult, OpenTaskStatus
from src.task_runner import BaseTask, TaskState


class FakeController:
    def __init__(self):
        self.taps = []

    def screenshot(self):
        return object()

    def tap(self, x, y):
        self.taps.append((x, y))


class FakeNavigator:
    def __init__(self):
        self.open_calls = 0
        self.return_calls = 0

    def open_task_from_daily(self, _spec):
        self.open_calls += 1
        return OpenTaskResult(OpenTaskStatus.OPENED)

    def open_task_from_current_daily_screen(self, _spec):
        self.open_calls += 1
        return OpenTaskResult(OpenTaskStatus.OPENED)

    def return_to_daily_tasks(self):
        self.return_calls += 1
        return True


class FakeContext:
    def __init__(self):
        self.controller = FakeController()
        self.navigator = FakeNavigator()


class FakeSceneTask(BaseTask):
    spec = TASK_SPECS["time_travel"]
    required_assets = ()

    def __init__(self, context, in_scene):
        super().__init__(context)
        self.in_scene = in_scene
        self.executed = 0

    def missing_assets(self):
        return ()

    def is_task_scene(self, _screen):
        return self.in_scene

    def execute(self):
        self.executed += 1
        return "executed"


class FakeSkippedTask(FakeSceneTask):
    def execute(self):
        self.executed += 1
        raise TaskSkippedError("safe skip")


class CurrentSceneRunnerTests(unittest.TestCase):
    def test_run_prefers_existing_task_scene_before_daily_navigation(self):
        context = FakeContext()
        task = FakeSceneTask(context, in_scene=True)

        result = task.run()

        self.assertEqual(result.state, TaskState.COMPLETED)
        self.assertEqual(task.executed, 1)
        self.assertEqual(context.navigator.open_calls, 0)
        self.assertEqual(context.navigator.return_calls, 1)

    def test_run_opens_from_daily_when_current_screen_is_not_task_scene(self):
        context = FakeContext()
        task = FakeSceneTask(context, in_scene=False)

        result = task.run()

        self.assertEqual(result.state, TaskState.COMPLETED)
        self.assertEqual(task.executed, 1)
        self.assertEqual(context.navigator.open_calls, 1)
        self.assertEqual(context.navigator.return_calls, 1)

    def test_run_current_scene_fails_without_matching_task_scene(self):
        context = FakeContext()
        task = FakeSceneTask(context, in_scene=False)

        result = task.run_from_current_scene()

        self.assertEqual(result.state, TaskState.FAILED)
        self.assertIn("Current screen is not", result.message)
        self.assertEqual(task.executed, 0)
        self.assertEqual(context.navigator.open_calls, 0)
        self.assertEqual(context.navigator.return_calls, 0)

    def test_task_skipped_error_returns_skipped_state(self):
        context = FakeContext()
        task = FakeSkippedTask(context, in_scene=True)

        result = task.run()

        self.assertEqual(result.state, TaskState.SKIPPED)
        self.assertEqual(result.message, "safe skip")
        self.assertEqual(task.executed, 1)
        self.assertEqual(context.navigator.return_calls, 0)

    def test_reward_blank_tap_helper_stops_when_closed(self):
        context = FakeContext()
        task = FakeSceneTask(context, in_scene=True)
        checks = [False, True]

        task.dismiss_reward_overlay_by_blank_taps(is_closed=lambda: checks.pop(0))

        self.assertEqual(context.controller.taps, [(80, 500)])

    def test_reward_blank_tap_helper_raises_when_still_open(self):
        context = FakeContext()
        task = FakeSceneTask(context, in_scene=True)

        with self.assertRaises(TaskFailedError):
            task.dismiss_reward_overlay_by_blank_taps(is_closed=lambda: False, max_taps=2)

        self.assertEqual(context.controller.taps, [(80, 500), (80, 500)])


if __name__ == "__main__":
    unittest.main()
