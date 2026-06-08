import unittest
from pathlib import Path
from unittest.mock import patch

import src.manual_screenshots as manual_screenshots


class ManualScreenshotPaintTests(unittest.TestCase):
    def test_open_in_paint_uses_mspaint(self):
        with patch("src.manual_screenshots.subprocess.Popen") as popen:
            manual_screenshots.open_in_paint(Path("manual_screenshots/example.png"))

        self.assertEqual(popen.call_count, 1)
        self.assertEqual(popen.call_args.args[0][0], "mspaint")

    def test_no_open_paint_flag_exists(self):
        parser = manual_screenshots._build_parser()

        args = parser.parse_args(["--task", "魔法商店", "--index", "1", "--no-open-paint"])

        self.assertTrue(args.no_open_paint)
        self.assertFalse(args.open_paint)


if __name__ == "__main__":
    unittest.main()
