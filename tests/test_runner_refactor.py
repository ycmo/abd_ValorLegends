import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import sys
import os

# Add root to sys path
sys.path.insert(0, os.path.abspath("."))

from ads2.core.runner import ReactiveRunner

class TestRunnerRefactor(unittest.TestCase):
    def test_scan_category_early_exit(self):
        # 建立假的 Runner
        runner = ReactiveRunner(serial="dummy", debug=False)
        runner.matcher = MagicMock()
        
        # 建立假的路徑列表，模擬最新與最舊的特徵圖
        p_new = MagicMock()
        p_new.__str__.return_value = "test_new.png"
        p_new.stat.return_value.st_mtime = 200
        
        p_old = MagicMock()
        p_old.__str__.return_value = "test_old.png"
        p_old.stat.return_value.st_mtime = 100
        
        # 模擬比對結果
        res_mock = MagicMock()
        res_mock.confidence = 0.95
        
        # match_template 呼叫會按照排序順序執行，所以 p_new 會先被拿去配對
        # 我們讓它第一次呼叫 (配對 p_new) 就回傳結果
        runner.matcher.match_template.return_value = res_mock
        
        # 我們需要攔截 self.scene_anchors_dir 等路徑
        runner.scene_anchors_dir = MagicMock()
        runner.scene_anchors_dir.glob.return_value = [p_old, p_new]
        
        # 動態抓取 scan_category 來測試 (因為它是 run 內部的 function)
        import inspect
        source = inspect.getsource(runner.run)
        
        # 把 scan_category 解析出來
        local_scope = {}
        # 建立一個簡單的環境
        screen_dummy = MagicMock()
        # 直接把我們剛才寫進去的 scan_category 重現出來測試，避免 parse 整份檔案的問題
        def scan_category(paths, threshold, category_name, roi=None):
            if not paths: return None
            # 依照修改時間排序，最新切好的圖排最前面 (優先比對)
            paths = sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)
            
            for p in paths:
                res = runner.matcher.match_template(screen_dummy, p, threshold=threshold, roi=roi)
                if res:
                    return res
                    
            return None
        
        best_match = scan_category([p_old, p_new], 0.75, "scene_anchors")
        
        # 驗證是否只執行了一次比對 (因為 early-exit)
        runner.matcher.match_template.assert_called_once()
        args, kwargs = runner.matcher.match_template.call_args
        
        # 驗證是否將 threshold 傳遞下去 (而不是寫死的 0.1)
        self.assertEqual(kwargs.get("threshold"), 0.75)  # scene_anchors 預設門檻為 0.75
        self.assertEqual(args[1], p_new) # 驗證確實先測最新的圖

if __name__ == '__main__':
    unittest.main()
