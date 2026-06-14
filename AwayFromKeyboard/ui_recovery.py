import time
import cv2
import numpy as np
from pathlib import Path
from src.adb_controller import DeviceController
from src.vision_matcher import VisionMatcher
from src.scene_detector import SceneDetector, Scene
from src.config import SHARED_ASSETS_DIR
from AwayFromKeyboard.integration_task.router import RedBoxFinder

MATCH_THRESHOLD = 0.80
UI_WAIT_SEC = 2.0
ARTIFACT_ROI = (804, 487, 944, 540)

class UIRecovery:
    def __init__(self, controller: DeviceController, matcher: VisionMatcher, detector: SceneDetector):
        self.controller = controller
        self.matcher = matcher
        self.detector = detector
        
        project_root = Path(__file__).resolve().parent.parent
        template_path = project_root / "AwayFromKeyboard" / "assets" / "main_anchor_artifact.png"
        if template_path.exists():
            self._artifact_template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
        else:
            self._artifact_template = None

    def _is_artifact_present(self, screen: np.ndarray) -> bool:
        if self._artifact_template is None:
            return False
            
        sh, sw = screen.shape[:2]
        x1, y1, x2, y2 = ARTIFACT_ROI
        x2, y2 = min(sw, x2), min(sh, y2)
        
        if y1 >= sh or x1 >= sw:
            return False
            
        roi = screen[y1:y2, x1:x2]
        if roi.shape[0] == 0 or roi.shape[1] == 0:
            return False
            
        res = cv2.matchTemplate(roi, self._artifact_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        return max_val >= MATCH_THRESHOLD

    def handle_remote_login(self) -> bool:
        project_root = Path(__file__).resolve().parent.parent
        route_dir = project_root / "AwayFromKeyboard" / "route_screenshots" / "異地登入"
        
        img_01 = route_dir / "01_異地登入.png"
        
        if not img_01.exists():
            print("⚠️ [警告] 找不到異地登入截圖，略過檢查。")
            return False
            
        screen = self.controller.screenshot()
        if screen is None:
            return False
            
        # 1. 提取綠框 (字樣) 與紅框 (按鈕)
        original_img = cv2.imdecode(np.fromfile(img_01, dtype=np.uint8), cv2.IMREAD_COLOR)
        if original_img is None:
            return False
            
        # 找綠框
        hsv = cv2.cvtColor(original_img, cv2.COLOR_BGR2HSV)
        lower_green = np.array([50, 100, 100])
        upper_green = np.array([70, 255, 255])
        green_mask = cv2.inRange(hsv, lower_green, upper_green)
        g_contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        gx, gy, gw, gh = 0, 0, 0, 0
        best_g_area = 0
        for cnt in g_contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area = w * h
            if area > best_g_area and w > 10 and h > 10:
                best_g_area = area
                gx, gy, gw, gh = x, y, w, h
                
        if best_g_area == 0:
            print("⚠️ [警告] 在異地登入圖片中找不到綠框！")
            return False
            
        green_template = original_img[gy:gy+gh, gx:gx+gw]
        
        # 在當前螢幕比對綠框
        sh, sw = screen.shape[:2]
        roi_x1 = max(0, gx - 50)
        roi_x2 = min(sw, gx + gw + 50)
        roi_y1 = max(0, gy - 150)
        roi_y2 = min(sh, gy + gh + 150)
        
        screen_roi = screen[roi_y1:roi_y2, roi_x1:roi_x2]
        res = cv2.matchTemplate(screen_roi, green_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        
        if max_val < 0.7:
            print("[系統] 未偵測到異地登入，正常放行。")
            return False
            
        print("👉 偵測到異地登入畫面！尋找確認按鈕...")
        
        # 2. 找紅框 (確認按鈕)
        finder = RedBoxFinder()
        try:
            (cx, cy), (rx, ry, rw, rh), _ = finder.find_largest_red_box_info(img_01)
            red_template = original_img[ry:ry+rh, rx:rx+rw]
            
            roi_x1_r = max(0, rx - 50)
            roi_x2_r = min(sw, rx + rw + 50)
            roi_y1_r = max(0, ry - 150)
            roi_y2_r = min(sh, ry + rh + 150)
            
            screen_roi_r = screen[roi_y1_r:roi_y2_r, roi_x1_r:roi_x2_r]
            res_r = cv2.matchTemplate(screen_roi_r, red_template, cv2.TM_CCOEFF_NORMED)
            _, max_val_r, _, max_loc_r = cv2.minMaxLoc(res_r)
            
            if max_val_r >= 0.7:
                abs_cx = roi_x1_r + max_loc_r[0] + rw // 2
                abs_cy = roi_y1_r + max_loc_r[1] + rh // 2
                print(f"👉 點擊確認按鈕 ({abs_cx}, {abs_cy})")
                self.controller.tap(abs_cx, abs_cy)
                time.sleep(3.0)
                
                # 4. 交給 game_entry 處理登入
                from src.game_entry import reenter_game
                return reenter_game(self.controller, self.matcher)
            else:
                print("⚠️ [警告] 找不到確認按鈕")
                return False
                
        except Exception as e:
            print(f"⚠️ [警告] 處理異地登入時發生錯誤: {e}")
            return False

    def recover_to_main(self, max_attempts=15) -> bool:
        """
        嘗試關閉任何彈窗，直到畫面確認為 Scene.MAIN
        """
        back_btn = SHARED_ASSETS_DIR / "back_button.png"
        close_btn = SHARED_ASSETS_DIR / "dialog_close_button.png"
        
        for attempt in range(max_attempts):
            screen = self.controller.screenshot()
            detected = self.detector.detect(screen)
            
            if detected.scene == Scene.MAIN or self._is_artifact_present(screen):
                print("✅ 成功回到主城 (Scene.MAIN)")
                return True
                
            print(f"[{attempt+1}/{max_attempts}] 目前場景: {detected.scene.value}，嘗試尋找關閉/返回按鈕...")
            
            # 優先嘗試 Dialog Close (因為登入後通常是一堆關閉視窗)
            if close_btn.exists():
                match = self.matcher.match_template(screen, close_btn, threshold=MATCH_THRESHOLD)
                if match:
                    print(f"👉 點擊關閉按鈕 {match.center}")
                    self.controller.tap(*match.center)
                    time.sleep(UI_WAIT_SEC)
                    continue

            # 其次嘗試 Back Button
            if back_btn.exists():
                match = self.matcher.match_template(screen, back_btn, threshold=MATCH_THRESHOLD)
                if match:
                    print(f"👉 點擊返回按鈕 {match.center}")
                    self.controller.tap(*match.center)
                    time.sleep(UI_WAIT_SEC)
                    continue
                    
            # 如果都找不到明確的按鈕，就等待一下（動畫或載入中）
            print(f"⏳ 找不到明確的關閉按鈕，等待 {UI_WAIT_SEC} 秒...")
            time.sleep(UI_WAIT_SEC)
            
        print("❌ 無法自動回到主城")
        return False
