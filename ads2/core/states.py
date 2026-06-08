import time
from .context import RunnerContext, StateName
from .vision import find_green_free_button
from src.vision_matcher import MatchResult
from pathlib import Path

class BaseState:
    def __init__(self, context: RunnerContext):
        self.ctx = context

    def run(self) -> StateName:
        raise NotImplementedError

class SweepAdsState(BaseState):
    """掃描畫面，尋找可點擊的綠色免費廣告按鈕"""
    def run(self) -> StateName:
        self.ctx.log("[SWEEP_ADS] 尋找綠色「免費」按鈕...")
        screen = self.ctx.take_screenshot("sweep")
        if screen is None:
            time.sleep(self.ctx.cfg.interval)
            return StateName.SWEEP_ADS

        center = find_green_free_button(screen)
        
        if not center:
            self.ctx.log("[SWEEP_ADS] 找不到綠色按鈕，可能被獎勵視窗擋住，嘗試點擊畫面邊緣關閉...")
            self.ctx.device.tap(50, 500)
            time.sleep(1.5)
            
            screen = self.ctx.take_screenshot("sweep_retry")
            if screen is not None:
                center = find_green_free_button(screen)
        
        if center:
            self.ctx.log(f"[SWEEP_ADS] 找到可看廣告: 綠色按鈕 (center: {center})")
            self.ctx.last_match = MatchResult(Path("green_btn.png"), 1.0, center, (0,0,0,0))
            return StateName.TAP_FREE_AD
        else:
            self.ctx.log("[SWEEP_ADS] 畫面上已經沒有綠色的免費廣告按鈕了！今日任務完成。")
            return StateName.DONE


class TapFreeAdState(BaseState):
    """點擊免費廣告按鈕並進入廣告"""
    def run(self) -> StateName:
        if not self.ctx.last_match:
            self.ctx.fail("No match result to tap.")
            return StateName.FAILED

        cx, cy = self.ctx.last_match.center
        self.ctx.log(f"[TAP_FREE_AD] 點擊觀看廣告: ({cx}, {cy})")
        self.ctx.device.tap(cx, cy)
        time.sleep(2.0)
        return StateName.INITIAL_WAIT


class InitialWaitState(BaseState):
    """進入廣告後的初始盲等期"""
    def run(self) -> StateName:
        wait = self.ctx.cfg.initial_wait_seconds
        self.ctx.log(f"[INITIAL_WAIT] 開始等待 {wait} 秒，讓廣告播放...")
        time.sleep(wait)
        # 進入尋找關閉按鈕狀態，並記錄開始尋找的時間
        self.ctx.start_time = time.time()
        self.ctx.tap_attempts = 0
        return StateName.FIND_CLOSE


class FindCloseState(BaseState):
    """掃描畫面，尋找所有的關閉(X)、略過(Skip)按鈕"""
    def run(self) -> StateName:
        elapsed = time.time() - self.ctx.start_time
        self.ctx.log(f"[FIND_CLOSE] 掃描關閉按鈕... ({elapsed:.1f}s)")
        
        if elapsed > self.ctx.cfg.timeout_seconds:
            self.ctx.fail("尋找關閉按鈕超時 (120秒)")
            return StateName.FAILED

        screen = self.ctx.take_screenshot("find_close")
        if screen is None:
            time.sleep(self.ctx.cfg.interval)
            return StateName.FIND_CLOSE

        # 優先檢查是否廣告提早結束，已經回到大廳
        if self._is_back_to_hub(screen):
            self.ctx.log("[FIND_CLOSE] 尚未點擊關閉，但畫面已回到遊戲場景！廣告可能已自行關閉，返回掃蕩...")
            return StateName.SWEEP_ADS

        # 比對 close_icons 目錄下的所有關閉按鈕特徵
        result = self.ctx.matcher.match_dir(screen, self.ctx.cfg.close_icons_dir, threshold=self.ctx.cfg.threshold)
        if result:
            if result.confidence > self.ctx.best_confidence:
                self.ctx.best_confidence = result.confidence
                self.ctx.best_template = result.template_path.name
                
            self.ctx.log(f"[FIND_CLOSE] 找到關閉按鈕: {result.template_path.name} (conf: {result.confidence:.2f})")
            self.ctx.last_match = result
            return StateName.TAP_CLOSE
        else:
            time.sleep(self.ctx.cfg.interval)
            return StateName.FIND_CLOSE

    def _is_back_to_hub(self, screen) -> bool:
        """驗證是否已返回廣告大廳或主畫面"""
        anchors = [
            self.ctx.cfg.scene_anchors_dir / "hub_anchor.png",
            self.ctx.cfg.nav_icons_dir / "nav_kingdom.png",
            self.ctx.cfg.scene_anchors_dir / "shop_anchor.png"
        ]
        for anchor in anchors:
            if anchor.exists() and self.ctx.matcher.match_template(screen, anchor, threshold=self.ctx.cfg.anchor_threshold):
                return True
        return False


