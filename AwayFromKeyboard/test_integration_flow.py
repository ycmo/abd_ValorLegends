import sys
import time
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import numpy as np
import cv2

# 強制設定輸出為 UTF-8，以防在 Windows 終端機顯示中文出錯
sys.stdout.reconfigure(encoding='utf-8')

# Ensure the module can be imported
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import the module under test
from AwayFromKeyboard.integration_flow import run_integration_flow

class TestIntegrationFlow(unittest.TestCase):
    @patch("subprocess.run")
    @patch("AwayFromKeyboard.integration_flow.run_yijie_task")
    @patch("AwayFromKeyboard.integration_flow.DeviceController")
    def test_run_integration_flow_structure(self, mock_device, mock_yijie, mock_subproc):
        """確保主流程隔離呼叫了 subprocess 且包含所有指定任務"""
        
        run_integration_flow()
        
        # 確認呼叫了 DeviceController
        mock_device.assert_called_once()
        
        # 確認 run_yijie_task 有被呼叫
        mock_yijie.assert_called_once()
        
        # 確認 subprocess.run 有被呼叫三次 (每日任務, 點金手, 疾風呼喚)
        self.assertEqual(mock_subproc.call_count, 3)


if __name__ == "__main__":
    unittest.main()
