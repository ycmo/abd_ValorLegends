import unittest
from pathlib import Path
import tempfile
import shutil
import sys
import numpy as np
import cv2
from unittest.mock import patch

# Ensure router.py can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from router import RouteNavigator
from src.blocker_handler import GIFT_PACK_CLOSE_POINT

class FakeDeviceController:
    def __init__(self, screen_image=None, screen_images=None):
        self.taps = []
        self.tap_annotations = []
        self.screen_image = screen_image
        self.screen_images = list(screen_images or [])
        self.screenshot_count = 0

    def tap(self, x, y):
        self.taps.append((x, y))

    def annotate_next_tap_debug(self, *, lines=(), boxes=()):
        self.tap_annotations.append((list(lines), list(boxes)))
        
    def screenshot(self):
        self.screenshot_count += 1
        if self.screen_images:
            self.screen_image = self.screen_images.pop(0)
        return self.screen_image


class FakeRedBoxFinder:
    def __init__(self, mock_results=None):
        self.mock_results = mock_results or {}

    def find_largest_red_box_info(self, img_path: Path):
        if img_path.name in self.mock_results:
            return self.mock_results[img_path.name]
        raise ValueError(f"在 {img_path.name} 中找不到符合條件的紅框！(Fake)")


class FakeColorBoxFinder(FakeRedBoxFinder):
    def find_largest_box_info(self, img_path: Path):
        if img_path.name in self.mock_results:
            return self.mock_results[img_path.name]
        raise ValueError(f"在 {img_path.name} 中找不到符合條件的框！(Fake)")

    def find_largest_red_box_info(self, img_path: Path):
        if img_path.name in self.mock_results:
            center, rect, img, kind = self.mock_results[img_path.name]
            if kind == "red":
                return center, rect, img
        raise ValueError(f"在 {img_path.name} 中找不到符合條件的紅框！(Fake)")

    def find_largest_green_box_info(self, img_path: Path):
        if img_path.name in self.mock_results:
            center, rect, img, kind = self.mock_results[img_path.name]
            if kind == "green":
                return center, rect, img
        raise ValueError(f"在 {img_path.name} 中找不到符合條件的綠框！(Fake)")


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

        with patch("router.time.sleep"):
            navigator.execute_route()

        # 驗證 tap 是否點擊在偏移後的絕對座標上
        self.assertEqual(len(controller.taps), 1)
        self.assertEqual(controller.taps[0], (60, 70))
        self.assertEqual(len(controller.tap_annotations), 1)
        lines, boxes = controller.tap_annotations[0]
        self.assertIn("router route=test_route phase=enter", lines)
        self.assertIn("template=01_first.png confidence=1.000", lines)
        self.assertEqual(boxes, [(50, 60, 20, 20, "route_match")])

    def test_execute_route_only_prefixes_runs_selected_group(self):
        (self.route_dir / "01_first.png").write_text("fake")
        (self.route_dir / "02_second.png").write_text("fake")

        original_img_01 = np.zeros((100, 100, 3), dtype=np.uint8)
        original_img_01[20:40, 20:40] = 128
        original_img_01[25:35, 25:35] = 255

        original_img_02 = np.zeros((100, 100, 3), dtype=np.uint8)
        original_img_02[40:60, 40:60] = 64
        original_img_02[45:55, 45:55] = 255

        mock_results = {
            "01_first.png": ((30, 30), (20, 20, 20, 20), original_img_01),
            "02_second.png": ((50, 50), (40, 40, 20, 20), original_img_02),
        }

        screen_image = np.zeros((200, 200, 3), dtype=np.uint8)
        screen_image[80:100, 70:90] = 64
        screen_image[85:95, 75:85] = 255

        controller = FakeDeviceController(screen_image=screen_image)
        navigator = RouteNavigator(
            route_name=self.route_name,
            controller=controller,
            finder=FakeRedBoxFinder(mock_results),
            base_dir=self.temp_dir,
        )

        with patch("router.time.sleep"):
            navigator.execute_route(only_prefixes=("02",))

        self.assertEqual(controller.taps, [(80, 90)])
        lines, _boxes = controller.tap_annotations[0]
        self.assertIn("template=02_second.png confidence=1.000", lines)

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

    def test_verify_step_succeeds_only_after_button_disappears(self):
        (self.route_dir / "01_first_verify.png").write_text("fake")

        original_img = np.zeros((100, 100, 3), dtype=np.uint8)
        original_img[40:60, 40:60] = 128
        original_img[45:55, 45:55] = 255
        mock_results = {
            "01_first_verify.png": ((50, 50), (40, 40, 20, 20), original_img)
        }

        matched_screen = np.zeros((200, 200, 3), dtype=np.uint8)
        matched_screen[60:80, 50:70] = 128
        matched_screen[65:75, 55:65] = 255
        disappeared_screen = np.zeros((200, 200, 3), dtype=np.uint8)
        controller = FakeDeviceController(screen_images=[matched_screen, disappeared_screen])
        navigator = RouteNavigator(
            route_name=self.route_name,
            controller=controller,
            finder=FakeRedBoxFinder(mock_results),
            base_dir=self.temp_dir,
        )

        with patch("router.time.sleep"):
            navigator.execute_route()

        self.assertEqual(controller.taps, [(60, 70)])
        self.assertEqual(controller.screenshot_count, 2)

    def test_verify_step_fails_after_three_clicks_when_button_remains(self):
        (self.route_dir / "01_first_verify.png").write_text("fake")

        original_img = np.zeros((100, 100, 3), dtype=np.uint8)
        original_img[40:60, 40:60] = 128
        original_img[45:55, 45:55] = 255
        mock_results = {
            "01_first_verify.png": ((50, 50), (40, 40, 20, 20), original_img)
        }
        matched_screen = np.zeros((200, 200, 3), dtype=np.uint8)
        matched_screen[60:80, 50:70] = 128
        matched_screen[65:75, 55:65] = 255
        controller = FakeDeviceController(screen_image=matched_screen)
        navigator = RouteNavigator(
            route_name=self.route_name,
            controller=controller,
            finder=FakeRedBoxFinder(mock_results),
            base_dir=self.temp_dir,
        )

        with patch("router.time.sleep"):
            with self.assertRaisesRegex(ValueError, "經 3 次點擊後仍未消失"):
                navigator.execute_route()

        self.assertEqual(controller.taps, [(60, 70), (60, 70), (60, 70)])

    def test_green_anchor_matches_without_tapping(self):
        (self.route_dir / "01_anchor.png").write_text("fake")

        original_img = np.zeros((100, 100, 3), dtype=np.uint8)
        original_img[40:60, 40:60] = 90
        original_img[45:55, 45:55] = 210
        mock_results = {
            "01_anchor.png": ((50, 50), (40, 40, 20, 20), original_img, "green")
        }

        screen_image = np.zeros((200, 200, 3), dtype=np.uint8)
        screen_image[60:80, 50:70] = 90
        screen_image[65:75, 55:65] = 210
        controller = FakeDeviceController(screen_image=screen_image)
        navigator = RouteNavigator(
            route_name=self.route_name,
            controller=controller,
            finder=FakeColorBoxFinder(mock_results),
            base_dir=self.temp_dir,
        )

        with patch("router.time.sleep"):
            navigator.execute_route()

        self.assertEqual(controller.taps, [])
        self.assertEqual(controller.screenshot_count, 1)

    def test_verify_next_waits_for_next_step_before_continuing(self):
        (self.route_dir / "01_first_verifyNext.png").write_text("fake")
        (self.route_dir / "02_next_anchor.png").write_text("fake")

        first_img = np.zeros((100, 100, 3), dtype=np.uint8)
        first_img[40:60, 40:60] = 128
        first_img[45:55, 45:55] = 255
        next_img = np.zeros((100, 100, 3), dtype=np.uint8)
        next_img[30:50, 70:90] = 70
        next_img[35:45, 75:85] = 200
        mock_results = {
            "01_first_verifyNext.png": ((50, 50), (40, 40, 20, 20), first_img, "red"),
            "02_next_anchor.png": ((80, 40), (70, 30, 20, 20), next_img, "green"),
        }

        first_screen = np.zeros((200, 200, 3), dtype=np.uint8)
        first_screen[60:80, 50:70] = 128
        first_screen[65:75, 55:65] = 255
        blank_screen = np.zeros((200, 200, 3), dtype=np.uint8)
        next_screen = np.zeros((200, 200, 3), dtype=np.uint8)
        next_screen[80:100, 90:110] = 70
        next_screen[85:95, 95:105] = 200

        controller = FakeDeviceController(
            screen_images=[first_screen, blank_screen, next_screen, next_screen]
        )
        navigator = RouteNavigator(
            route_name=self.route_name,
            controller=controller,
            finder=FakeColorBoxFinder(mock_results),
            base_dir=self.temp_dir,
        )

        with patch("router.time.sleep"):
            navigator.execute_route()

        self.assertEqual(controller.taps, [(60, 70)])
        self.assertGreaterEqual(controller.screenshot_count, 4)

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

    def test_handle_blocking_popup_taps_close_point(self):
        blocker_dir = self.temp_dir / "integration_task" / "templates" / "blockers"
        blocker_dir.mkdir(parents=True)

        template = np.zeros((45, 92, 3), dtype=np.uint8)
        template[:, :] = (20, 30, 40)
        template[8:36, 14:78] = (230, 230, 255)
        template[16:28, 30:62] = (40, 80, 230)
        cv2.imwrite(str(blocker_dir / "gift_pack_label.png"), template)

        screen = np.zeros((540, 960, 3), dtype=np.uint8)
        screen[194:239, 490:582] = template

        controller = FakeDeviceController(screen_image=screen)
        navigator = RouteNavigator(
            route_name=self.route_name,
            controller=controller,
            finder=FakeRedBoxFinder(),
            base_dir=self.temp_dir,
        )

        with patch("router.time.sleep"):
            handled = navigator._handle_blocking_popup(screen)

        self.assertTrue(handled)
        self.assertEqual(controller.taps, [GIFT_PACK_CLOSE_POINT])

    def test_vertical_swipe_uses_search_roi_center(self):
        controller = FakeDeviceController()
        navigator = RouteNavigator(
            route_name=self.route_name,
            controller=controller,
            finder=FakeRedBoxFinder(),
            base_dir=self.temp_dir,
        )

        points = navigator._dynamic_swipe_points(
            {"x": 9, "w": 116},
            screen_width=960,
            screen_height=540,
            swipe_dir=1,
        )

        self.assertEqual(points, (87, 405, 87, 135, 700))

    def test_optional_miss_does_not_save_debug_by_default(self):
        (self.route_dir / "01_optional.png").write_text("fake")

        original_img = np.zeros((100, 100, 3), dtype=np.uint8)
        original_img[40:60, 40:60] = 128
        original_img[45:55, 45:55] = 255
        mock_results = {
            "01_optional.png": ((50, 50), (40, 40, 20, 20), original_img)
        }

        np.random.seed(42)
        screen_image = np.random.randint(0, 256, (200, 200, 3), dtype=np.uint8)
        controller = FakeDeviceController(screen_image=screen_image)
        navigator = RouteNavigator(
            route_name=self.route_name,
            controller=controller,
            finder=FakeRedBoxFinder(mock_results),
            base_dir=self.temp_dir,
            debug_actions=False,
        )

        with patch("router.time.sleep"):
            navigator.execute_route()

        debug_img_path = self.temp_dir / "debug" / "fallback_01_optional.png"
        self.assertFalse(debug_img_path.exists())
        self.assertEqual(controller.taps, [])
        self.assertEqual(controller.screenshot_count, 12)

    def test_optional_miss_saves_debug_when_debug_actions_enabled(self):
        (self.route_dir / "01_optional.png").write_text("fake")

        original_img = np.zeros((100, 100, 3), dtype=np.uint8)
        original_img[40:60, 40:60] = 128
        original_img[45:55, 45:55] = 255
        mock_results = {
            "01_optional.png": ((50, 50), (40, 40, 20, 20), original_img)
        }

        np.random.seed(42)
        screen_image = np.random.randint(0, 256, (200, 200, 3), dtype=np.uint8)
        controller = FakeDeviceController(screen_image=screen_image)
        navigator = RouteNavigator(
            route_name=self.route_name,
            controller=controller,
            finder=FakeRedBoxFinder(mock_results),
            base_dir=self.temp_dir,
            debug_actions=True,
        )

        navigator.execute_route()

        debug_img_path = self.temp_dir / "debug" / "fallback_01_optional.png"
        self.assertTrue(debug_img_path.exists())
        self.assertEqual(controller.taps, [])
        self.assertEqual(controller.screenshot_count, 12)

if __name__ == "__main__":
    unittest.main()
