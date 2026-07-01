import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.daily_runner import DailyRunner
from src.daily_task_finder import GoFirstTaskRow, TaskSearchResult, TaskSearchStatus
from src.exceptions import TaskSkippedError
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

    def test_failed_adb_stall_result_logs_sleeps_and_stops(self):
        runner = DailyRunner(context=FakeContext())
        result = TaskRunResult("summon", TaskState.FAILED, "ADB screenshot timed out", 1.2)

        out = io.StringIO()
        with patch("src.daily_runner.time.sleep") as sleep, redirect_stdout(out):
            should_stop = runner._handle_failed_run_all_result("run-all", "summon", result, 0.1)

        self.assertTrue(should_stop)
        sleep.assert_called_once_with(0.1)
        self.assertIn("task=summon failed: ADB screenshot timed out", out.getvalue())
        self.assertIn("ADB may be stalled", out.getvalue())
        self.assertIn("stopping run-all", out.getvalue())

    def test_failed_normal_result_logs_without_sleep_and_stops(self):
        runner = DailyRunner(context=FakeContext())
        result = TaskRunResult("arena", TaskState.FAILED, "Cannot find runnable task row for 競技場", 1.2)

        out = io.StringIO()
        with patch("src.daily_runner.time.sleep") as sleep, redirect_stdout(out):
            should_stop = runner._handle_failed_run_all_result("run-all", "arena", result, 0.1)

        self.assertTrue(should_stop)
        sleep.assert_not_called()
        self.assertIn("task=arena failed: Cannot find runnable task row for 競技場", out.getvalue())
        self.assertIn("stopping run-all", out.getvalue())
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

    def test_run_all_go_first_logs_action_debug_dir_and_scan_index(self):
        class Finder:
            def scan_current_screen_go_first(self, _specs):
                return [
                    GoFirstTaskRow(None, TaskSearchResult(TaskSearchStatus.DONE_OR_CLAIMABLE, done_match=_match()), "completed", 420),
                ]

        class Navigator:
            def go_to_daily_tasks(self):
                return True

        context = FakeContext()
        context.finder = Finder()
        context.navigator = Navigator()
        context.controller = SimpleNamespace(debug_actions=True, debug_dir=Path("captures/action_debug/run123"))
        runner = DailyRunner(context=context)

        runner.run_all_go_first(["midas"], log_prefix="run-all", failure_sleep_seconds=0.1)

        messages = [message for message, _force in context.logger.messages]
        self.assertIn("run-all action_debug_dir=captures\\action_debug\\run123", messages)
        self.assertIn("run-all scan=01/30 handled=", messages)

    def test_run_all_go_first_clears_known_blocker_before_scan(self):
        class Finder:
            def __init__(self):
                self.scans = 0

            def scan_current_screen_go_first(self, _specs, screen=None):
                self.scans += 1
                self.last_screen = screen
                return [
                    GoFirstTaskRow(None, TaskSearchResult(TaskSearchStatus.DONE_OR_CLAIMABLE, done_match=_match()), "completed", 420),
                ]

        class Navigator:
            def go_to_daily_tasks(self):
                return True

        class Controller:
            def __init__(self):
                self.screenshots = 0

            def screenshot(self):
                self.screenshots += 1
                return object()

        class Blocker:
            def __init__(self):
                self.calls = 0

            def handle_known_blocker(self, _screen):
                self.calls += 1
                return self.calls == 1

        context = FakeContext()
        context.finder = Finder()
        context.navigator = Navigator()
        context.controller = Controller()
        context.blocker = Blocker()
        runner = DailyRunner(context=context)

        runner.run_all_go_first(["midas"], log_prefix="run-all", failure_sleep_seconds=0.1)

        self.assertEqual(context.blocker.calls, 2)
        self.assertEqual(context.finder.scans, 1)
        self.assertIsNotNone(context.finder.last_screen)
        messages = [message for message, _force in context.logger.messages]
        self.assertIn("run-all cleared known blocker before scan", messages)

    def test_run_all_go_first_returns_failed_result_when_scan_swipe_times_out(self):
        class Finder:
            def scan_current_screen_go_first(self, _specs):
                return []

            def _swipe_until_changed(self, *args, **kwargs):
                raise RuntimeError("ADB command timed out after 45s: adb shell input swipe")

        class Navigator:
            def go_to_daily_tasks(self):
                return True

        context = FakeContext()
        context.finder = Finder()
        context.navigator = Navigator()
        runner = DailyRunner(context=context)

        with patch("src.daily_runner.time.sleep"), redirect_stdout(io.StringIO()):
            results = runner.run_all_go_first(["midas"], log_prefix="run-all", failure_sleep_seconds=0.1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].task_key, "run-all")
        self.assertEqual(results[0].state, TaskState.FAILED)
        self.assertIn("ADB command timed out", results[0].message)

    def test_run_all_go_first_retries_once_after_no_movement_swipe(self):
        class Finder:
            def __init__(self):
                self.scans = 0
                self.swipes = []

            def scan_current_screen_go_first(self, _specs):
                self.scans += 1
                if self.scans == 1:
                    return []
                return [
                    GoFirstTaskRow(None, TaskSearchResult(TaskSearchStatus.DONE_OR_CLAIMABLE, done_match=_match()), "completed", 420),
                ]

            def _swipe_until_changed(self, *args, **kwargs):
                self.swipes.append((args, kwargs))
                return len(self.swipes) == 2

        class Navigator:
            def go_to_daily_tasks(self):
                return True

        context = FakeContext()
        context.finder = Finder()
        context.navigator = Navigator()
        runner = DailyRunner(context=context)

        runner.run_all_go_first(["midas"], log_prefix="run-all", failure_sleep_seconds=0.1)

        self.assertEqual(len(context.finder.swipes), 2)
        self.assertEqual(context.finder.swipes[0][1]["duration_ms"], 700)
        self.assertEqual(context.finder.swipes[1][0], (360, 460, 360, 180))
        self.assertEqual(context.finder.swipes[1][1]["duration_ms"], 900)
        messages = [message for message, _force in context.logger.messages]
        self.assertIn("run-all daily list swipe had no visible movement; retrying with longer swipe", messages)

    def test_run_all_go_first_treats_task_skipped_error_as_skipped(self):
        class Finder:
            def __init__(self):
                self.scans = 0

            def scan_current_screen_go_first(self, _specs):
                self.scans += 1
                if self.scans == 1:
                    return [
                        GoFirstTaskRow("arena", TaskSearchResult(TaskSearchStatus.READY, go_match=_match()), "go", 340),
                    ]
                return [
                    GoFirstTaskRow(None, TaskSearchResult(TaskSearchStatus.DONE_OR_CLAIMABLE, done_match=_match()), "completed", 420),
                ]

            def _swipe_until_changed(self, *args, **kwargs):
                return False

        class Navigator:
            def go_to_daily_tasks(self):
                return True

        class Controller:
            def tap(self, x, y):
                pass

        context = FakeContext()
        context.finder = Finder()
        context.navigator = Navigator()
        context.controller = Controller()
        runner = DailyRunner(context=context)

        with (
            patch("src.tasks.arena.ArenaTask.missing_assets", return_value=()),
            patch("src.tasks.arena.ArenaTask._execute_and_return", side_effect=TaskSkippedError("Arena OCR is uncertain")),
            patch("src.daily_runner.time.sleep"),
        ):
            results = runner.run_all_go_first(["arena"], log_prefix="run-all", failure_sleep_seconds=0.1)

        self.assertEqual(results[0].task_key, "arena")
        self.assertEqual(results[0].state, TaskState.SKIPPED)
        self.assertIn("Arena OCR is uncertain", results[0].message)


def _match() -> MatchResult:
    return MatchResult(
        template_path="go_button.png",
        confidence=0.95,
        center=(840, 300),
        bbox=(768, 280, 144, 40),
    )


if __name__ == "__main__":
    unittest.main()
