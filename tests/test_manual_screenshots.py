import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

import src.manual_screenshots as manual_screenshots


class ManualScreenshotPaintTests(unittest.TestCase):
    def test_no_open_paint_flag_exists(self):
        parser = manual_screenshots._build_parser()

        args = parser.parse_args(["--task", "魔法商店", "--no-open-paint"])

        self.assertTrue(args.no_open_paint)
        self.assertIsNone(args.index)

    def test_next_index_starts_at_zero_for_empty_task_dir(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(manual_screenshots._next_index(Path(tmp)), "000")

    def test_next_index_uses_largest_existing_png_prefix(self):
        with TemporaryDirectory() as tmp:
            task_dir = Path(tmp)
            (task_dir / "000_開始.png").write_bytes(b"")
            (task_dir / "003_結束.png").write_bytes(b"")
            (task_dir / "abc.png").write_bytes(b"")
            (task_dir / "002_blue_01.png").write_bytes(b"")

            self.assertEqual(manual_screenshots._next_index(task_dir), "004")

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

    def test_default_flow_auto_increments_when_index_omitted(self):
        class FakeController:
            def __init__(self, serial):
                self.serial = serial

            def connect(self):
                return True

            def screenshot(self):
                return np.zeros((540, 960, 3), dtype=np.uint8)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "公會祈願"
            task_dir.mkdir()
            (task_dir / "001_既有.png").write_bytes(b"")
            with (
                patch.object(manual_screenshots, "MANUAL_SCREENSHOTS_DIR", root),
                patch.object(manual_screenshots, "DeviceController", FakeController),
                patch("src.manual_screenshots.run_paint_crop_workflow", return_value=[]) as workflow,
            ):
                code = manual_screenshots.main(["--task", "公會祈願", "--scene", "每日任務"])

                self.assertEqual(code, 0)
                screenshot_path = root / "公會祈願" / "002_每日任務.png"
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
