import argparse
import os
import sys
import time
import cv2
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

# Setup path to import from src/
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, ".."))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from adb_controller import DeviceController, AdbControllerError
from vision_matcher import VisionMatcher, MatchResult

# ------------------------------------------------------------------
# 配置結構
# ------------------------------------------------------------------
@dataclass
class AdConfig:
    serial: str = "emulator-5554"
    initial_wait_seconds: float = 30.0
    timeout_seconds: float = 120.0
    interval: float = 1.0
    threshold: float = 0.82
    anchor_threshold: float = 0.80
    debug: bool = False
    max_tap_attempts: int = 5

    # 目錄與路徑
    entry_dir: str = os.path.join(_THIS_DIR, "assets", "entry")
    ad_close_dir: str = os.path.join(_THIS_DIR, "assets", "ad_close")
    anchor_dir: str = os.path.join(_THIS_DIR, "assets", "anchors")
    debug_dir: str = os.path.join(_THIS_DIR, "debug")
    captures_dir: str = os.path.join(_THIS_DIR, "captures")


# ------------------------------------------------------------------
# 狀態定義
# ------------------------------------------------------------------
class State(Enum):
    NAV_TO_HUB = auto()
    SWEEP_ADS = auto()
    TAP_FREE_AD = auto()
    INITIAL_WAIT = auto()
    FIND_CLOSE = auto()
    TAP_CLOSE = auto()
    VERIFY_RETURN = auto()
    DONE = auto()
    FAILED = auto()


