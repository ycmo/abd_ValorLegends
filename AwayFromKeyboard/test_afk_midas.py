import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from AwayFromKeyboard.afk_midas import (
    AUTO_OCR_FAILURE_SLEEP_SECONDS,
    AUTO_WAKEUP_BUFFER_SECONDS,
    _handle_wakeup_exceptions_if_available,
    build_auto_account_order,
    calculate_midas_wake_at,
    build_sweep_first_order,
    choose_next_account,
    execute_scheduled_midas_account,
    format_schedule_decision,
    main,
    midas_task_debug_actions,
    process_auto_account,
    rotate_midas_action_debug_dir_if_new_day,
    run_auto_initial_round,
    run_auto_loop,
    run_auto_round,
    run_auto_sweep_first_round,
    run_midas_auto_with_ocr_retry,
    run_midas_once,
    switch_to_account_if_needed,
    update_timing_average,
)
from AwayFromKeyboard import task_config
from src.account_state import TAIPEI_TZ
from src.tasks.midas import MidasAutoResult


class AutoMidasLoopTests(unittest.TestCase):
    def setUp(self):
        self.write_patcher = patch("AwayFromKeyboard.afk_midas.write_current_account")
        self.mock_write_current_account = self.write_patcher.start()
        self.activity_patcher = patch("AwayFromKeyboard.afk_midas.write_activity_state")
        self.mock_write_activity_state = self.activity_patcher.start()
        self.clear_activity_patcher = patch("AwayFromKeyboard.afk_midas.clear_activity_state")
        self.mock_clear_activity_state = self.clear_activity_patcher.start()

    def tearDown(self):
        self.clear_activity_patcher.stop()
        self.activity_patcher.stop()
        self.write_patcher.stop()

    @patch("AwayFromKeyboard.afk_midas._recover_or_restart")
    def test_wakeup_exception_check_direct_retries_adb_wobble_without_recovery(self, mock_recover):
        from src.adb_controller import AdbControllerError

        recovery = MagicMock()
        recovery.handle_wakeup_exceptions.side_effect = [AdbControllerError("screencap failed"), False]

        result = _handle_wakeup_exceptions_if_available(recovery)

        self.assertFalse(result)
        self.assertEqual(recovery.handle_wakeup_exceptions.call_count, 2)
        mock_recover.assert_not_called()

    @patch("AwayFromKeyboard.afk_midas._recover_or_restart")
    def test_wakeup_exception_check_recovers_after_direct_retry_fails(self, mock_recover):
        from src.adb_controller import AdbControllerError

        recovery = MagicMock()
        recovery.handle_wakeup_exceptions.side_effect = [
            AdbControllerError("screencap failed"),
            AdbControllerError("screencap failed again"),
            True,
        ]

        result = _handle_wakeup_exceptions_if_available(recovery)

        self.assertTrue(result)
        self.assertEqual(recovery.handle_wakeup_exceptions.call_count, 3)
        mock_recover.assert_called_once_with(recovery)

    @patch("AwayFromKeyboard.afk_midas._recover_or_restart")
    @patch("AwayFromKeyboard.afk_midas.MidasTask")
    @patch("AwayFromKeyboard.afk_midas.RouteNavigator")
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

    @patch("AwayFromKeyboard.afk_midas._save_midas_popup_recovery_debug")
    @patch("AwayFromKeyboard.afk_midas._recover_or_restart")
    @patch("AwayFromKeyboard.afk_midas.MidasTask")
    @patch("AwayFromKeyboard.afk_midas.RouteNavigator")
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

    @patch("AwayFromKeyboard.afk_midas._save_midas_popup_recovery_debug")
    @patch("AwayFromKeyboard.afk_midas._recover_or_restart")
    @patch("AwayFromKeyboard.afk_midas.MidasTask")
    @patch("AwayFromKeyboard.afk_midas.RouteNavigator")
    def test_midas_route_enter_failure_runs_recovery_then_retries(
        self,
        MockRoute,
        MockMidas,
        mock_recover,
        mock_save_failure,
    ):
        context = SimpleNamespace(controller=MagicMock())
        recovery = object()
        route = MockRoute.return_value
        route.execute_route.side_effect = [
            ValueError("route enter blocked by gift pack"),
            None,
            None,
        ]
        MockMidas.return_value.execute.return_value = "Midas taps: free"

        result = run_midas_once(context, recovery)

        self.assertEqual(result, "Midas taps: free")
        self.assertEqual(
            route.execute_route.call_args_list,
            [call(phase="enter"), call(phase="enter"), call(phase="exit")],
        )
        route.handle_blocking_popup.assert_called_once()
        self.assertEqual(mock_recover.call_count, 2)
        mock_save_failure.assert_called_once()

    @patch("AwayFromKeyboard.afk_midas._save_midas_popup_recovery_debug")
    @patch("AwayFromKeyboard.afk_midas._recover_or_restart")
    @patch("AwayFromKeyboard.afk_midas.MidasTask")
    @patch("AwayFromKeyboard.afk_midas.RouteNavigator")
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

    def test_midas_action_debug_dir_rotates_once_per_day(self):
        controller = SimpleNamespace(debug_actions=True, reset_action_debug_dir=MagicMock())
        context = SimpleNamespace(controller=controller)

        with patch("AwayFromKeyboard.afk_midas.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 7, 10, 12, 0, tzinfo=TAIPEI_TZ)
            rotate_midas_action_debug_dir_if_new_day(context)
            rotate_midas_action_debug_dir_if_new_day(context)
            mock_datetime.now.return_value = datetime(2026, 7, 11, 0, 1, tzinfo=TAIPEI_TZ)
            rotate_midas_action_debug_dir_if_new_day(context)

        self.assertEqual(
            controller.reset_action_debug_dir.call_args_list,
            [call("midas"), call("midas")],
        )

    def test_midas_task_debug_actions_temporarily_disables_task_debug_by_default(self):
        controller = SimpleNamespace(debug_actions=True)
        context = SimpleNamespace(controller=controller)

        with midas_task_debug_actions(context, enabled=False):
            self.assertFalse(controller.debug_actions)

        self.assertTrue(controller.debug_actions)

    def test_midas_task_debug_actions_keeps_debug_enabled_when_requested(self):
        controller = SimpleNamespace(debug_actions=True)
        context = SimpleNamespace(controller=controller)

        with midas_task_debug_actions(context, enabled=True):
            self.assertTrue(controller.debug_actions)

        self.assertTrue(controller.debug_actions)

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

    @patch("AwayFromKeyboard.afk_midas.smart_sleep")
    @patch("AwayFromKeyboard.afk_midas.run_midas_auto_once")
    @patch("AwayFromKeyboard.afk_midas._recover_or_restart")
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
        self.mock_write_activity_state.assert_called_with(
            "midas_auto",
            active=True,
            source="midas.auto.short_cooldown_sleep",
        )

    @patch("AwayFromKeyboard.afk_midas.run_midas_auto_once")
    def test_long_cooldown_moves_to_next_account(self, mock_run):
        mock_run.return_value = MidasAutoResult(False, 301, "00:05:01", 0.9)

        self.assertTrue(process_auto_account(object(), object(), "em3"))
        mock_run.assert_called_once()

    @patch("AwayFromKeyboard.afk_midas.run_midas_auto_once")
    def test_intermediate_ocr_failure_moves_to_next_account(self, mock_run):
        mock_run.return_value = MidasAutoResult(False, None, "O1:2B:22", 0.42)

        self.assertTrue(process_auto_account(object(), object(), "em3"))

    @patch("AwayFromKeyboard.afk_midas.run_midas_auto_once")
    @patch("AwayFromKeyboard.afk_midas.process_auto_account", return_value=True)
    @patch("AwayFromKeyboard.afk_midas.switch_account", return_value=True)
    @patch("AwayFromKeyboard.afk_midas.detect_current_account", return_value="311")
    @patch("AwayFromKeyboard.afk_midas._recover_or_restart")
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
        mock_run.assert_called_once_with(context, recovery, require_cooldown=True, midas_debug_actions=False)

    @patch("AwayFromKeyboard.afk_midas.run_midas_auto_once")
    @patch("AwayFromKeyboard.afk_midas.process_auto_account", return_value=True)
    @patch("AwayFromKeyboard.afk_midas.switch_account", return_value=True)
    @patch("AwayFromKeyboard.afk_midas.detect_current_account", return_value="14")
    @patch("AwayFromKeyboard.afk_midas._recover_or_restart")
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

    @patch("AwayFromKeyboard.afk_midas.run_midas_auto_once")
    @patch("AwayFromKeyboard.afk_midas.process_auto_account", return_value=True)
    @patch("AwayFromKeyboard.afk_midas.switch_account", return_value=True)
    @patch("AwayFromKeyboard.afk_midas.detect_current_account", return_value="311")
    @patch("AwayFromKeyboard.afk_midas._recover_or_restart")
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
        mock_process.assert_called_once_with(context, recovery, "311", notify_enabled=False, midas_debug_actions=False)
        mock_switch.assert_called_once_with("em3")
        mock_run.assert_called_once_with(context, recovery, require_cooldown=True, midas_debug_actions=False)

    @patch("AwayFromKeyboard.afk_midas.run_midas_auto_once")
    @patch("AwayFromKeyboard.afk_midas.process_auto_account", return_value=True)
    @patch("AwayFromKeyboard.afk_midas.switch_account", return_value=True)
    @patch("AwayFromKeyboard.afk_midas.detect_current_account", return_value="tiger")
    @patch("AwayFromKeyboard.afk_midas._recover_or_restart")
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
        mock_run.assert_called_once_with(context, recovery, require_cooldown=True, midas_debug_actions=False)

    def test_update_timing_average_first_sample_replaces_default(self):
        schedule = {"timing": {"switch_google_google": {"seconds": 180, "samples": 0}}}

        update_timing_average(schedule, "switch_google_google", 42)
        update_timing_average(schedule, "switch_google_google", 52)

        self.assertEqual(schedule["timing"]["switch_google_google"]["samples"], 2)
        self.assertAlmostEqual(schedule["timing"]["switch_google_google"]["seconds"], 44.0)

    @patch("AwayFromKeyboard.afk_midas.save_midas_schedule")
    @patch("AwayFromKeyboard.afk_midas.robust_switch_account", return_value=True)
    @patch("AwayFromKeyboard.afk_midas.notify_status")
    @patch("AwayFromKeyboard.afk_midas.time.monotonic", side_effect=[100.0, 142.0])
    def test_switch_to_account_saves_timing_immediately(
        self,
        mock_monotonic,
        mock_notify,
        mock_switch,
        mock_save,
    ):
        schedule = {"timing": {"switch_google_google": {"seconds": 180, "samples": 0}}}
        accounts = {"em3": {"type": "google"}, "311": {"type": "google"}}

        result = switch_to_account_if_needed(
            "311",
            active_account="em3",
            accounts=accounts,
            recovery=MagicMock(),
            schedule=schedule,
            notify_enabled=False,
            switch_recovery_options={},
        )

        self.assertEqual(result, "311")
        self.assertEqual(schedule["timing"]["switch_google_google"]["samples"], 1)
        self.assertEqual(schedule["timing"]["switch_google_google"]["seconds"], 42.0)
        mock_save.assert_called_once_with(schedule)

    @patch("AwayFromKeyboard.afk_midas.save_midas_schedule")
    @patch("AwayFromKeyboard.afk_midas.run_midas_auto_with_ocr_retry")
    @patch("AwayFromKeyboard.afk_midas.notify_status")
    @patch("AwayFromKeyboard.afk_midas.time.monotonic", side_effect=[200.0, 230.0])
    def test_execute_scheduled_midas_saves_run_and_cooldown_immediately(
        self,
        mock_monotonic,
        mock_notify,
        mock_run,
        mock_save,
    ):
        schedule = {"accounts": {}, "timing": {"midas_run": {"seconds": 60, "samples": 0}}}
        mock_run.return_value = MidasAutoResult(False, 3600, "01:00:00", 0.9)

        result = execute_scheduled_midas_account(
            SimpleNamespace(),
            MagicMock(),
            account="em3",
            schedule=schedule,
            notify_enabled=False,
            midas_debug_actions=False,
        )

        self.assertIs(result, mock_run.return_value)
        self.assertEqual(schedule["timing"]["midas_run"]["samples"], 1)
        self.assertEqual(schedule["timing"]["midas_run"]["seconds"], 30.0)
        self.assertIn("em3", schedule["accounts"])
        self.assertEqual(schedule["accounts"]["em3"]["cooldown_seconds"], 3600)
        self.assertEqual(schedule["accounts"]["em3"]["cooldown_source"], "ocr")
        mock_save.assert_called_once_with(schedule)

    @patch("AwayFromKeyboard.afk_midas.save_midas_schedule")
    @patch("AwayFromKeyboard.afk_midas.run_midas_auto_with_ocr_retry")
    @patch("AwayFromKeyboard.afk_midas.notify_status")
    @patch("AwayFromKeyboard.afk_midas.time.monotonic", side_effect=[200.0, 260.0])
    def test_execute_scheduled_midas_retries_recoverable_task_error_without_extra_recovery(
        self,
        mock_monotonic,
        mock_notify,
        mock_run,
        mock_save,
    ):
        from src.exceptions import TaskFailedError

        schedule = {"accounts": {}, "timing": {"midas_run": {"seconds": 60, "samples": 0}}}
        success = MidasAutoResult(False, 3600, "01:00:00", 0.9)
        mock_run.side_effect = [TaskFailedError("ADB screenshot failed"), success]

        result = execute_scheduled_midas_account(
            SimpleNamespace(),
            MagicMock(),
            account="em3",
            schedule=schedule,
            notify_enabled=False,
            midas_debug_actions=False,
        )

        self.assertIs(result, success)
        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(schedule["accounts"]["em3"]["cooldown_source"], "ocr")
        mock_save.assert_called_once_with(schedule)

    @patch("AwayFromKeyboard.afk_midas._recover_or_restart")
    @patch("AwayFromKeyboard.afk_midas.save_midas_schedule")
    @patch("AwayFromKeyboard.afk_midas.run_midas_auto_with_ocr_retry")
    @patch("AwayFromKeyboard.afk_midas.notify_status")
    @patch("AwayFromKeyboard.afk_midas.time.monotonic", side_effect=[200.0, 290.0])
    def test_execute_scheduled_midas_recovers_only_after_direct_retry_fails(
        self,
        mock_monotonic,
        mock_notify,
        mock_run,
        mock_save,
        mock_recover,
    ):
        from src.exceptions import TaskFailedError

        schedule = {"accounts": {}, "timing": {"midas_run": {"seconds": 60, "samples": 0}}}
        success = MidasAutoResult(False, 3600, "01:00:00", 0.9)
        mock_run.side_effect = [
            TaskFailedError("ADB screenshot failed"),
            TaskFailedError("ADB screenshot failed again"),
            success,
        ]
        recovery = MagicMock()

        result = execute_scheduled_midas_account(
            SimpleNamespace(),
            recovery,
            account="em3",
            schedule=schedule,
            notify_enabled=False,
            midas_debug_actions=False,
        )

        self.assertIs(result, success)
        self.assertEqual(mock_run.call_count, 3)
        mock_recover.assert_called_once_with(recovery)
        self.assertEqual(schedule["accounts"]["em3"]["cooldown_source"], "ocr")
        mock_save.assert_called_once_with(schedule)

    def test_choose_next_account_biases_current_account_when_ready_times_are_close(self):
        now = datetime(2026, 7, 13, 9, 0, tzinfo=TAIPEI_TZ)
        accounts = {"em3": {"type": "google"}, "311": {"type": "google"}}
        schedule = {
            "accounts": {
                "em3": {"ready_at": (now + timedelta(seconds=60)).isoformat()},
                "311": {"ready_at": (now + timedelta(seconds=30)).isoformat()},
            },
            "timing": {
                "switch_google_google": {"seconds": 180, "samples": 1},
                "midas_run": {"seconds": 60, "samples": 1},
            },
        }

        account, start_at, switch_seconds = choose_next_account(
            schedule,
            accounts,
            ["em3", "311"],
            "em3",
            now=now,
        )

        self.assertEqual(account, "em3")
        self.assertEqual(start_at, now + timedelta(seconds=60))
        self.assertEqual(switch_seconds, 0)

    def test_choose_next_account_uses_configured_order_for_equal_candidates(self):
        now = datetime(2026, 7, 13, 21, 21, 55, tzinfo=TAIPEI_TZ)
        accounts = {
            "em3": {"type": "google"},
            "311": {"type": "google"},
            "tiger": {"type": "email"},
            "14": {"type": "email"},
        }
        schedule = {
            "accounts": {
                "em3": {"ready_at": (now + timedelta(hours=2)).isoformat()},
            },
            "timing": {
                "switch_google_google": {"seconds": 180, "samples": 0},
                "switch_google_email": {"seconds": 180, "samples": 0},
                "midas_run": {"seconds": 19, "samples": 1},
            },
        }

        account, start_at, switch_seconds = choose_next_account(
            schedule,
            accounts,
            ["em3", "311", "tiger", "14"],
            "em3",
            now=now,
        )

        self.assertEqual(account, "311")
        self.assertEqual(start_at, now + timedelta(seconds=180))
        self.assertEqual(switch_seconds, 180)

    def test_format_schedule_decision_aligns_accounts_without_source(self):
        now = datetime(2026, 7, 18, 8, 32, 43, tzinfo=TAIPEI_TZ)
        accounts = {
            "em3": {"type": "google"},
            "311": {"type": "google"},
            "tiger": {"type": "email"},
            "14": {"type": "email"},
        }
        schedule = {
            "accounts": {
                "em3": {
                    "ready_at": datetime(2026, 7, 18, 15, 27, 43, tzinfo=TAIPEI_TZ).isoformat(),
                    "cooldown_source": "ocr",
                },
                "311": {
                    "ready_at": datetime(2026, 7, 18, 16, 18, 22, tzinfo=TAIPEI_TZ).isoformat(),
                    "cooldown_source": "ocr",
                },
                "tiger": {
                    "ready_at": datetime(2026, 7, 18, 16, 10, 0, tzinfo=TAIPEI_TZ).isoformat(),
                    "cooldown_source": "ocr",
                },
                "14": {
                    "ready_at": datetime(2026, 7, 18, 16, 32, 6, tzinfo=TAIPEI_TZ).isoformat(),
                    "cooldown_source": "ocr",
                },
            },
            "timing": {"midas_run": {"seconds": 60, "samples": 1}},
        }

        text = format_schedule_decision(
            schedule,
            accounts,
            ["em3", "311", "tiger", "14"],
            "em3",
            now=now,
        )

        self.assertIn("- em3   : ready = 2026-07-18 15:27:43 (06:55:00)", text)
        self.assertIn("- 311   : ready = 2026-07-18 16:18:22 (07:45:39)", text)
        self.assertIn("- tiger : ready = 2026-07-18 16:10:00 (07:37:17)", text)
        self.assertIn("- 14    : ready = 2026-07-18 16:32:06 (07:59:23)", text)
        self.assertNotIn("source=", text)

    def test_calculate_midas_wake_at_includes_prepare_buffer(self):
        now = datetime(2026, 7, 13, 9, 0, tzinfo=TAIPEI_TZ)
        start_at = now + timedelta(minutes=10)

        wake_at = calculate_midas_wake_at(now, start_at, 180)

        self.assertEqual(wake_at, now + timedelta(minutes=2))

    @patch("AwayFromKeyboard.afk_midas.notify_status")
    @patch("AwayFromKeyboard.afk_midas.run_midas_auto_once")
    def test_ocr_retry_alerts_after_second_failure(self, mock_run, mock_notify):
        first = MidasAutoResult(False, None, "", 0.0)
        second = MidasAutoResult(False, None, "??", 0.1)
        mock_run.side_effect = [first, second]

        result = run_midas_auto_with_ocr_retry(
            object(),
            object(),
            account="em3",
            notify_enabled=True,
        )

        self.assertIs(result, second)
        self.assertEqual(mock_run.call_count, 2)
        self.assertIn("OCR failed twice", mock_notify.call_args_list[-1].args[1])

    @patch("AwayFromKeyboard.afk_midas.notify_status")
    @patch("AwayFromKeyboard.afk_midas.run_midas_auto_once")
    def test_ocr_retry_returns_second_success(self, mock_run, mock_notify):
        failed = MidasAutoResult(False, None, "", 0.0)
        success = MidasAutoResult(True, 7200, "02:00:00", 0.9)
        mock_run.side_effect = [failed, success]

        result = run_midas_auto_with_ocr_retry(
            object(),
            object(),
            account="em3",
            notify_enabled=True,
        )

        self.assertIs(result, success)
        self.assertEqual(mock_run.call_count, 2)

    @patch("AwayFromKeyboard.afk_midas.smart_sleep", side_effect=KeyboardInterrupt)
    @patch("AwayFromKeyboard.afk_midas.execute_scheduled_midas_account")
    @patch("AwayFromKeyboard.afk_midas.choose_next_account")
    @patch("AwayFromKeyboard.afk_midas.detect_current_account", return_value="em3")
    @patch("AwayFromKeyboard.afk_midas._recover_or_restart")
    @patch("AwayFromKeyboard.afk_midas.load_midas_schedule")
    @patch("AwayFromKeyboard.afk_midas.load_accounts", return_value={"em3": {}, "311": {}})
    def test_auto_loop_sleeps_until_next_scheduled_account(
        self,
        mock_load,
        mock_schedule,
        mock_recover,
        mock_detect,
        mock_choose,
        mock_execute,
        mock_sleep,
    ):
        future = datetime.now(TAIPEI_TZ) + timedelta(seconds=600)
        mock_schedule.return_value = {"accounts": {}, "timing": {}}
        mock_choose.return_value = ("311", future, 180)
        context = SimpleNamespace(controller=object(), matcher=object())
        recovery = MagicMock()

        with self.assertRaises(KeyboardInterrupt):
            run_auto_loop(context, recovery, use_all=False)

        self.mock_write_activity_state.assert_called_once_with(
            "midas_auto",
            active=True,
            source="midas.auto.smart_round.start",
        )
        clear_call = self.mock_clear_activity_state.call_args
        self.assertEqual(clear_call.args, ("midas_auto",))
        self.assertEqual(clear_call.kwargs["source"], "midas.auto.smart_sleep")
        self.assertIn("wake_at", clear_call.kwargs["extra"])
        mock_sleep.assert_called_once()
        mock_execute.assert_not_called()

    @patch("AwayFromKeyboard.afk_midas.smart_sleep", side_effect=KeyboardInterrupt)
    @patch("AwayFromKeyboard.afk_midas.execute_scheduled_midas_account")
    @patch("AwayFromKeyboard.afk_midas.switch_to_account_if_needed", return_value="em3")
    @patch("AwayFromKeyboard.afk_midas.choose_next_account")
    @patch("AwayFromKeyboard.afk_midas.detect_current_account", return_value="em3")
    @patch("AwayFromKeyboard.afk_midas._recover_or_restart")
    @patch("AwayFromKeyboard.afk_midas.load_midas_schedule")
    @patch("AwayFromKeyboard.afk_midas.load_accounts", return_value={"em3": {}, "311": {}})
    def test_auto_loop_waits_after_early_prepare_before_running_midas(
        self,
        mock_load,
        mock_schedule,
        mock_recover,
        mock_detect,
        mock_choose,
        mock_switch,
        mock_execute,
        mock_sleep,
    ):
        start_at = datetime.now(TAIPEI_TZ) + timedelta(seconds=100)
        mock_schedule.return_value = {"accounts": {}, "timing": {}}
        mock_choose.return_value = ("em3", start_at, 0)
        context = SimpleNamespace(controller=object(), matcher=object())
        recovery = MagicMock()

        with self.assertRaises(KeyboardInterrupt):
            run_auto_loop(context, recovery, use_all=False)

        self.mock_write_activity_state.assert_any_call(
            "midas_auto",
            active=True,
            source="midas.auto.pre_ready_sleep",
        )
        mock_sleep.assert_called_once()
        mock_execute.assert_not_called()

    @patch("AwayFromKeyboard.afk_midas.smart_sleep", side_effect=KeyboardInterrupt)
    @patch("AwayFromKeyboard.afk_midas.save_midas_schedule")
    @patch("AwayFromKeyboard.afk_midas.choose_next_account")
    @patch("AwayFromKeyboard.afk_midas.detect_current_account", return_value="em3")
    @patch("AwayFromKeyboard.afk_midas.sweep_all_accounts_for_schedule", return_value="em3")
    @patch("AwayFromKeyboard.afk_midas._recover_or_restart")
    @patch("AwayFromKeyboard.afk_midas.load_midas_schedule")
    @patch("AwayFromKeyboard.afk_midas.load_accounts", return_value={"em3": {}, "311": {}})
    def test_auto_loop_can_use_sweep_first_to_probe_all_accounts(
        self,
        mock_load,
        mock_schedule,
        mock_recover,
        mock_sweep,
        mock_detect,
        mock_choose,
        mock_save,
        mock_sleep,
    ):
        future = datetime.now(TAIPEI_TZ) + timedelta(seconds=600)
        mock_schedule.return_value = {"accounts": {}, "timing": {}}
        mock_choose.return_value = ("311", future, 180)
        context = SimpleNamespace(controller=object(), matcher=object())
        recovery = MagicMock()

        with self.assertRaises(KeyboardInterrupt):
            run_auto_loop(context, recovery, use_all=False, sweep_first=True)

        self.mock_write_activity_state.assert_any_call(
            "midas_auto",
            active=True,
            source="midas.auto.sweep_all.start",
        )
        clear_call = self.mock_clear_activity_state.call_args
        self.assertEqual(clear_call.args, ("midas_auto",))
        self.assertEqual(clear_call.kwargs["source"], "midas.auto.smart_sleep")
        self.assertIn("wake_at", clear_call.kwargs["extra"])
        mock_sweep.assert_called_once()
        mock_save.assert_called_once_with(mock_schedule.return_value)
        mock_sleep.assert_called_once()

    @patch("AwayFromKeyboard.afk_midas.sys.argv", ["afk_midas.py"])
    @patch("AwayFromKeyboard.afk_midas.build_context")
    @patch("AwayFromKeyboard.afk_midas.UIRecovery")
    @patch("AwayFromKeyboard.afk_midas.run_auto_loop", side_effect=KeyboardInterrupt)
    def test_main_clears_midas_activity_on_ctrl_c(self, mock_loop, mock_recovery, mock_build_context):
        context = SimpleNamespace(controller=MagicMock(), matcher=object(), detector=object())
        context.controller.connect.return_value = True
        mock_build_context.return_value = context

        with self.assertRaises(SystemExit) as raised:
            main()

        self.assertEqual(raised.exception.code, 0)
        self.mock_clear_activity_state.assert_called_once_with(
            "midas_auto",
            source="midas.auto.ctrl_c",
        )
        mock_loop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
