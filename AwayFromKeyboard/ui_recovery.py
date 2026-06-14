import time
import cv2
import numpy as np
from pathlib import Path
from src.adb_controller import DeviceController
from src.vision_matcher import VisionMatcher
from src.scene_detector import SceneDetector, Scene
from src.config import SHARED_ASSETS_DIR

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
