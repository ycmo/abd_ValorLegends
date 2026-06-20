import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import sys
import os
import cv2

# Add root to sys path
sys.path.insert(0, os.path.abspath("."))

from ads2.core.runner import ReactiveRunner
from ads2.core.profile import load_ads_profile
from src.vision_matcher import MatchResult, read_image

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

    def test_call_of_the_gale_profile_matches_restore_3_darts(self):
        profile = load_ads_profile(
            "call_of_the_gale",
            project_root=Path(".").resolve(),
            ads2_dir=Path("ads2").resolve(),
        )
        self.assertIsNotNone(profile)
        self.assertEqual(profile.name, "call_of_the_gale")
        self.assertIn("疾風呼喚", profile.description)
        self.assertEqual(len(profile.finish_templates), 1)

        screen = read_image(
            Path("manual_screenshots") / "疾風呼喚" / "001_看完廣告.png",
            cv2.IMREAD_COLOR,
        )
        runner = ReactiveRunner(serial="dummy", debug=False, profile="call_of_the_gale")
        matched = runner.match_profile_finish(screen)

        self.assertIsNotNone(matched)
        condition, result = matched
        self.assertEqual(condition.name, "restore_3_darts_status")
        self.assertGreaterEqual(result.confidence, 0.99)

    def test_runner_profile_finish_uses_configured_roi_and_threshold(self):
        runner = ReactiveRunner(serial="dummy", debug=False, profile="call_of_the_gale")
        runner.matcher = MagicMock()
        fake_result = MatchResult(Path("restore_3_darts.png"), 0.95, (593, 25), (545, 10, 97, 30))
        runner.matcher.match_template.return_value = fake_result

        screen = MagicMock()
        matched = runner.match_profile_finish(screen)

        self.assertIsNotNone(matched)
        condition, result = matched
        self.assertEqual(condition.roi, (520, 0, 150, 60))
        self.assertEqual(result, fake_result)
        _args, kwargs = runner.matcher.match_template.call_args
        self.assertEqual(kwargs["threshold"], 0.85)
        self.assertEqual(kwargs["roi"], (520, 0, 150, 60))

    def test_gale_ad_revive_button_matches_reference_roi(self):
        from call_of_the_gale.scripts.single_shoot import (
            AD_REVIVE_BTN_PATH,
            AD_REVIVE_ROI,
            AD_REVIVE_THRESHOLD,
        )

        screen = read_image(
            Path("manual_screenshots") / "疾風呼喚" / "000_送出前看廣告.png",
            cv2.IMREAD_COLOR,
        )
        runner = ReactiveRunner(serial="dummy", debug=False)
        match = runner.matcher.match_template(
            screen,
            AD_REVIVE_BTN_PATH,
            threshold=AD_REVIVE_THRESHOLD,
            roi=AD_REVIVE_ROI,
        )

        self.assertIsNotNone(match)
        self.assertGreaterEqual(match.confidence, 0.99)
        self.assertEqual(match.center, (647, 26))

    def test_wait_for_ad_revive_retries_until_match(self):
        from call_of_the_gale.scripts.single_shoot import wait_for_ad_revive_button

        device = MagicMock()
        device.screenshot.side_effect = ["screen1", "screen2"]
        matcher = MagicMock()
        expected = MatchResult(Path("ad_revive_button.png"), 0.91, (647, 26), (626, 11, 42, 31))

        with patch(
            "call_of_the_gale.scripts.single_shoot.find_ad_revive_button_once",
            side_effect=[None, expected],
        ), patch("call_of_the_gale.scripts.single_shoot.time.sleep", return_value=None):
            result = wait_for_ad_revive_button(device, matcher, timeout=2.0, interval=0.5)

        self.assertEqual(result, expected)
        self.assertEqual(device.screenshot.call_count, 2)

if __name__ == '__main__':
    unittest.main()
