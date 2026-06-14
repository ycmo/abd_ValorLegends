import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import switch_account

class DummyMatchResult:
    def __init__(self, name, confidence, center):
        self.template_path = Path(name)
        self.confidence = confidence
        self.center = center

class TestSwitchAccount(unittest.TestCase):
    @patch("switch_account.DeviceController")
    @patch("switch_account.VisionMatcher")
    @patch("switch_account.time.sleep")
    @patch("switch_account.wait_and_tap")
    @patch("switch_account.wait_for_appearance")
    @patch("switch_account.select_server")
    @patch("builtins.print")
    def test_email_branch(self, mock_print, mock_select_server, mock_wait_for_appearance, mock_wait_and_tap, mock_sleep, MockVisionMatcher, MockDeviceController):
        switch_account.ACCOUNTS = {
            "email_acc": {"type": "email", "email": "a@b.com", "password": "123"}
        }
        
        mock_controller = MagicMock()
        MockDeviceController.return_value = mock_controller
        MockDeviceController.list_devices.return_value = ["emulator-5554"]
        
        mock_matcher = MagicMock()
        MockVisionMatcher.return_value = mock_matcher
        
        # Make match_template return None for current account check and loop break
        mock_matcher.match_template.return_value = None
        
        try:
            switch_account.switch_account("email_acc")
        except RuntimeError:
            pass # Catch the timeout exception from the 10 loops
            
        mock_print.assert_any_call("步驟 2/4: 選擇信箱登入 (email_acc)")
        
    @patch("switch_account.DeviceController")
    @patch("switch_account.VisionMatcher")
    @patch("switch_account.time.sleep")
    @patch("switch_account.wait_and_tap")
    @patch("switch_account.wait_for_appearance")
    @patch("switch_account.select_server")
    @patch("builtins.print")
    def test_google_branch(self, mock_print, mock_select_server, mock_wait_for_appearance, mock_wait_and_tap, mock_sleep, MockVisionMatcher, MockDeviceController):
        switch_account.ACCOUNTS = {
            "google_acc": {"type": "google", "server": "14"}
        }
        
        mock_controller = MagicMock()
        MockDeviceController.return_value = mock_controller
        MockDeviceController.list_devices.return_value = ["emulator-5554"]
        
        mock_matcher = MagicMock()
        MockVisionMatcher.return_value = mock_matcher
        mock_matcher.match_template.return_value = None
        
        try:
            switch_account.switch_account("google_acc")
        except RuntimeError:
            pass
            
        mock_print.assert_any_call("步驟 2/4: 選擇 Google 登入")
        mock_select_server.assert_called_once()
        
    @patch("switch_account.DeviceController")
    @patch("switch_account.VisionMatcher")
    @patch("switch_account.time.sleep")
    @patch("switch_account.wait_and_tap")
    @patch("switch_account.wait_for_appearance")
    @patch("switch_account.select_server")
    @patch("builtins.print")
    def test_toggle_shortcut_branch(self, mock_print, mock_select_server, mock_wait_for_appearance, mock_wait_and_tap, mock_sleep, MockVisionMatcher, MockDeviceController):
        switch_account.ACCOUNTS = {
            "311": {"type": "google", "server": "311"},
            "em3": {"type": "google", "server": "em3"}
        }
        
        mock_controller = MagicMock()
        MockDeviceController.return_value = mock_controller
        MockDeviceController.list_devices.return_value = ["emulator-5554"]
        
        mock_matcher = MagicMock()
        MockVisionMatcher.return_value = mock_matcher
        
        def mock_match_template_side_effect(screen, template_path, *args, **kwargs):
            if "000_頭像311.png" in str(template_path):
                return DummyMatchResult("000_頭像311.png", 0.9, (10, 10))
            return None
            
        mock_matcher.match_template.side_effect = mock_match_template_side_effect
        
        try:
            switch_account.switch_account("toggle")
        except RuntimeError:
            pass
            
        mock_print.assert_any_call("🔄 觸發 Toggle 模式：決定目標帳號為 'em3'")
        mock_print.assert_any_call("⚡ 觸發超級捷徑：目前為 Google 帳號，目標也是 Google 帳號，跳過完整登出流程！")
        mock_print.assert_any_call("👉 點擊左側「伺服器」分頁...")
        
    @patch("switch_account.DeviceController")
    @patch("switch_account.VisionMatcher")
    @patch("switch_account.time.sleep")
    @patch("switch_account.wait_and_tap")
    @patch("switch_account.wait_for_appearance")
    @patch("switch_account.select_server")
    @patch("builtins.print")
    def test_toggle_14_to_tiger(self, mock_print, mock_select_server, mock_wait_for_appearance, mock_wait_and_tap, mock_sleep, MockVisionMatcher, MockDeviceController):
        switch_account.ACCOUNTS = {
            "14": {"type": "email", "email": "a", "password": "b"},
            "tiger": {"type": "email", "email": "c", "password": "d"}
        }
        
        mock_controller = MagicMock()
        MockDeviceController.return_value = mock_controller
        MockDeviceController.list_devices.return_value = ["emulator-5554"]
        
        mock_matcher = MagicMock()
        MockVisionMatcher.return_value = mock_matcher
        
        def mock_match_template_side_effect(screen, template_path, *args, **kwargs):
            if "000_頭像14.png" in str(template_path):
                return DummyMatchResult("000_頭像14.png", 0.9, (10, 10))
            return None
            
        mock_matcher.match_template.side_effect = mock_match_template_side_effect
        
        try:
            switch_account.switch_account("toggle")
        except RuntimeError:
            pass
            
        mock_print.assert_any_call("🔄 觸發 Toggle 模式：決定目標帳號為 'tiger'")

    @patch("switch_account.DeviceController")
    @patch("switch_account.VisionMatcher")
    @patch("builtins.print")
    def test_toggle_unknown_abort(self, mock_print, MockVisionMatcher, MockDeviceController):
        switch_account.ACCOUNTS = {
            "311": {"type": "google", "server": "311"},
        }
        
        mock_controller = MagicMock()
        MockDeviceController.return_value = mock_controller
        MockDeviceController.list_devices.return_value = ["emulator-5554"]
        
        mock_matcher = MagicMock()
        MockVisionMatcher.return_value = mock_matcher
        mock_matcher.match_template.return_value = None
        
        result = switch_account.switch_account("toggle")
        
        self.assertFalse(result)
        mock_print.assert_any_call("錯誤：無法辨識當前帳號，無法執行 Toggle 模式！")

if __name__ == '__main__':
    unittest.main(verbosity=2)