# ------------------------------------------------------------------
# 核心狀態機
# ------------------------------------------------------------------
class AdRunner:
    def __init__(self, cfg: AdConfig):
        self.cfg = cfg
        self.device = DeviceController(serial=cfg.serial)
        self.matcher: Optional[VisionMatcher] = None
        
        self.state = State.NAV_TO_HUB
        self.start_time: float = 0.0
        self.tap_attempts: int = 0
        self.last_match: Optional[MatchResult] = None
        self.last_screen = None
        self.best_confidence: float = 0.0
        self.best_template: str = ""

    def run(self) -> State:
        print(f"==================================================")
        print(f"[AdRunner] 啟動廣告自動尋寶與觀看流程")
        print(f"==================================================")
        
        if not self._setup():
            return State.FAILED

        self.start_time = time.time()
        
        while self.state not in (State.DONE, State.FAILED):
            try:
                if self.state == State.NAV_TO_HUB:
                    self._do_nav_to_hub()
                elif self.state == State.SWEEP_ADS:
                    self._do_sweep_ads()
                elif self.state == State.TAP_FREE_AD:
                    self._do_tap_free_ad()
                elif self.state == State.INITIAL_WAIT:
                    self._do_initial_wait()
                elif self.state == State.FIND_CLOSE:
                    self._do_find_close()
                elif self.state == State.TAP_CLOSE:
                    self._do_tap_close()
                elif self.state == State.VERIFY_RETURN:
                    self._do_verify_return()
            except AdbControllerError as e:
                self._fail(f"ADB 錯誤: {e}")
                break
            except Exception as e:
                self._fail(f"未預期錯誤: {e}")
                break

        print(f"[AdRunner] 最終狀態: {self.state.name}")
        return self.state

    def _do_nav_to_hub(self):
        print("[NAV_TO_HUB] 判斷目前所在場景...")
        
        screen = self._take_screenshot("nav_detect")
        if screen is None:
            time.sleep(1.0); return
            
        from pathlib import Path
        entry_dir = Path(self.cfg.entry_dir)
        
        # 1. 最深層：是否已經在廣告大廳 (看到大廳錨點)
        from pathlib import Path
        hub_anchor_path = Path(self.cfg.entry_dir) / "hub_anchor.png"
        res_hub = self.matcher.match_template(screen, hub_anchor_path, threshold=0.8)
        
        if res_hub:
            print("  > 已經在廣告大廳 (異界奇聞)，開始點擊")
            self.state = State.SWEEP_ADS
            return

        # 2. 中層：是否在王國事件 (看到異界奇聞的入口)
        otherworld_path = Path(self.cfg.entry_dir) / "nav_otherworld.png"
        res_otherworld = self.matcher.match_template(screen, otherworld_path)
        if res_otherworld:
            print("  > 在王國事件選單，點擊「異界奇聞」...")
            self.device.tap(*res_otherworld.center)
            time.sleep(2.0)
            return # 下一輪迴圈會再次進入 _do_nav_to_hub 判斷

        # 3. 最淺層：是否在「主畫面」 (看到王國事件標籤)
        kingdom_path = Path(self.cfg.entry_dir) / "nav_kingdom.png"
        res_kingdom = self.matcher.match_template(screen, kingdom_path)
        if res_kingdom:
            print("  > 在主畫面，點擊「王國事件」...")
            self.device.tap(*res_kingdom.center)
            time.sleep(2.0)
            return # 下一輪迴圈會再次進入 _do_nav_to_hub 判斷

        # 4. 未知場景
        print("[NAV_TO_HUB] 無法辨識目前場景，找不到導航入口。")
        self._fail("不在已知場景 (主畫面/王國事件/異界奇聞)，無法導航")

    def _find_green_free_button(self, screen: np.ndarray) -> Optional[tuple[int, int]]:
        # 將畫面轉到 HSV，尋找純綠色
        hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
        # 綠色的範圍 (大約 H: 35~85, S: 100~255, V: 100~255)
        lower_green = np.array([35, 100, 100])
        upper_green = np.array([85, 255, 255])
        mask = cv2.inRange(hsv, lower_green, upper_green)
        
        # 尋找綠色區域的輪廓
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best_center = None
        best_area = 0
        
        # 找最大的綠色按鈕 (過濾掉雜訊)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            # 廣告按鈕大約是 120x40 = 4800 像素，我們設定範圍 500 ~ 15000 避免選到整個背景草地
            if 500 < area < 15000: 
                x, y, w, h = cv2.boundingRect(cnt)
                aspect_ratio = float(w) / h
                # 按鈕通常是長方形 (寬大於高)
                if 1.5 < aspect_ratio < 6.0:
                    M = cv2.moments(cnt)
                    if M["m00"] != 0:
                        cx = int(M["m10"] / M["m00"])
                        cy = int(M["m01"] / M["m00"])
                        if cy > 300 and area > best_area:
                            best_area = area
                            best_center = (cx, cy)
                        
        return best_center

    def _do_sweep_ads(self):
        print("[SWEEP_ADS] 尋找綠色「免費」按鈕...")
        
        screen = self._take_screenshot("sweep")
        if screen is None:
            time.sleep(self.cfg.interval)
            return

        # 尋找發光的綠色免費按鈕 (避免誤判灰色的已售完按鈕)
        center = self._find_green_free_button(screen)
        
        if not center:
            # 可能是剛看完廣告後，被「獲得道具」的彈出視窗遮擋住了
            # 嘗試安全點擊畫面邊緣一次來關閉視窗，然後重試
            print("[SWEEP_ADS] 找不到綠色按鈕，可能被獎勵視窗擋住，嘗試點擊畫面邊緣關閉...")
            import sys
            if 'src' not in sys.path:
                sys.path.insert(0, 'src')
            from adb_controller import DeviceController
            DeviceController(self.cfg.serial).tap(50, 500)
            time.sleep(1.5)
            
            # 再截圖一次
            screen = self._take_screenshot("sweep_retry")
            if screen is not None:
                center = self._find_green_free_button(screen)
        
        # 確保找到的是免費按鈕
        if center:
            print(f"[SWEEP_ADS] 找到可看廣告: 綠色按鈕 (center: {center})")
            # 建立一個假的 MatchResult 讓狀態機繼續
            from src.vision_matcher import MatchResult
            from pathlib import Path
            self.last_match = MatchResult(Path("green_btn.png"), 1.0, center, (0,0,0,0))
            self.state = State.TAP_FREE_AD
        else:
            print("[SWEEP_ADS] 畫面上已經沒有綠色的免費廣告按鈕了！今日任務完成。")
            self.state = State.DONE

    def _do_tap_free_ad(self):
        cx, cy = self.last_match.center
        print(f"[TAP_FREE_AD] 點擊觀看廣告: ({cx}, {cy})")
        self.device.tap(cx, cy)
        time.sleep(2.0)
        self.state = State.INITIAL_WAIT

    def _do_initial_wait(self):
        wait = self.cfg.initial_wait_seconds
        print(f"[INITIAL_WAIT] 開始等待 {wait} 秒，讓廣告播放...")
        time.sleep(wait)
        self.state = State.FIND_CLOSE

    def _do_find_close(self):
        elapsed = time.time() - self.start_time
        print(f"[FIND_CLOSE] 掃描關閉按鈕... ({elapsed:.1f}s)")
        screen = self._take_screenshot("find_close")
        if screen is None:
            time.sleep(self.cfg.interval)
            return

        result = self.matcher.match_dir(screen, Path(self.cfg.ad_close_dir), threshold=0.75)
        if result:
            if result.confidence > self.best_confidence:
                self.best_confidence = result.confidence
                self.best_template = result.template_path.name
                
            print(f"[FIND_CLOSE] 找到關閉按鈕: {result.template_path.name} (conf: {result.confidence:.2f})")
            self.last_match = result
            self.state = State.TAP_CLOSE
        else:
            time.sleep(self.cfg.interval)

    def _do_tap_close(self):
        if self.tap_attempts >= self.cfg.max_tap_attempts:
            self._fail("關閉按鈕超過最大點擊嘗試次數")
            return

        cx, cy = self.last_match.center
        self.tap_attempts += 1
        print(f"[TAP_CLOSE] 嘗試點擊關閉 #{self.tap_attempts}: ({cx}, {cy})")
        self.device.tap(cx, cy)
        time.sleep(3.0)
        
        self.state = State.VERIFY_RETURN

    def _do_verify_return(self):
        print("[VERIFY_RETURN] 驗證是否成功關閉廣告...")
        screen = self._take_screenshot("verify")
        if screen is None:
            time.sleep(1.0)
            return

        # 1. 如果關閉按鈕還在，退回 FIND_CLOSE
        still_has_close = self.matcher.match_dir(screen, Path(self.cfg.ad_close_dir))
        if still_has_close:
            print("[VERIFY_RETURN] 關閉按鈕仍在，退回 FIND_CLOSE。")
            self.state = State.FIND_CLOSE
            return
            
        # 2. 回到異界奇聞，繼續掃蕩下一個免費廣告
        print("[VERIFY_RETURN] 成功跳出廣告！返回掃蕩下一個...")
        self.state = State.SWEEP_ADS

    def _fail(self, reason: str):
        self.state = State.FAILED
        print(f"[FAILED] 發生錯誤，停止動作。原因: {reason}")
        if self.last_screen is not None:
            import os, time
            ts = time.strftime("%H%M%S")
            path = os.path.join(self.cfg.debug_dir, f"ad_fail_{ts}.png")
            cv2.imwrite(path, self.last_screen)
            print(f"[FAILED] Screenshot saved to: {path}")
            
            # 黃金法則：發生錯誤自動打開小畫家
            print("[INFO] Opening mspaint...")
            try:
                import subprocess
                subprocess.Popen(["mspaint", str(path)])
            except Exception as e:
                print(f"[WARNING] Could not open mspaint: {e}")

    def _setup(self) -> bool:
        if not self.device.connect():
            print("[ERROR] 無法連線至 ADB")
            return False
            
        try:
            w, h = self.device.get_screen_size()
            print(f"[INFO] 設備解析度: {w}x{h}")
        except:
            w, h = 960, 540
            
        self.matcher = VisionMatcher(
            threshold=self.cfg.threshold,
            debug_dir=Path(self.cfg.debug_dir) if self.cfg.debug else None
        )
        os.makedirs(self.cfg.debug_dir, exist_ok=True)
        return True

    def _take_screenshot(self, tag: str):
        try:
            screen = self.device.screenshot()
            self.last_screen = screen
            if self.cfg.debug:
                ts = time.strftime("%H%M%S")
                cv2.imwrite(os.path.join(self.cfg.debug_dir, f"{tag}_{ts}.png"), screen)
            return screen
        except:
            return None


