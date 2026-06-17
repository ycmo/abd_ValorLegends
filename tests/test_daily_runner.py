import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from src.daily_runner import DailyRunner
from src.daily_task_finder import GoFirstTaskRow, TaskSearchResult, TaskSearchStatus
from src.task_runner import TaskRunResult, TaskState
from src.vision_matcher import MatchResult


class FakeLogger:
    def __init__(self):
        self.messages = []

    def log(self, message, force=False):
        self.messages.append((message, force))


class FakeContext:
    def __init__(self):
        self.logger = FakeLogger()


class DailyRunnerRunAllTests(unittest.TestCase):
    def test_run_all_delegates_to_go_first_with_run_all_log_prefix(self):
        runner = DailyRunner(context=FakeContext())
        expected = [TaskRunResult("midas", TaskState.COMPLETED, "ok", 0.5)]

        with patch.object(runner, "run_all_go_first", return_value=expected) as run_all_go_first:
            results = runner.run_all(["summon", "midas"], failure_sleep_seconds=0.1)

        self.assertEqual(results, expected)
        run_all_go_first.assert_called_once_with(
            ["summon", "midas"],
            log_prefix="run-all",
            failure_sleep_seconds=0.1,
        )

    def test_failed_adb_stall_result_logs_sleeps_and_continues(self):
        runner = DailyRunner(context=FakeContext())
        result = TaskRunResult("summon", TaskState.FAILED, "ADB screenshot timed out", 1.2)

        out = io.StringIO()
        with patch("src.daily_runner.time.sleep") as sleep, redirect_stdout(out):
            runner._handle_failed_run_all_result("run-all", "summon", result, 0.1)

        sleep.assert_called_once_with(0.1)
        self.assertIn("task=summon failed: ADB screenshot timed out", out.getvalue())
        self.assertIn("ADB may be stalled", out.getvalue())

    def test_failed_normal_result_logs_without_sleep(self):
        runner = DailyRunner(context=FakeContext())
        result = TaskRunResult("arena", TaskState.FAILED, "Cannot find runnable task row for 競技場", 1.2)

        out = io.StringIO()
        with patch("src.daily_runner.time.sleep") as sleep, redirect_stdout(out):
            runner._handle_failed_run_all_result("run-all", "arena", result, 0.1)

        sleep.assert_not_called()
        self.assertIn("task=arena failed: Cannot find runnable task row for 競技場", out.getvalue())
        self.assertNotIn("sleeping", out.getvalue())

    def test_run_all_go_first_uses_detected_screen_order(self):
        class Finder:
            def __init__(self):
                self.scans = 0

            def scan_current_screen_go_first(self, _specs):
                self.scans += 1
                if self.scans == 1:
                    return [
                        GoFirstTaskRow("midas", TaskSearchResult(TaskSearchStatus.READY, go_match=_match()), "go", 260),
                        GoFirstTaskRow("arena", TaskSearchResult(TaskSearchStatus.READY, go_match=_match()), "go", 340),
                    ]
                return [
                    GoFirstTaskRow("arena", TaskSearchResult(TaskSearchStatus.READY, go_match=_match()), "go", 340),
                ]

            def _swipe_until_changed(self, *args, **kwargs):
                return False

        class Navigator:
            def go_to_daily_tasks(self):
                return True

        class Controller:
            def __init__(self):
                self.taps = []

            def tap(self, x, y):
                self.taps.append((x, y))

        context = FakeContext()
        context.finder = Finder()
        context.navigator = Navigator()
        context.controller = Controller()
        runner = DailyRunner(context=context)

        with (
            patch("src.tasks.midas.MidasTask.missing_assets", return_value=()),
            patch("src.tasks.midas.MidasTask._execute_and_return", return_value=TaskRunResult("midas", TaskState.COMPLETED, "ok", 1.0)),
            patch("src.tasks.arena.ArenaTask.missing_assets", return_value=()),
            patch("src.tasks.arena.ArenaTask._execute_and_return", return_value=TaskRunResult("arena", TaskState.COMPLETED, "ok", 1.0)),
            patch("src.daily_runner.time.sleep"),
        ):
            results = runner.run_all_go_first(["arena", "midas"], failure_sleep_seconds=0.1)

        self.assertEqual([result.task_key for result in results], ["midas", "arena"])
        self.assertEqual([result.state for result in results], [TaskState.COMPLETED, TaskState.COMPLETED])
        self.assertEqual(context.controller.taps, [(840, 300), (840, 300)])

    def test_run_all_go_first_stops_at_completed_section_after_skipped_go_rows(self):
        class Finder:
            def __init__(self):
                self.swipes = []

            def scan_current_screen_go_first(self, _specs):
                return [
                    GoFirstTaskRow(None, TaskSearchResult(TaskSearchStatus.READY, go_match=_match()), "go", 260),
                    GoFirstTaskRow("campaign", TaskSearchResult(TaskSearchStatus.READY, go_match=_match()), "go", 300),
                    GoFirstTaskRow("endless_trial", TaskSearchResult(TaskSearchStatus.READY, go_match=_match()), "go", 340),
                    GoFirstTaskRow(None, TaskSearchResult(TaskSearchStatus.DONE_OR_CLAIMABLE, done_match=_match()), "completed", 420),
                ]

            def _swipe_until_changed(self, *args, **kwargs):
                self.swipes.append((args, kwargs))
                return True

        class Navigator:
            def go_to_daily_tasks(self):
                return True

        class Controller:
            def __init__(self):
                self.taps = []

            def tap(self, x, y):
                self.taps.append((x, y))

        context = FakeContext()
        context.finder = Finder()
        context.navigator = Navigator()
        context.controller = Controller()
        runner = DailyRunner(context=context)

        results = runner.run_all_go_first(["midas"], failure_sleep_seconds=0.1)

        self.assertEqual(results, [])
        self.assertEqual(context.controller.taps, [])
        self.assertEqual(context.finder.swipes, [])


def _match() -> MatchResult:
    return MatchResult(
        template_path="go_button.png",
        confidence=0.95,
        center=(840, 300),
        bbox=(768, 280, 144, 40),
    )


if __name__ == "__main__":
    unittest.main()
