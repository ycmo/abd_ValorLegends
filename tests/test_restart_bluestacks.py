import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import restart_bluestacks


class RestartBlueStacksTests(unittest.TestCase):
    def test_selects_hd_player_command_line(self):
        command = restart_bluestacks._select_hd_player_command_line(
            [
                "CommandLine",
                "",
                r'"C:\Program Files\BlueStacks_nxt\HD-Player.exe" --instance Nougat64',
            ]
        )

        self.assertEqual(command, r'"C:\Program Files\BlueStacks_nxt\HD-Player.exe" --instance Nougat64')

    @patch("restart_bluestacks.close_bluestacks", return_value=True)
    @patch("restart_bluestacks.load_cached_command_line", return_value=None)
    @patch("restart_bluestacks.find_bluestacks_command_line", return_value=None)
    def test_close_only_does_not_require_cached_command(self, _find_cmd, _load_cached, close_mock):
        result = restart_bluestacks.restart_bluestacks(close_only=True)

        self.assertEqual(result, 0)
        close_mock.assert_called_once()

    @patch("restart_bluestacks.reset_adb")
    @patch("restart_bluestacks.time.sleep")
    @patch("restart_bluestacks.start_bluestacks")
    @patch("restart_bluestacks.close_bluestacks", return_value=True)
    @patch("restart_bluestacks.load_cached_command_line", return_value="cached command")
    @patch("restart_bluestacks.find_bluestacks_command_line", return_value=None)
    def test_restart_uses_cached_command_when_bluestacks_is_not_running(
        self,
        _find_cmd,
        _load_cached,
        _close,
        start_mock,
        _sleep,
        _reset,
    ):
        result = restart_bluestacks.restart_bluestacks(boot_wait_seconds=0)

        self.assertEqual(result, 0)
        start_mock.assert_called_once_with("cached command")

    @patch("restart_bluestacks.reset_adb")
    @patch("restart_bluestacks.time.sleep")
    @patch("restart_bluestacks.start_bluestacks")
    @patch("restart_bluestacks.close_bluestacks", return_value=True)
    @patch("restart_bluestacks.save_cached_command_line")
    @patch("restart_bluestacks.get_default_command_line", return_value=restart_bluestacks.DEFAULT_COMMAND_LINE)
    @patch("restart_bluestacks.load_cached_command_line", return_value=None)
    @patch("restart_bluestacks.find_bluestacks_command_line", return_value=None)
    def test_restart_uses_default_pie64_command_when_no_cache_exists(
        self,
        _find_cmd,
        _load_cached,
        _default_cmd,
        save_mock,
        _close,
        start_mock,
        _sleep,
        _reset,
    ):
        result = restart_bluestacks.restart_bluestacks(boot_wait_seconds=0)

        self.assertEqual(result, 0)
        save_mock.assert_called_once_with(restart_bluestacks.DEFAULT_COMMAND_LINE)
        start_mock.assert_called_once_with(restart_bluestacks.DEFAULT_COMMAND_LINE)

    @patch("restart_bluestacks.subprocess.run")
    @patch("restart_bluestacks.wait_for_bluestacks_exit", return_value=True)
    def test_close_bluestacks_kills_process_tree_and_adb(self, _wait, run_mock):
        self.assertTrue(restart_bluestacks.close_bluestacks())

        calls = [call.args[0] for call in run_mock.call_args_list]
        self.assertIn(["taskkill", "/F", "/T", "/IM", "HD-Player.exe"], calls)
        self.assertIn(["adb", "kill-server"], calls)

    def test_cache_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.txt"
            with patch.object(restart_bluestacks, "CACHE_FILE", cache):
                restart_bluestacks.save_cached_command_line("hello")
                self.assertEqual(restart_bluestacks.load_cached_command_line(), "hello")

    def test_default_boot_wait_is_two_minutes(self):
        args = restart_bluestacks.build_parser().parse_args([])

        self.assertEqual(args.boot_wait, 120.0)

    @patch("restart_bluestacks.subprocess.run")
    def test_reset_adb_runs_commands_directly_without_pause_bat(self, run_mock):
        restart_bluestacks.reset_adb()

        commands = [call.args[0] for call in run_mock.call_args_list]
        self.assertEqual(
            commands,
            [
                ["adb", "kill-server"],
                ["adb", "start-server"],
                ["adb", "connect", "127.0.0.1:5555"],
                ["adb", "devices"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
