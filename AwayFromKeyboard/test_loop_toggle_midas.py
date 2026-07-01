import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from AwayFromKeyboard.loop_toggle_midas import (
    AUTO_OCR_FAILURE_SLEEP_SECONDS,
    AUTO_WAKEUP_BUFFER_SECONDS,
    build_auto_account_order,
    build_sweep_first_order,
    process_auto_account,
    run_auto_initial_round,
    run_auto_loop,
    run_auto_round,
    run_auto_sweep_first_round,
    run_midas_once,
)
from AwayFromKeyboard import task_config
from src.tasks.midas import MidasAutoResult


class AutoMidasLoopTests(unittest.TestCase):
    @patch("AwayFromKeyboard.loop_toggle_midas._recover_or_restart")
    @patch("AwayFromKeyboard.loop_toggle_midas.MidasTask")
    @patch("AwayFromKeyboard.loop_toggle_midas.RouteNavigator")
    def test_non_auto_midas_uses_route_and_task_directly(self, MockRoute, MockMidas, mock_recover):
        context = SimpleNamespace(controller=object())
        recovery = object()
        MockMidas.return_value.execute.return_value = "Midas taps: free"

        result = run_midas_once(context, recovery)

        self.assertEqual(result, "Midas taps: free")
        MockRoute.assert_called_once_with(route_name="點金手", controller=context.controller)
        MockRoute.return_value.execute_route.assert_any_call(phase="enter")
        MockRoute.return_value.execute_route.assert_any_call(phase="exit")
        MockMidas.assert_called_once_with(context)
        mock_recover.assert_called_once_with(recovery)

    @patch("AwayFromKeyboard.loop_toggle_midas._save_midas_popup_recovery_debug")
    @patch("AwayFromKeyboard.loop_toggle_midas._recover_or_restart")
    @patch("AwayFromKeyboard.loop_toggle_midas.MidasTask")
    @patch("AwayFromKeyboard.loop_toggle_midas.RouteNavigator")
    def test_midas_closes_known_popup_and_reenters_route(
        self,
        MockRoute,
        MockMidas,
        mock_recover,
        mock_save_failure,
    ):
        from src.exceptions import TaskFailedError

        context = SimpleNamespace(controller=MagicMock())
        recovery = object()
        task = MockMidas.return_value
        task.execute.side_effect = [
            TaskFailedError("Midas expected screen element not found: Midas dialog"),
            "Midas taps: free",
        ]
        MockRoute.return_value.handle_blocking_popup.return_value = True

        result = run_midas_once(context, recovery)

        self.assertEqual(result, "Midas taps: free")
        self.assertEqual(task.execute.call_count, 2)
        self.assertEqual(
            MockRoute.return_value.execute_route.call_args_list,
            [call(phase="enter"), call(phase="enter"), call(phase="exit")],
        )
        self.assertEqual(mock_recover.call_count, 2)
        mock_save_failure.assert_called_once()

    @patch("AwayFromKeyboard.loop_toggle_midas._save_midas_popup_recovery_debug")
    @patch("AwayFromKeyboard.loop_toggle_midas._recover_or_restart")
    @patch("AwayFromKeyboard.loop_toggle_midas.MidasTask")
    @patch("AwayFromKeyboard.loop_toggle_midas.RouteNavigator")
    def test_midas_popup_recovery_stops_after_three_retries(
        self,
        MockRoute,
        MockMidas,
        mock_recover,
        mock_save_failure,
    ):
        from src.exceptions import TaskFailedError

        context = SimpleNamespace(controller=MagicMock())
        MockMidas.return_value.execute.side_effect = TaskFailedError("Midas dialog missing")
        MockRoute.return_value.handle_blocking_popup.return_value = True

        with self.assertRaises(TaskFailedError):
            run_midas_once(context, object())

        self.assertEqual(MockMidas.return_value.execute.call_count, 4)
        self.assertEqual(MockRoute.return_value.handle_blocking_popup.call_count, 3)
        self.assertEqual(mock_save_failure.call_count, 3)
        self.assertEqual(mock_recover.call_count, 4)

    def test_afk_midas_command_cannot_fall_back_to_daily_tasks(self):
        self.assertEqual(
            task_config.get_command_for_task("點金手"),
            ["-m", "src.main", "--debug", "run-current-scene-task", "midas"],
        )

    def test_first_run_also_uses_fixed_account_order(self):
        accounts = {
            "em3": {"type": "google"},
            "311": {"type": "google"},
            "tiger": {"type": "email"},
            "14": {"type": "email"},
        }

        self.assertEqual(
            build_auto_account_order(accounts, True),
            ["em3", "311", "tiger", "14"],
        )
        self.assertEqual(
            build_auto_account_order(accounts, False),
            ["em3", "311"],
        )

    def test_later_two_account_round_starts_from_em3(self):
        accounts = {
            "em3": {"type": "google"},
            "311": {"type": "google"},
            "tiger": {"type": "email"},
            "14": {"type": "email"},
        }

        self.assertEqual(
            build_auto_account_order(accounts, False),
            ["em3", "311"],
        )

    def test_all_account_order_contains_each_account_once(self):
        accounts = {
            "14": {"type": "email"},
            "tiger": {"type": "email"},
            "311": {"type": "google"},
            "em3": {"type": "google"},
        }

        order = build_auto_account_order(accounts, True)

        self.assertEqual(order, ["em3", "311", "tiger", "14"])
        self.assertEqual(len(order), len(set(order)))

    def test_sweep_first_order_minimizes_google_email_switches(self):
        accounts = {
            "em3": {"type": "google"},
            "311": {"type": "google"},
            "tiger": {"type": "email"},
            "14": {"type": "email"},
        }

        self.assertEqual(
            build_sweep_first_order("em3", accounts, True),
            ["em3", "311", "tiger", "14", "em3"],
        )
        self.assertEqual(
            build_sweep_first_order("311", accounts, True),
            ["311", "tiger", "14", "em3"],
        )
        self.assertEqual(
            build_sweep_first_order("tiger", accounts, True),
            ["tiger", "14", "311", "em3"],
        )
        self.assertEqual(
            build_sweep_first_order("14", accounts, True),
            ["14", "tiger", "311", "em3"],
        )

    @patch("AwayFromKeyboard.loop_toggle_midas.time.sleep")
    @patch("AwayFromKeyboard.loop_toggle_midas.run_midas_auto_once")
    @patch("AwayFromKeyboard.loop_toggle_midas._recover_or_restart")
    def test_short_cooldown_waits_then_retries_until_clicked(self, mock_recover, mock_run, mock_sleep):
        mock_run.side_effect = [
            MidasAutoResult(False, 120, "00:02:00", 0.9),
            MidasAutoResult(True),
        ]
        recovery = MagicMock()

        result = process_auto_account(object(), recovery, "em3")

        self.assertTrue(result)
        mock_sleep.assert_called_once_with(120)
        self.assertEqual(mock_run.call_count, 2)
        recovery.handle_wakeup_exceptions.assert_called_once()
        mock_recover.assert_called_once_with(recovery)

    @patch("AwayFromKeyboard.loop_toggle_midas.run_midas_auto_once")
    def test_long_cooldown_moves_to_next_account(self, mock_run):
        mock_run.return_value = MidasAutoResult(False, 301, "00:05:01", 0.9)

        self.assertTrue(process_auto_account(object(), object(), "em3"))
        mock_run.assert_called_once()

    @patch("AwayFromKeyboard.loop_toggle_midas.run_midas_auto_once")
    def test_intermediate_ocr_failure_moves_to_next_account(self, mock_run):
        mock_run.return_value = MidasAutoResult(False, None, "O1:2B:22", 0.42)

        self.assertTrue(process_auto_account(object(), object(), "em3"))

    @patch("AwayFromKeyboard.loop_toggle_midas.run_midas_auto_once")
    @patch("AwayFromKeyboard.loop_toggle_midas.process_auto_account", return_value=True)
    @patch("AwayFromKeyboard.loop_toggle_midas.switch_account", return_value=True)
    @patch("AwayFromKeyboard.loop_toggle_midas.detect_current_account", return_value="311")
    @patch("AwayFromKeyboard.loop_toggle_midas._recover_or_restart")
    def test_round_returns_to_em3_and_uses_final_cooldown(
        self,
        mock_recover,
        mock_detect,
        mock_switch,
        mock_process,
        mock_run,
    ):
        context = SimpleNamespace(controller=object(), matcher=object())
        recovery = MagicMock()
        mock_run.return_value = MidasAutoResult(False, 7200, "02:00:00", 0.9)
        accounts = {
            "em3": {"type": "google"},
            "311": {"type": "google"},
            "tiger": {"type": "email"},
            "14": {"type": "email"},
        }

        sleep_seconds = run_auto_round(
            context,
            recovery,
            accounts=accounts,
            use_all=False,
        )

        self.assertEqual(sleep_seconds, 7200 - AUTO_WAKEUP_BUFFER_SECONDS)
        self.assertEqual([call.args[2] for call in mock_process.call_args_list], ["em3", "311"])
        self.assertEqual([call.args[0] for call in mock_switch.call_args_list], ["em3", "311", "em3"])
        mock_run.assert_called_once_with(context, recovery, require_cooldown=True)

    @patch("AwayFromKeyboard.loop_toggle_midas.run_midas_auto_once")
    @patch("AwayFromKeyboard.loop_toggle_midas.process_auto_account", return_value=True)
    @patch("AwayFromKeyboard.loop_toggle_midas.switch_account", return_value=True)
    @patch("AwayFromKeyboard.loop_toggle_midas.detect_current_account", return_value="14")
    @patch("AwayFromKeyboard.loop_toggle_midas._recover_or_restart")
    def test_round_ocr_failure_returns_em3_and_sleeps_two_hours(
        self,
        mock_recover,
        mock_detect,
        mock_switch,
        mock_process,
        mock_run,
    ):
        context = SimpleNamespace(controller=object(), matcher=object())
        recovery = MagicMock()
        accounts = {
            "em3": {"type": "google"},
            "311": {"type": "google"},
            "tiger": {"type": "email"},
            "14": {"type": "email"},
        }

        mock_run.return_value = MidasAutoResult(False, None, "37:", 0.083)

        sleep_seconds = run_auto_round(
            context,
            recovery,
            accounts=accounts,
            use_all=True,
        )

        self.assertEqual(sleep_seconds, AUTO_OCR_FAILURE_SLEEP_SECONDS)
        self.assertEqual([call.args[2] for call in mock_process.call_args_list], ["em3", "311", "tiger", "14"])
        self.assertEqual([call.args[0] for call in mock_switch.call_args_list], ["em3", "311", "tiger", "14", "em3"])

    @patch("AwayFromKeyboard.loop_toggle_midas.run_midas_auto_once")
    @patch("AwayFromKeyboard.loop_toggle_midas.process_auto_account", return_value=True)
    @patch("AwayFromKeyboard.loop_toggle_midas.switch_account", return_value=True)
    @patch("AwayFromKeyboard.loop_toggle_midas.detect_current_account", return_value="311")
    @patch("AwayFromKeyboard.loop_toggle_midas._recover_or_restart")
    def test_initial_round_runs_current_account_then_returns_em3_for_sleep(
        self,
        mock_recover,
        mock_detect,
        mock_switch,
        mock_process,
        mock_run,
    ):
        context = SimpleNamespace(controller=object(), matcher=object())
        recovery = MagicMock()
        mock_run.return_value = MidasAutoResult(False, 3600, "01:00:00", 0.9)

        sleep_seconds = run_auto_initial_round(context, recovery)

        self.assertEqual(sleep_seconds, 3600 - AUTO_WAKEUP_BUFFER_SECONDS)
        mock_process.assert_called_once_with(context, recovery, "311", notify_enabled=False)
        mock_switch.assert_called_once_with("em3")
        mock_run.assert_called_once_with(context, recovery, require_cooldown=True)

    @patch("AwayFromKeyboard.loop_toggle_midas.run_midas_auto_once")
    @patch("AwayFromKeyboard.loop_toggle_midas.process_auto_account", return_value=True)
    @patch("AwayFromKeyboard.loop_toggle_midas.switch_account", return_value=True)
    @patch("AwayFromKeyboard.loop_toggle_midas.detect_current_account", return_value="tiger")
    @patch("AwayFromKeyboard.loop_toggle_midas._recover_or_restart")
    def test_sweep_first_round_uses_requested_order_then_reads_em3_cooldown(
        self,
        mock_recover,
        mock_detect,
        mock_switch,
        mock_process,
        mock_run,
    ):
        context = SimpleNamespace(controller=object(), matcher=object())
        recovery = MagicMock()
        accounts = {
            "em3": {"type": "google"},
            "311": {"type": "google"},
            "tiger": {"type": "email"},
            "14": {"type": "email"},
        }
        mock_run.return_value = MidasAutoResult(False, 3600, "01:00:00", 0.9)

        sleep_seconds = run_auto_sweep_first_round(
            context,
            recovery,
            accounts=accounts,
            use_all=True,
        )

        self.assertEqual(sleep_seconds, 3600 - AUTO_WAKEUP_BUFFER_SECONDS)
        self.assertEqual([call.args[2] for call in mock_process.call_args_list], ["tiger", "14", "311"])
        self.assertEqual([call.args[0] for call in mock_switch.call_args_list], ["14", "311", "em3"])
        mock_run.assert_called_once_with(context, recovery, require_cooldown=True)

    @patch("AwayFromKeyboard.loop_toggle_midas.time.sleep", side_effect=KeyboardInterrupt)
    @patch("AwayFromKeyboard.loop_toggle_midas.run_auto_round")
    @patch("AwayFromKeyboard.loop_toggle_midas.run_auto_initial_round", return_value=123)
    @patch("AwayFromKeyboard.loop_toggle_midas.load_accounts", return_value={"em3": {}, "311": {}})
    def test_auto_loop_sleeps_after_initial_round_before_later_rounds(
        self,
        mock_load,
        mock_initial,
        mock_round,
        mock_sleep,
    ):
        with self.assertRaises(KeyboardInterrupt):
            run_auto_loop(object(), object(), use_all=False)

        mock_initial.assert_called_once()
        mock_sleep.assert_called_once_with(123)
        mock_round.assert_not_called()

    @patch("AwayFromKeyboard.loop_toggle_midas.time.sleep", side_effect=KeyboardInterrupt)
    @patch("AwayFromKeyboard.loop_toggle_midas.run_auto_round")
    @patch("AwayFromKeyboard.loop_toggle_midas.run_auto_sweep_first_round", return_value=234)
    @patch("AwayFromKeyboard.loop_toggle_midas.run_auto_initial_round")
    @patch("AwayFromKeyboard.loop_toggle_midas.load_accounts", return_value={"em3": {}, "311": {}})
    def test_auto_loop_can_use_sweep_first_initial_round(
        self,
        mock_load,
        mock_initial,
        mock_sweep,
        mock_round,
        mock_sleep,
    ):
        with self.assertRaises(KeyboardInterrupt):
            run_auto_loop(object(), object(), use_all=False, sweep_first=True)

        mock_sweep.assert_called_once()
        mock_initial.assert_not_called()
        mock_sleep.assert_called_once_with(234)
        mock_round.assert_not_called()


if __name__ == "__main__":
    unittest.main()