# ------------------------------------------------------------------
# CLI 命令
# ------------------------------------------------------------------
def run_capture(tag: str, serial: str):
    """手動擷取截圖供後續裁切"""
    device = DeviceController(serial=serial)
    if not device.connect():
        print("連線失敗")
        return
    try:
        screen = device.screenshot()
        captures_dir = os.path.join(_THIS_DIR, "captures")
        os.makedirs(captures_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{tag}_{ts}.png" if tag else f"capture_{ts}.png"
        path = os.path.join(captures_dir, filename)
        cv2.imwrite(path, screen)
        print(f"✅ 截圖已儲存至: {path}")
    except Exception as e:
        print(f"擷取失敗: {e}")


def main():
    parser = argparse.ArgumentParser(description="Ad Closer 廣告自動關閉工具")
    subparsers = parser.add_subparsers(dest="command", help="子命令")
    
    # run command
    run_parser = subparsers.add_parser("run", help="執行自動觀看與關閉廣告")
    run_parser.add_argument("--serial", default="emulator-5554")
    run_parser.add_argument("--debug", action="store_true")
    
    # capture command
    cap_parser = subparsers.add_parser("capture", help="手動擷取畫面")
    cap_parser.add_argument("--serial", default="emulator-5554")
    cap_parser.add_argument("--tag", default="", help="截圖名稱標籤")

    args = parser.parse_args()

    # Default to run if no command
    if args.command is None or args.command == "run":
        cfg = AdConfig(serial=args.serial, debug=args.debug)
        runner = AdRunner(cfg)
        runner.run()
    elif args.command == "capture":
        run_capture(args.tag, args.serial)


if __name__ == "__main__":
    main()
