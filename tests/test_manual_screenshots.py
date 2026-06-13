import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

import src.manual_screenshots as manual_screenshots


class ManualScreenshotPaintTests(unittest.TestCase):
    def test_no_open_paint_flag_exists(self):
        parser = manual_screenshots._build_parser()

        args = parser.parse_args(["--task", "魔法商店", "--index", "1", "--no-open-paint"])

        self.assertTrue(args.no_open_paint)

    def test_default_flow_runs_paint_cropper_next_to_manual_screenshot(self):
        class FakeController:
            def __init__(self, serial):
                self.serial = serial

            def connect(self):
                return True

            def screenshot(self):
                return np.zeros((540, 960, 3), dtype=np.uint8)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(manual_screenshots, "MANUAL_SCREENSHOTS_DIR", root),
                patch.object(manual_screenshots, "DeviceController", FakeController),
                patch("src.manual_screenshots.run_paint_crop_workflow", return_value=[]) as workflow,
            ):
                code = manual_screenshots.main(["--task", "公會祈願", "--index", "7", "--scene", "每日任務"])

                self.assertEqual(code, 0)
                screenshot_path = root / "公會祈願" / "007_每日任務.png"
                self.assertTrue(screenshot_path.exists())
                workflow.assert_called_once_with(screenshot_path)

    def test_no_open_paint_saves_only_full_screenshot(self):
        class FakeController:
            def __init__(self, serial):
                self.serial = serial

            def connect(self):
                return True

            def screenshot(self):
                return np.zeros((540, 960, 3), dtype=np.uint8)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(manual_screenshots, "MANUAL_SCREENSHOTS_DIR", root),
                patch.object(manual_screenshots, "DeviceController", FakeController),
                patch("src.manual_screenshots.run_paint_crop_workflow", return_value=[]) as workflow,
            ):
                code = manual_screenshots.main(
                    ["--task", "公會祈願", "--index", "7", "--scene", "每日任務", "--no-open-paint"]
                )

                self.assertEqual(code, 0)
                self.assertTrue((root / "公會祈願" / "007_每日任務.png").exists())
                workflow.assert_not_called()


if __name__ == "__main__":
    unittest.main()
