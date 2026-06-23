import logging
import unittest
from unittest.mock import MagicMock, call

from arcane_forge.arcane_forge_task import ArcaneForgeTask


class TestArcaneForgeTask(unittest.TestCase):
    def setUp(self):
        # 停用 log 輸出干擾測試
        logging.getLogger('arcane_forge.arcane_forge_task').setLevel(logging.CRITICAL)

        self.mock_ctrl = MagicMock()
        self.mock_ctrl.screenshot.return_value = "dummy_screen"

        self.mock_vm = MagicMock()

        self.task = ArcaneForgeTask(self.mock_ctrl, self.mock_vm)

        # 建立假的 MatchResult
        self.fake_title_res = MagicMock(x=10, y=10)
        self.fake_quick_put_res = MagicMock(x=20, y=20)
        self.fake_deconstruct_res = MagicMock(x=30, y=30)
        self.fake_popup_res = MagicMock(x=40, y=40)
        self.fake_back_res = MagicMock(x=50, y=50)

        patcher = unittest.mock.patch('pathlib.Path.exists', return_value=True)
        self.addCleanup(patcher.stop)
        self.mock_exists = patcher.start()

    @unittest.mock.patch('arcane_forge.arcane_forge_task.time.sleep')
    def test_run_success_loop_and_exit(self, mock_sleep):
        # 模擬：
        # 第1輪: 找到標題 -> 找到一鍵放入 -> 找到分解 -> 找到彈窗
        # 第2輪: 找到一鍵放入 -> 找不到分解 (無英雄) -> 迴圈結束 -> 找到返回鍵

        def mock_match_template(screen, tpl_path):
            name = tpl_path.name
            if name == "arcane_forge_title.png":
                return self.fake_title_res
            elif name == "quick_put_btn.png":
                return self.fake_quick_put_res
            elif name == "deconstruct_btn.png":
                # 第一輪找得到，第二輪找不到
                if self.mock_vm.match_template.call_count <= 4:
                    return self.fake_deconstruct_res
                return None
            elif name == "obtain_items_popup.png":
                return self.fake_popup_res
            elif name == "back_btn.png":
                return self.fake_back_res
            return None

        self.mock_vm.match_template.side_effect = mock_match_template

        result = self.task.run()

        self.assertTrue(result)

        # 驗證 tap 有正確呼叫
        self.mock_ctrl.tap.assert_has_calls([
            call(20, 20), # quick put
            call(30, 30), # deconstruct
            call(480, 50), # close popup
            call(20, 20), # quick put (2nd round)
            call(50, 50), # back button
        ])

    def test_run_fails_at_title(self):
        # 模擬：找不到標題防呆
        self.mock_vm.match_template.return_value = None

        result = self.task.run()

        self.assertFalse(result)
        self.mock_ctrl.tap.assert_not_called()

    @unittest.mock.patch('arcane_forge.arcane_forge_task.time.sleep')
    def test_run_breaks_at_popup_missing(self, mock_sleep):
        # 模擬：找到標題 -> 找到一鍵放入 -> 找到分解 -> 找不到彈窗 -> 返回
        def mock_match_template(screen, tpl_path):
            name = tpl_path.name
            if name == "arcane_forge_title.png":
                return self.fake_title_res
            if name == "quick_put_btn.png":
                return self.fake_quick_put_res
            if name == "deconstruct_btn.png":
                return self.fake_deconstruct_res
            if name == "obtain_items_popup.png":
                return None
            if name == "back_btn.png":
                return None # 測試找不到返回時不會用 ctrl.back()
            return None

        self.mock_vm.match_template.side_effect = mock_match_template

        result = self.task.run()

        self.assertTrue(result)
        # tap quick put, deconstruct. No tap for popup. Then back is missing, so no back called.
        self.mock_ctrl.tap.assert_has_calls([
            call(20, 20),
            call(30, 30),
        ])
        self.mock_ctrl.back.assert_not_called()

if __name__ == '__main__':
    unittest.main()
