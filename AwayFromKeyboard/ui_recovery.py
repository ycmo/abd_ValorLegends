import time
from pathlib import Path
from src.adb_controller import DeviceController
from src.vision_matcher import VisionMatcher
from src.scene_detector import SceneDetector, Scene
from src.config import SHARED_ASSETS_DIR

class UIRecovery:
    def __init__(self, controller: DeviceController, matcher: VisionMatcher, detector: SceneDetector):
        self.controller = controller
        self.matcher = matcher
        self.detector = detector

    def recover_to_main(self, max_attempts=15) -> bool:
        """
        嘗試關閉任何彈窗，直到畫面確認為 Scene.MAIN
        """
        back_btn = SHARED_ASSETS_DIR / "back_button.png"
        close_btn = SHARED_ASSETS_DIR / "dialog_close_button.png"
        
        for attempt in range(max_attempts):
            screen = self.controller.screenshot()
            detected = self.detector.detect(screen)
            
            if detected.scene == Scene.MAIN:
                print("✅ 成功回到主城 (Scene.MAIN)")
                return True
                
            print(f"[{attempt+1}/{max_attempts}] 目前場景: {detected.scene.value}，嘗試尋找關閉/返回按鈕...")
            
            # 優先嘗試 Dialog Close (因為登入後通常是一堆關閉視窗)
            if close_btn.exists():
                match = self.matcher.match_template(screen, close_btn, threshold=0.80)
                if match:
                    print(f"👉 點擊關閉按鈕 {match.center}")
                    self.controller.tap(*match.center)
                    time.sleep(2)
                    continue

            # 其次嘗試 Back Button
            if back_btn.exists():
                match = self.matcher.match_template(screen, back_btn, threshold=0.80)
                if match:
                    print(f"👉 點擊返回按鈕 {match.center}")
                    self.controller.tap(*match.center)
                    time.sleep(2)
                    continue
                    
            # 如果都找不到明確的按鈕，就等待一下（動畫或載入中）
            print("⏳ 找不到明確的關閉按鈕，等待 2 秒...")
            time.sleep(2)
            
        print("❌ 無法自動回到主城")
        return False
