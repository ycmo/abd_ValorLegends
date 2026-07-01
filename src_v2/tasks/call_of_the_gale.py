from __future__ import annotations

import time
import math
import random
import cv2
import numpy as np

from src_v2.task_runner import BaseTask, TaskSceneAnchor, TaskRunResult, TaskState
from src_v2.config import TASK_SPECS
from src.exceptions import TaskFailedError
from src.ocr_utils import get_cached_easyocr_reader

class CallOfTheGaleTask(BaseTask):
    spec = TASK_SPECS["call_of_the_gale"]

    required_assets = (
        "challenge_button.png",
        "skip_button.png",
        "exit_button.png",
        "depart_button.png",
        "return_06_button.png",
        "return_07_button.png",
        "shuriken_template.png",
        "ad_revive_button.png",
        "empty_slot.png",
    )

    # call_of_the_gale 是場景完全不同的小遊戲，不從 VL 主畫面偵測
    task_scene_anchors = ()

    SHURIKEN_X = 340
    SHURIKEN_Y = 410
    SHURIKEN_DIST = 100
    UPGRADE_X = 800
    UPGRADE_Y = 400
    LEAVE_X = 50
    LEAVE_Y = 50
    ENERGY_ROI = (595, 15, 35, 20)
    SCROLL_ROI = (850, 10, 35, 35)
    ONIGIRI_ROI = (680, 10, 90, 30)
    UPGRADE_COST_ROI = (740, 350, 120, 40)
    AD_REVIVE_ROI = (603, 5, 89, 43)
    AD_REVIVE_THRESHOLD = 0.90

    def _get_ocr_reader(self):
        return get_cached_easyocr_reader(("en",), download_enabled=False)

    def _execute_and_return(self, started: float) -> TaskRunResult:
        # call_of_the_gale 不需要 return to daily，直接結束
        message = self.execute()
        return TaskRunResult(
            task_key=self.spec.key,
            state=TaskState.COMPLETED,
            message=message,
            elapsed_seconds=time.time() - started,
        )

    def _wait_and_click(self, asset_name: str, wait_appear=10, wait_disappear=5, threshold=0.8):
        path = self._asset_path(asset_name)
        appeared = False
        for _ in range(wait_appear):
            screen = self.context.controller.screenshot()
            match = self.context.matcher.match_template(screen, path, threshold=threshold)
            if match:
                appeared = True
                break
            time.sleep(1.0)
            
        if not appeared:
            self._log(f"[Warning] 等待 {asset_name} 出現超時！")
            return False
            
        for _ in range(wait_disappear):
            screen = self.context.controller.screenshot()
            match = self.context.matcher.match_template(screen, path, threshold=threshold)
            if match:
                self._log(f"[Action] 點擊 {asset_name} (信心值: {match.confidence:.2f})")
                self.context.controller.tap(*match.center)
                time.sleep(1.5)
            else:
                self._log(f"[Info] {asset_name} 已消失 (信心值低於門檻)，轉場成功！")
                return True
                
        self._log(f"[Warning] {asset_name} 連續點擊 {wait_disappear} 次仍未消失！")
        return False

    def execute(self) -> str:
        reader = self._get_ocr_reader()

        while True:
            screen = self.context.controller.screenshot()
            scrolls = self.get_scroll_count(screen, reader)
            
            if scrolls == 0:
                self._log("[Info] OCR 辨識卷軸為 0，準備一路退出！")
                self._log("[Action] 點擊左上角「離開」...")
                self.context.controller.tap(self.LEAVE_X, self.LEAVE_Y)
                time.sleep(2.0)
                
                self._log("[Info] 準備銜接點擊「07_返回」...")
                self._wait_and_click("return_07_button.png", wait_appear=10, wait_disappear=5)
                
                self._log("[Info] 退場程序完畢，徹底結束程式！")
                return "call_of_the_gale completed"
            elif scrolls == -1:
                self._log("[Warning] 無法辨識卷軸數量，預設為還有卷軸，繼續執行...")
            else:
                self._log(f"[Info] 進入新一輪，目前剩餘卷軸: {scrolls}")

            self._log("[Info] 呼叫 run_single_round 進行單回合操作...")
            success = self.run_single_round(reader)
            if not success:
                self._log("[Warning] run_single_round 回報失敗，強行進入下一步找跳過...")

            self._log("[Info] 正在等待與處理過場動畫...")
            for _ in range(20):
                screen = self.context.controller.screenshot()
                if self.context.matcher.match_template(screen, self._asset_path("challenge_button.png"), threshold=0.8):
                    break
                match_skip = self.context.matcher.match_template(screen, self._asset_path("skip_button.png"), threshold=0.7, roi=(750, 450, 200, 100))
                if match_skip:
                    self._log(f"[Action] 找到「跳過」按鈕，位置 {match_skip.center}，持續點擊！")
                    self.context.controller.tap(*match_skip.center)
                time.sleep(1.0)
                
            self._log("[Info] 正在等待結算畫面與「繼續挑戰 / 退出」按鈕...")
            for _ in range(30):
                screen = self.context.controller.screenshot()
                
                match_challenge = self.context.matcher.match_template(screen, self._asset_path("challenge_button.png"), threshold=0.8)
                if match_challenge:
                    self._log("[Action] 找到「05_繼續挑戰」按鈕，點擊！")
                    self.context.controller.tap(*match_challenge.center)
                    time.sleep(3.0)
                    break
                    
                match_exit = self.context.matcher.match_template(screen, self._asset_path("exit_button.png"), threshold=0.8)
                if match_exit:
                    self._log("\n[Action] 找到「05_完成挑戰退出」按鈕！")
                    self._wait_and_click("exit_button.png", wait_appear=1, wait_disappear=5)
                    
                    self._log("[Info] 準備銜接點擊遊戲盤面左上角的「返回箭頭」...")
                    self._wait_and_click("return_06_button.png", wait_appear=10, wait_disappear=5)
                    
                    self._log("[Info] 準備銜接點擊「07_返回」...")
                    self._wait_and_click("return_07_button.png", wait_appear=10, wait_disappear=5)
                    
                    self._log("[Info] 退場程序完畢，徹底結束程式！")
                    return "call_of_the_gale completed"
                    
                time.sleep(1.0)
                
            self._log("[Info] 準備進行下一回合...")
            time.sleep(2.0)

    def parse_game_number(self, text):
        text = text.replace(',', '')
        text = text.replace('O', '0').replace('o', '0')
        text = text.replace('l', '1').replace('I', '1')
        
        multiplier = 1.0
        if 'k' in text.lower():
            multiplier = 1000.0
            text = text.lower().replace('k', '')
        elif 'm' in text.lower():
            multiplier = 1000000.0
            text = text.lower().replace('m', '')
            
        try:
            return int(float(text) * multiplier)
        except ValueError:
            return -1

    def get_scroll_count(self, screen, reader):
        x, y, w, h = self.SCROLL_ROI
        crop = screen[y:y+h, x:x+w]
        crop_large = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(crop_large, cv2.COLOR_BGR2GRAY)
        _, bin_img = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)
        results = reader.readtext(bin_img, allowlist='0123456789OoIl')
        if not results:
            return -1
        
        best_text = ""
        best_conf = 0.0
        for bbox, text, conf in results:
            if conf > best_conf:
                best_text = text
                best_conf = float(conf)
                
        return self.parse_game_number(best_text)

    def get_shuriken_count(self, screen, reader):
        x, y, w, h = self.ENERGY_ROI
        crop = screen[y:y+h, x:x+w]
        crop_large = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        results = reader.readtext(crop_large, allowlist='0123456789')
        if not results:
            return -1
        
        best_text = ""
        best_conf = 0.0
        for bbox, text, conf in results:
            if conf > best_conf:
                best_text = text
                best_conf = float(conf)
                
        try:
            return int(best_text)
        except ValueError:
            return -1

    def get_onigiri_count(self, screen, reader):
        x, y, w, h = self.ONIGIRI_ROI
        crop = screen[y:y+h, x:x+w]
        crop_large = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        results = reader.readtext(crop_large, allowlist='0123456789,kKmM.OoIl')
        if not results:
            return -1
        
        best_text = ""
        best_conf = 0.0
        for bbox, text, conf in results:
            if conf > best_conf:
                best_text = text
                best_conf = float(conf)
                
        return self.parse_game_number(best_text)

    def get_upgrade_cost(self, screen, reader):
        x, y, w, h = self.UPGRADE_COST_ROI
        crop = screen[y:y+h, x:x+w]
        crop_large = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        results = reader.readtext(crop_large, allowlist='0123456789,kKmM.OoIl')
        if not results:
            return -1
        
        best_text = ""
        best_conf = 0.0
        for bbox, text, conf in results:
            if conf > best_conf:
                best_text = text
                best_conf = float(conf)
                
        return self.parse_game_number(best_text)

    def shoot_shuriken(self, start_x: int, start_y: int, pull_distance: int = 100):
        direction = random.choice([-1, 1])
        offset_angle_deg = random.uniform(3.0, 5.0) * direction
        angle_deg = 90.0 + offset_angle_deg
        angle_rad = math.radians(angle_deg)
        
        end_x = start_x + int(pull_distance * math.cos(angle_rad))
        end_y = start_y + int(pull_distance * math.sin(angle_rad))
        
        self._log(f"[Action] 發射！ 拖曳起點({start_x}, {start_y}) -> 終點({end_x}, {end_y})")
        self.context.controller.swipe(start_x, start_y, end_x, end_y, duration_ms=500)

    def wait_for_shuriken(self, max_wait=30.0):
        self._log("[Info] 正在等待飛鏢回填就緒...")
        start_time = time.time()
        
        empty_path = self._asset_path("empty_slot.png")
        if not empty_path.exists():
            self._log("[Warning] 無法載入 empty_slot.png，將使用固定等待時間...")
            time.sleep(5.0)
            return

        empty_template = cv2.imdecode(np.fromfile(str(empty_path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if empty_template is None:
            self._log("[Warning] 無法解碼 empty_slot.png，將使用固定等待時間...")
            time.sleep(5.0)
            return

        gray_empty = cv2.cvtColor(empty_template, cv2.COLOR_BGR2GRAY)
        half = 30
        
        while time.time() - start_time < max_wait:
            screen = self.context.controller.screenshot()
            crop_current = screen[self.SHURIKEN_Y-half:self.SHURIKEN_Y+half, self.SHURIKEN_X-half:self.SHURIKEN_X+half]
            gray_current = cv2.cvtColor(crop_current, cv2.COLOR_BGR2GRAY)
            
            res = cv2.matchTemplate(gray_current, gray_empty, cv2.TM_CCOEFF_NORMED)
            match_score = res[0][0]
            
            if match_score < 0.6:
                self._log(f"[Info] 飛鏢已就緒！ (背景相似度降至 {match_score:.3f})")
                return True
                
            time.sleep(0.5)
            
        self._log("[Warning] 等待飛鏢就緒超時 (超過30秒)！")
        return False

    def find_ad_revive_button_once(self, screen):
        path = self._asset_path("ad_revive_button.png")
        if not path.exists():
            return None
        match = self.context.matcher.match_template(
            screen,
            path,
            threshold=self.AD_REVIVE_THRESHOLD,
            roi=self.AD_REVIVE_ROI,
        )
        if match:
            return match

        best = self.context.matcher.best_template_match(screen, path, roi=self.AD_REVIVE_ROI)
        if best:
            self._log(
                "[Debug] 看廣告續命未達門檻 "
                f"best_conf={best.confidence:.3f} threshold={self.AD_REVIVE_THRESHOLD:.2f} "
                f"center={best.center} bbox={best.bbox} roi={self.AD_REVIVE_ROI}"
            )
        else:
            self._log(f"[Debug] 看廣告續命未達門檻，且無法計算最佳信心值 roi={self.AD_REVIVE_ROI}")
        return None

    def wait_for_ad_revive_button(self, timeout=3.0, interval=0.5):
        self._log("[Info] 等待「看廣告續命」按鈕出現。")
        start_time = time.time()
        attempt = 0
        while time.time() - start_time < timeout:
            attempt += 1
            screen = self.context.controller.screenshot()
            match = self.find_ad_revive_button_once(screen)
            if match:
                if attempt > 1:
                    self._log(f"[Info] 第 {attempt} 次檢查找到「看廣告續命」。")
                return match
            time.sleep(interval)
        self._log(f"[Info] {timeout:.1f} 秒內找不到「看廣告續命」按鈕，改走原本升級流程。")
        return None

    def try_ad_revive(self):
        match = self.wait_for_ad_revive_button()
        if not match:
            return False

        self._log(f"[Action] 找到「看廣告續命」按鈕，信心值 {match.confidence:.3f}，先點擊上方 +。")
        if hasattr(self.context.controller, "annotate_next_tap_debug"):
            self.context.controller.annotate_next_tap_debug(
                lines=["call_of_the_gale ad revive +", f"conf={match.confidence:.3f}"],
                boxes=[(*match.bbox, "ad revive +")],
            )
        self.context.controller.tap(*match.center)
        time.sleep(1.0)

        try:
            from ads2.core.runner import ReactiveRunner as AdsReactiveRunner
            ads_runner = AdsReactiveRunner(
                serial=self.context.controller.serial,
                ad_wait=15,
                debug=False,
                profile="call_of_the_gale",
            )
            
            def find_ads2_free_ad_button(screen):
                free_ad_paths = sorted(
                    ads_runner.free_ad_icons_dir.rglob("*.png"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                for path in free_ad_paths:
                    result = ads_runner.matcher.match_template(screen, path, threshold=0.75)
                    if result:
                        return result
                return None
            
            self._log("[Info] 等待免費廣告按鈕出現，再交給 ADS2。")
            start_time = time.time()
            found_free_ad = False
            while time.time() - start_time < 8.0:
                screen = self.context.controller.screenshot()
                if find_ads2_free_ad_button(screen):
                    self._log("[Info] 已確認免費廣告按鈕出現。")
                    found_free_ad = True
                    break
                time.sleep(0.5)
                
            if not found_free_ad:
                self._log("[Warning] 點擊 + 後沒有看到免費廣告按鈕，先不啟動 ADS2。")
                return False

            self._log("[Info] 交給 ADS2 profile: call_of_the_gale，等待免費廣告與恢復 3 飛鏢狀態。")
            ads_runner.run()
            self._log("[Info] ADS2 已偵測到恢復 3 飛鏢，回到疾風射擊流程。")
            time.sleep(1.0)
            return True
        except ImportError:
            self._log("[Warning] 無法載入 ads2 模組，跳過廣告續命")
            return False

    def run_single_round(self, reader):
        consecutive_fails = 0
        
        self._log("[Info] 開場第一發！")
        self.shoot_shuriken(self.SHURIKEN_X, self.SHURIKEN_Y, self.SHURIKEN_DIST)
        time.sleep(1.0)
        self.wait_for_shuriken()
            
        while True:
            screen = self.context.controller.screenshot()
            count = self.get_shuriken_count(screen, reader)
            
            if count == -1:
                self._log("[Warning] 無法辨識飛鏢數量，重試中...")
                consecutive_fails += 1
                if consecutive_fails >= 5:
                    raise TaskFailedError("連續 5 次無法辨識飛鏢數量")
                time.sleep(1.0)
                continue
                
            consecutive_fails = 0
            self._log(f"[Info] 當前飛鏢數量: {count}")
            
            if count > 0:
                self.shoot_shuriken(self.SHURIKEN_X, self.SHURIKEN_Y, self.SHURIKEN_DIST)
                time.sleep(1.0)
                self.wait_for_shuriken()
            elif count == 0:
                self._log("[Info] 飛鏢已用盡 (0)，等待 8 秒讓最後一發飛鏢落地...")
                time.sleep(8.0)
                if self.try_ad_revive():
                    continue
                break

        self._log("[Info] 準備升級：第一次無條件長按「升級」3 秒鐘...")
        self.context.controller.swipe(self.UPGRADE_X, self.UPGRADE_Y, self.UPGRADE_X + 2, self.UPGRADE_Y + 2, duration_ms=3000)
        time.sleep(1.0)

        self._log("[Info] 開始檢查飯糰數量與升級消耗...")
        onigiri_fails = 0
        upgrade_attempts = 0
        
        while True:
            screen = self.context.controller.screenshot()
            onigiri = self.get_onigiri_count(screen, reader)
            cost = self.get_upgrade_cost(screen, reader)
            
            if onigiri == -1 or cost == -1:
                self._log("[Warning] 無法辨識飯糰數量或升級門檻...")
                onigiri_fails += 1
                if onigiri_fails >= 5:
                    raise TaskFailedError("連續 5 次無法辨識飯糰或升級門檻")
                time.sleep(1.0)
                continue
                
            onigiri_fails = 0
            self._log(f"[Info] 當前飯糰: {onigiri}, 升級需要: {cost}")
            
            if onigiri < cost:
                self._log(f"[Info] 飯糰數量 ({onigiri}) 已低於升級門檻 ({cost})，停止升級，準備出發！")
                break
                
            if upgrade_attempts >= 5:
                raise TaskFailedError("已經長按升級多次，但飯糰數量仍無法降至門檻以內")
                
            self._log(f"[Info] 飯糰數量 ({onigiri}) >= 門檻 ({cost})，直接長按「升級」3 秒鐘...")
            self.context.controller.swipe(self.UPGRADE_X, self.UPGRADE_Y, self.UPGRADE_X + 2, self.UPGRADE_Y + 2, duration_ms=3000)
            time.sleep(1.0)
            upgrade_attempts += 1

        self._log("[Info] 準備尋找並點擊「出發」...")
        max_depart_attempts = 20
        depart_success = False
        has_clicked_depart = False
        
        for attempt in range(max_depart_attempts):
            screen = self.context.controller.screenshot()
            match = self.context.matcher.match_template(screen, self._asset_path("depart_button.png"), threshold=0.7)
            if match:
                self._log(f"[Action] 第 {attempt+1} 次發現「出發」按鈕，點擊！")
                self.context.controller.tap(*match.center)
                has_clicked_depart = True
                time.sleep(1.0)
            else:
                if has_clicked_depart:
                    self._log("[Info] 「出發」按鈕已消失，確認成功進入過場畫面！")
                    depart_success = True
                    break
                else:
                    self._log(f"[Warning] 第 {attempt+1} 次嘗試找不到「出發」按鈕（可能正在閃爍或被遮擋），繼續等待...")
                    time.sleep(1.0)

        if not depart_success:
            self._log("[Warning] 點擊出發按鈕多次後，按鈕仍未消失，可能跳轉失敗或卡頓。")
            return False
            
        return True