class TapCloseState(BaseState):
    """點擊關閉或略過按鈕"""
    def run(self) -> StateName:
        if self.ctx.tap_attempts >= self.ctx.cfg.max_tap_attempts:
            self.ctx.fail("關閉按鈕超過最大點擊嘗試次數")
            return StateName.FAILED

        cx, cy = self.ctx.last_match.center
        
        # 多次點擊加入偏移量
        if self.ctx.tap_attempts > 0:
            dx = 1 if cx < 300 else -1
            dy = 1 if cy < 300 else -1
            offset = 15 * self.ctx.tap_attempts
            cx += dx * offset
            cy += dy * offset

        self.ctx.tap_attempts += 1
        self.ctx.log(f"[TAP_CLOSE] 嘗試點擊關閉 #{self.ctx.tap_attempts}: ({cx}, {cy})")
        self.ctx.device.tap(cx, cy)
        time.sleep(3.0)
        
        return StateName.VERIFY_RETURN


class VerifyReturnState(BaseState):
    """確認點擊關閉後是否成功返回遊戲大廳"""
    def run(self) -> StateName:
        self.ctx.log("[VERIFY_RETURN] 驗證是否成功關閉廣告...")
        
        for attempt in range(5):
            screen = self.ctx.take_screenshot("verify")
            if screen is None:
                time.sleep(1.0)
                continue

            # 1. 如果關閉按鈕還在，退回 FIND_CLOSE
            still_has_close = self.ctx.matcher.match_dir(screen, self.ctx.cfg.close_icons_dir, threshold=self.ctx.cfg.threshold)
            if still_has_close:
                self.ctx.log(f"[VERIFY_RETURN] 發現關閉按鈕 {still_has_close.template_path.name}，退回 FIND_CLOSE。")
                return StateName.FIND_CLOSE
                
            # 2. 判斷是否已經回到大廳
            if self._is_back_to_hub(screen):
                self.ctx.log("[VERIFY_RETURN] 確認已回到遊戲場景！返回掃蕩下一個...")
                return StateName.SWEEP_ADS
                
            self.ctx.log(f"  > 尚未看到關閉按鈕，也尚未回到遊戲場景，等待中... ({attempt+1}/5)")
            time.sleep(1.0)
            
        self.ctx.log("[VERIFY_RETURN] 超時未發現明確特徵，假設已成功跳出，嘗試掃蕩下一個...")
        return StateName.SWEEP_ADS

    def _is_back_to_hub(self, screen) -> bool:
        anchors = [
            self.ctx.cfg.scene_anchors_dir / "hub_anchor.png",
            self.ctx.cfg.nav_icons_dir / "nav_kingdom.png",
            self.ctx.cfg.scene_anchors_dir / "shop_anchor.png"
        ]
        for anchor in anchors:
            if anchor.exists() and self.ctx.matcher.match_template(screen, anchor, threshold=self.ctx.cfg.anchor_threshold):
                return True
        return False
