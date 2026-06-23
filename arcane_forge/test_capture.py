import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from arcane_forge.capture import capture_and_crop, get_unique_screenshot_path


class TestCapture(unittest.TestCase):
    def test_get_unique_screenshot_path_no_conflict(self):
        with patch('pathlib.Path.exists', return_value=False):
            output_dir = Path("dummy")
            path = get_unique_screenshot_path(output_dir, "test")
            self.assertEqual(path, Path("dummy/test.png"))

    def test_get_unique_screenshot_path_with_conflict(self):
        with patch('pathlib.Path.exists') as mock_exists:
            # First call is for test.png (exists), second for test_2.png (exists), third for test_3.png (does not exist)
            mock_exists.side_effect = [True, True, False]
            output_dir = Path("dummy")
            path = get_unique_screenshot_path(output_dir, "test")
            self.assertEqual(path, Path("dummy/test_3.png"))

    @patch('arcane_forge.capture.DeviceController')
    @patch('arcane_forge.capture.run_paint_crop_workflow')
    def test_capture_and_crop(self, mock_workflow, mock_ctrl_class):
        mock_ctrl = MagicMock()
        mock_ctrl_class.return_value = mock_ctrl
        mock_workflow.return_value = [Path("dummy_dir/crop1.png")]

        with patch('pathlib.Path.mkdir') as mock_mkdir, \
             patch('pathlib.Path.exists', return_value=False):

            output_dir = Path("dummy_dir")
            capture_and_crop("test_file", output_dir)

            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
            mock_ctrl.connect.assert_called_once()
            mock_ctrl.save_screenshot.assert_called_once_with(Path("dummy_dir/test_file.png"))
            mock_workflow.assert_called_once_with(Path("dummy_dir/test_file.png"))

if __name__ == '__main__':
    unittest.main()
