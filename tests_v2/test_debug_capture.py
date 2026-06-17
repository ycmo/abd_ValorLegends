"""
test_debug_capture.py — DebugCapture 的 unittest

測試範圍：
  - save_failure()：正確建立目錄、儲存標註截圖、回傳 Path
  - save_action()：before/after 檔案正確命名
  - cleanup()：保留最新 N 個 session，刪除其餘
  - session 目錄命名格式驗證

Mock 策略：
  - 使用 tmp_path（pytest fixture）或 tempfile.TemporaryDirectory
  - annotate_image → 回傳 dummy array，不需真實 OpenCV 繪製
  - 不需要真實截圖內容

不測試：
  - cv2.imwrite 的實際圖片品質
  - Windows junction 建立（平台相依，標記為 skip）
"""
import unittest
from unittest.mock import MagicMock, patch
import tempfile
from pathlib import Path

# TODO: 實作測試案例（待 src_v2/debug_capture.py 完成後）
