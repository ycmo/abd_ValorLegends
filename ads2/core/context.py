from typing import Optional
from enum import Enum, auto
import time
import os
import sys

# Setup project root import
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.adb_controller import DeviceController
from src.vision_matcher import VisionMatcher, MatchResult
from .config import AdConfig

class StateName(Enum):
    NAV_TO_HUB = auto()
    SWEEP_ADS = auto()
    TAP_FREE_AD = auto()
    INITIAL_WAIT = auto()
    FIND_CLOSE = auto()
    TAP_CLOSE = auto()
    VERIFY_RETURN = auto()
    DONE = auto()
    FAILED = auto()

class RunnerContext:
    def __init__(self, cfg: AdConfig):
        self.cfg = cfg
        self.device = DeviceController(serial=cfg.serial)
        
        # Will be initialized in setup()
        self.matcher: Optional[VisionMatcher] = None
        
        self.state: StateName = StateName.NAV_TO_HUB
        self.start_time: float = 0.0
        self.tap_attempts: int = 0
        
        self.last_match: Optional[MatchResult] = None
        self.last_screen = None
        
        self.best_confidence: float = 0.0
        self.best_template: str = ""
        
        self.run_id = time.strftime("%Y%m%d_%H%M%S")
        self.run_dir = self.cfg.debug_dir / f"run_{self.run_id}"
        self.log_file = None

    def setup(self) -> bool:
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
            debug_dir=self.cfg.debug_dir if self.cfg.debug else None
        )
        
        os.makedirs(self.cfg.debug_dir, exist_ok=True)
        if self.cfg.debug:
            os.makedirs(self.run_dir, exist_ok=True)
            self.log_file = open(self.run_dir / "run.log", "w", encoding="utf-8")
        return True

    def log(self, msg: str):
        print(msg)
        if self.log_file:
            ts = time.strftime("%H:%M:%S")
            self.log_file.write(f"[{ts}] {msg}\n")
            self.log_file.flush()

    def take_screenshot(self, tag: str):
        import cv2
        try:
            screen = self.device.screenshot()
            self.last_screen = screen
            if self.cfg.debug:
                ts = time.strftime("%H%M%S")
                cv2.imwrite(str(self.run_dir / f"{ts}_{tag}.png"), screen)
            return screen
        except Exception as e:
            self.log(f"[ERROR] Screenshot failed: {e}")
            return None

    def fail(self, reason: str):
        import cv2
        self.state = StateName.FAILED
        self.log(f"[FAILED] 發生錯誤，停止動作。原因: {reason}")
        if self.last_screen is not None:
            ts = time.strftime("%H%M%S")
            path = self.cfg.debug_dir / f"ad_fail_{ts}.png"
            cv2.imwrite(str(path), self.last_screen)
            self.log(f"[FAILED] Screenshot saved to: {path}")
            
            # 黃金法則：發生錯誤自動打開小畫家
            self.log("[INFO] Opening mspaint...")
            try:
                import subprocess
                subprocess.Popen(["mspaint", str(path)])
            except Exception as e:
                self.log(f"[WARNING] Could not open mspaint: {e}")
