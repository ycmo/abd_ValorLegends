import unittest
from pathlib import Path
import tempfile
import shutil
import sys
import numpy as np
import cv2

# Ensure router.py can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from router import RouteNavigator

class FakeDeviceController:
    def __init__(self, screen_image=None):
        self.taps = []
        self.screen_image = screen_image

    def tap(self, x, y):
        self.taps.append((x, y))
        
    def screenshot(self):
        return self.screen_image


class FakeRedBoxFinder:
    def __init__(self, mock_results=None):
        self.mock_results = mock_results or {}

    def find_largest_red_box_info(self, img_path: Path):
        if img_path.name in self.mock_results:
            return self.mock_results[img_path.name]
        raise ValueError(f"在 {img_path.name} 中找不到符合條件的紅框！(Fake)")


class TestRouter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.route_name = "test_route"
        self.route_dir = self.temp_dir / "route_screenshots" / self.route_name
        self.route_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_execute_route_match_success(self):
        # 建立假圖片檔案
        (self.route_dir / "01_first.png").write_text("fake")
        
        # 建立一個模擬的原圖 100x100
        original_img = np.zeros((100, 100, 3), dtype=np.uint8)
        # 填上不均勻特徵讓 template match 有變異數
        original_img[40:60, 40:60] = 128
        original_img[45:55, 45:55] = 255
        
        # 設定紅框中心與邊界: 中心 (50, 50), 邊界 (40, 40, 20, 20)
        mock_results = {
            "01_first.png": ((50, 50), (40, 40, 20, 20), original_img)
        }

        # 建立一個實機畫面 200x200
        screen_image = np.zeros((200, 200, 3), dtype=np.uint8)
        # 把相同的特徵畫在偏移的位置 (例如 x+10, y+20) => x=50, y=60
        # 這樣絕對中心點應該是 (60, 70)
        screen_image[60:80, 50:70] = 128
        screen_image[65:75, 55:65] = 255

        controller = FakeDeviceController(screen_image=screen_image)
        finder = FakeRedBoxFinder(mock_results)
        
        navigator = RouteNavigator(
            route_name=self.route_name,
            controller=controller,
            finder=finder,
            base_dir=self.temp_dir
        )

        navigator.execute_route()

        # 驗證 tap 是否點擊在偏移後的絕對座標上
        self.assertEqual(len(controller.taps), 1)
        self.assertEqual(controller.taps[0], (60, 70))

    def test_execute_route_fallback(self):
        # 建立假圖片檔案
        (self.route_dir / "01_first.png").write_text("fake")
        
        original_img = np.zeros((100, 100, 3), dtype=np.uint8)
        original_img[40:60, 40:60] = 128
        original_img[45:55, 45:55] = 255
        
        mock_results = {
            "01_first.png": ((50, 50), (40, 40, 20, 20), original_img)
        }

        # 建立一個隨機雜訊的實機畫面，保證比對不到
        np.random.seed(42)
        screen_image = np.random.randint(0, 256, (200, 200, 3), dtype=np.uint8)

        controller = FakeDeviceController(screen_image=screen_image)
        finder = FakeRedBoxFinder(mock_results)
        
        navigator = RouteNavigator(
            route_name=self.route_name,
            controller=controller,
            finder=finder,
            base_dir=self.temp_dir
        )

        with self.assertRaises(ValueError) as context:
            navigator.execute_route()
            
        self.assertIn("比對失敗！步驟群組 01 找不到目標", str(context.exception))
        
        # 驗證 fallback 不會觸發點擊
        self.assertEqual(len(controller.taps), 0)
        
        # 驗證 debug 圖片已產生
        debug_img_path = self.temp_dir / "debug" / "fallback_01_first.png"
        self.assertTrue(debug_img_path.exists())

    def test_route_directory_not_found(self):
        controller = FakeDeviceController()
        finder = FakeRedBoxFinder()
        
        navigator = RouteNavigator(
            route_name="non_existent_route",
            controller=controller,
            finder=finder,
            base_dir=self.temp_dir
        )

        with self.assertRaises(FileNotFoundError):
            navigator.execute_route()

    def test_no_png_files_in_directory(self):
        controller = FakeDeviceController()
        finder = FakeRedBoxFinder()
        
        navigator = RouteNavigator(
            route_name=self.route_name,
            controller=controller,
            finder=finder,
            base_dir=self.temp_dir
        )

        with self.assertRaises(FileNotFoundError):
            navigator.execute_route()

    def test_missing_red_box_raises_exception(self):
        (self.route_dir / "01_first.png").write_text("fake")
        
        controller = FakeDeviceController()
        finder = FakeRedBoxFinder()
        
        navigator = RouteNavigator(
            route_name=self.route_name,
            controller=controller,
            finder=finder,
            base_dir=self.temp_dir
        )

        with self.assertRaises(ValueError):
            navigator.execute_route()
        self.assertEqual(len(controller.taps), 0)

if __name__ == "__main__":
    unittest.main()
