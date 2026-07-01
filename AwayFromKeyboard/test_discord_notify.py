import unittest
from unittest.mock import patch

from AwayFromKeyboard.discord_notify import format_status_msg, notify_status


class DiscordNotifyTests(unittest.TestCase):
    def test_format_status_msg(self):
        self.assertEqual(
            format_status_msg(
                "AFK",
                "開始",
                account="em3",
                route="每日任務",
                detail="debug",
            ),
            "[AFK] | em3 | 每日任務 | 開始 | debug",
        )

    @patch("AwayFromKeyboard.discord_notify.send_discord_msg")
    def test_notify_status_can_be_disabled(self, mock_send):
        notify_status("AFK", "開始", enabled=False)

        mock_send.assert_not_called()

    @patch("AwayFromKeyboard.discord_notify.send_discord_msg")
    def test_notify_status_sends_formatted_message(self, mock_send):
        notify_status("Midas", "完成", account="311", route="點金手")

        mock_send.assert_called_once_with("[Midas] | 311 | 點金手 | 完成")


if __name__ == "__main__":
    unittest.main()
