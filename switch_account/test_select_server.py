import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import sys

# 確保能引用到 switch_account.py
sys.path.insert(0, str(Path(__file__).resolve().parent))
import switch_account

class DummyMatchResult:
    def __init__(self, name, confidence, center):
        self.template_path = Path(name)
        self.confidence = confidence
        self.center = center

class TestSelectServer(unittest.TestCase):
    @patch("switch_account.wait_and_tap")
    @patch("switch_account.TEMPLATES_DIR")
    @patch("time.sleep")
    def test_select_server_no_popup(self, mock_sleep, mock_templates_dir, mock_wait_and_tap):
        mock_templates_dir.glob.return_value = [Path("008_伺服器_311.png")]
        mock_controller = MagicMock()
        mock_matcher = MagicMock()
        
        res_311 = DummyMatchResult("008_伺服器_311.png", 0.9, (400, 100))
        mock_matcher.match_any.return_value = res_311
        mock_matcher.match_template.return_value = None
        
        switch_account.select_server(mock_controller, mock_matcher, "311")
        
        mock_controller.swipe.assert_not_called()
        mock_controller.tap.assert_called_once_with(400, 100)

    @patch("switch_account.wait_and_tap")
    @patch("switch_account.TEMPLATES_DIR")
    @patch("time.sleep")
    def test_select_server_with_popup(self, mock_sleep, mock_templates_dir, mock_wait_and_tap):
        mock_templates_dir.glob.return_value = [Path("008_伺服器_311.png")]
        mock_controller = MagicMock()
        mock_matcher = MagicMock()
        
        res_311 = DummyMatchResult("008_伺服器_311.png", 0.9, (400, 100))
        mock_matcher.match_any.return_value = res_311
        
        res_popup = DummyMatchResult("008_1_確認切換是_0.png", 0.8, (500, 300))
        mock_matcher.match_template.return_value = res_popup
        
        switch_account.select_server(mock_controller, mock_matcher, "311")
        
        self.assertEqual(mock_controller.tap.call_count, 2)
        mock_controller.tap.assert_any_call(400, 100)
        mock_controller.tap.assert_any_call(500, 300)

if __name__ == '__main__':
    unittest.main(verbosity=2)
