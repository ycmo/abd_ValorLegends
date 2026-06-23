import logging
import unittest
from unittest.mock import MagicMock, call, patch

from arcane_forge.arcane_forge_ascend import ArcaneForgeAscendTask


class TestArcaneForgeAscendTask(unittest.TestCase):
    def setUp(self):
        logging.getLogger('arcane_forge.arcane_forge_ascend').setLevel(logging.CRITICAL)

        self.mock_ctrl = MagicMock()
        self.mock_ctrl.screenshot.return_value = "dummy_screen"
        self.mock_vm = MagicMock()

        patcher_reader = patch('arcane_forge.arcane_forge_ascend.get_cached_easyocr_reader')
        self.mock_get_reader = patcher_reader.start()
        self.addCleanup(patcher_reader.stop)

        self.task = ArcaneForgeAscendTask(self.mock_ctrl, self.mock_vm)

        self.fake_ascend_res = MagicMock(x=10, y=10)
        self.fake_auto_add_res = MagicMock(x=20, y=20)
        self.fake_success_res = MagicMock(x=30, y=30)
        self.fake_lock_res = MagicMock(x=40, y=40)
        self.fake_back_res = MagicMock(x=50, y=50)

        patcher_exists = patch('pathlib.Path.exists', return_value=True)
        self.mock_exists = patcher_exists.start()
        self.addCleanup(patcher_exists.stop)

    @patch('arcane_forge.arcane_forge_ascend.time.sleep')
    @patch('arcane_forge.arcane_forge_ascend.read_texts_easyocr')
    @patch('arcane_forge.arcane_forge_ascend.cv2.matchTemplate')
    @patch('arcane_forge.arcane_forge_ascend.read_image')
    def test_run_success_loop_and_exit(self, mock_read_image, mock_matchTemplate, mock_ocr, mock_sleep):
        import numpy as np
        # 模擬 OCR 返回足夠的紫粉
        mock_ocr.return_value = [{'text': '200', 'confidence': 0.9}]

        # 模擬 matchTemplate 找到 2 個「最大」
        mock_read_image.return_value = MagicMock(ndim=2) # dummy image

        # 構造一個夠大的 fake result，使得兩個點距離超過 100 像素以通過 NMS
        fake_res = np.zeros((200, 200))
        fake_res[0, 0] = 1.0
        fake_res[150, 150] = 1.0
        mock_matchTemplate.return_value = fake_res

        def mock_match_template(screen, tpl_path):
            name = tpl_path.name
            if name == "升星.png":
                if self.mock_vm.match_template.call_count <= 6:
                    return self.fake_ascend_res
                return None
            elif name == "自動添加.png":
                return self.fake_auto_add_res
            elif name == "升星成功.png":
                return self.fake_success_res
            elif name == "鎖定.png":
                return self.fake_lock_res
            elif name == "返回.png":
                return self.fake_back_res
            return None

        self.mock_vm.match_template.side_effect = mock_match_template

        result = self.task.run()

        self.assertTrue(result)

        # 驗證 tap 順序
        self.mock_ctrl.tap.assert_has_calls([
            call(572, 148), # click first slot
            call(10, 10),   # click ascend
            call(20, 20),   # auto add
            call(10, 10),   # confirm ascend
            call(480, 50),  # close success popup
            call(40, 40),   # lock (because 2 max stats)
            call(50, 50),   # back
            call(572, 148)  # click first slot (2nd round)
        ])

    @patch('arcane_forge.arcane_forge_ascend.time.sleep')
    @patch('arcane_forge.arcane_forge_ascend.read_texts_easyocr')
    def test_run_breaks_on_low_dust(self, mock_ocr, mock_sleep):
        # 模擬 OCR 返回紫粉不足
        mock_ocr.return_value = [{'text': '150', 'confidence': 0.9}]

        self.mock_vm.match_template.return_value = self.fake_ascend_res

        result = self.task.run()

        self.assertTrue(result)

        # 驗證 tap 順序: 只點擊第一格與升星，然後因為紫粉不足結束
        self.mock_ctrl.tap.assert_has_calls([
            call(572, 148),
            call(10, 10),
        ])
        self.assertEqual(self.mock_ctrl.tap.call_count, 2)

    @patch('arcane_forge.arcane_forge_ascend.time.sleep')
    @patch('arcane_forge.arcane_forge_ascend.read_texts_easyocr')
    @patch('arcane_forge.arcane_forge_ascend.cv2.matchTemplate')
    @patch('arcane_forge.arcane_forge_ascend.read_image')
    def test_run_continues_on_parse_failure(self, mock_read_image, mock_matchTemplate, mock_ocr, mock_sleep):
        import numpy as np
        # 模擬 OCR 返回無法解析的文字
        mock_ocr.return_value = [{'text': 'abc', 'confidence': 0.9}]

        # 模擬 matchTemplate 找到 0 個「最大」
        mock_read_image.return_value = MagicMock(ndim=2)
        mock_matchTemplate.return_value = np.zeros((200, 200))

        def mock_match_template(screen, tpl_path):
            name = tpl_path.name
            if name == "升星.png":
                if self.mock_vm.match_template.call_count <= 6:
                    return self.fake_ascend_res
                return None
            elif name == "自動添加.png":
                return self.fake_auto_add_res
            elif name == "升星成功.png":
                return self.fake_success_res
            elif name == "鎖定.png":
                return self.fake_lock_res
            elif name == "返回.png":
                return self.fake_back_res
            return None

        self.mock_vm.match_template.side_effect = mock_match_template

        result = self.task.run()

        self.assertTrue(result)

        # 驗證 tap 順序: 解析失敗仍會繼續升星，直到第二輪找不到升星.png
        self.mock_ctrl.tap.assert_has_calls([
            call(572, 148),
            call(10, 10),
            call(20, 20),
            call(10, 10),
            call(480, 50),
            call(50, 50), # 無最大屬性所以沒上鎖，直接返回
            call(572, 148),
        ])

if __name__ == '__main__':
    unittest.main()
