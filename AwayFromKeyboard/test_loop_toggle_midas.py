import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from AwayFromKeyboard.loop_toggle_midas import (
    AUTO_OCR_FAILURE_SLEEP_SECONDS,
    AUTO_WAKE_BUFFER_SECONDS,
    build_auto_account_order,
    process_auto_account,
    run_auto_round,
)
from src.tasks.midas import MidasAutoResult


class AutoMidasLoopTests(unittest.TestCase):
    def test_two_account_order_starts_current_then_em3_without_duplicates(self):
        accounts = {"311": {}, "em3": {}, "14": {}, "tiger": {}}

        self.assertEqual(build_auto_account_order("311", accounts, False), ["311", "em3"])
        self.assertEqual(build_auto_account_order("14", accounts, False), ["14", "em3", "311"])

    def test_all_account_order_contains_each_account_once(self):
        accounts = {"311": {}, "em3": {}, "14": {}, "tiger": {}}

        order = build_auto_account_order("14", accounts, True)

        self.assertEqual(order, ["14", "em3", "311", "tiger"])
        self.assertEqual(len(order), len(set(order)))

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
        mock_sleep.assert_called_once_with(120 + AUTO_WAKE_BUFFER_SECONDS)
        self.assertEqual(mock_run.call_count, 2)
        recovery.handle_wakeup_exceptions.assert_called_once()
        mock_recover.assert_called_once_with(recovery)

    @patch("AwayFromKeyboard.loop_toggle_midas.run_midas_auto_once")
    def test_long_cooldown_moves_to_next_account(self, mock_run):
        mock_run.return_value = MidasAutoResult(False, 301, "00:05:01", 0.9)

        self.assertTrue(process_auto_account(object(), object(), "em3"))
        mock_run.assert_called_once()

    @patch("AwayFromKeyboard.loop_toggle_midas.run_midas_auto_once")
    def test_ocr_failure_requests_two_hour_sleep(self, mock_run):
        mock_run.return_value = MidasAutoResult(False, None, "O1:2B:22", 0.42)

        self.assertFalse(process_auto_account(object(), object(), "em3"))

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
        accounts = {"311": {}, "em3": {}, "14": {}, "tiger": {}}

        sleep_seconds = run_auto_round(context, recovery, accounts=accounts, use_all=False)

        self.assertEqual(sleep_seconds, 7200 + AUTO_WAKE_BUFFER_SECONDS)
        self.assertEqual([call.args[2] for call in mock_process.call_args_list], ["311", "em3"])
        self.assertEqual([call.args[0] for call in mock_switch.call_args_list], ["em3"])
        mock_run.assert_called_once_with(context, recovery, require_cooldown=True)

    @patch("AwayFromKeyboard.loop_toggle_midas.process_auto_account", return_value=False)
    @patch("AwayFromKeyboard.loop_toggle_midas.switch_account", return_value=True)
    @patch("AwayFromKeyboard.loop_toggle_midas.detect_current_account", return_value="14")
    @patch("AwayFromKeyboard.loop_toggle_midas._recover_or_restart")
    def test_round_ocr_failure_returns_em3_and_sleeps_two_hours(
        self,
        mock_recover,
        mock_detect,
        mock_switch,
        mock_process,
    ):
        context = SimpleNamespace(controller=object(), matcher=object())
        recovery = MagicMock()
        accounts = {"311": {}, "em3": {}, "14": {}, "tiger": {}}

        sleep_seconds = run_auto_round(context, recovery, accounts=accounts, use_all=True)

        self.assertEqual(sleep_seconds, AUTO_OCR_FAILURE_SLEEP_SECONDS)
        mock_switch.assert_called_once_with("em3")


if __name__ == "__main__":
    unittest.main()
