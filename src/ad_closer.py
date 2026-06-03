"""
ad_closer.py  [已移至支線實驗]
-------------------------------
⚠️  此模組已移至：
    experiments/ad_closer/run_ad_closer.py

請直接執行支線入口：
    python experiments/ad_closer/run_ad_closer.py --debug

本檔案保留僅供歷史參考，不再由 src/main.py 呼叫，
也不屬於主線 Valor Legends bot 流程的一部分。
-------------------------------
[原始 ad_closer.py 內容保留如下，僅作參考]
"""

# fmt: off
# ruff: noqa
# mypy: ignore-errors
# ↑ 以上設定讓 linter 忽略此參考存檔

"""
ad_closer.py  [REFERENCE COPY — see experiments/ad_closer/run_ad_closer.py]
------------
廣告關閉狀態機 MVP（v2）。

狀態流程：
  INITIAL_WAIT
    └─ 固定等待 initial_wait_seconds（預設 30s），不做任何截圖或比對
  FIND_CLOSE_OR_SKIP
    └─ 每 interval 秒截圖一次，掃描四角 ROI，
       輸出 elapsed / confidence / template / ROI，
       找到 close/X/skip → TAP_CLOSE
  TAP_CLOSE
    └─ adb tap center → 等待 post_tap_wait 秒 → 確認結果
       ├─ anchor 通過 → DONE
       ├─ close button 消失 → DONE
       └─ close button 仍在 → 更新 last_match，再次 TAP_CLOSE
  DONE   ✅
  FAILED ❌（timeout 超過或 max_tap 超過；輸出 debug 截圖，不 back、不重啟）

Timeout 定義：
  「整個 close-ad 流程的總時間」= INITIAL_WAIT + FIND 階段
  例：--initial-wait 30 --timeout 90 → 前 30s 不掃描，後 60s 掃描，共 90s 上限

使用方式：
  from ad_closer import AdCloser, AdCloserConfig
  cfg = AdCloserConfig(serial="127.0.0.1:5555", debug=True)
  result = AdCloser(cfg).run()
"""

import os
import sys
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

import numpy as np

from adb_controller import DeviceController, AdbControllerError
from vision_matcher import VisionMatcher, MatchResult


# ──────────────────────────────────────────────
# 設定結構
# ──────────────────────────────────────────────

@dataclass
class AdCloserConfig:
    """所有可調整的參數集中於此，方便從 CLI 傳入。"""
    serial: str = "127.0.0.1:5555"
    # ── 時間相關 ─────────────────────────────
    initial_wait_seconds: float = 30.0   # INITIAL_WAIT 固定等待（秒）
    timeout_seconds: float = 90.0        # 整個流程的總 timeout（秒）
    interval: float = 1.0                # FIND 階段每次截圖間隔（秒）
    post_tap_wait: float = 2.5           # TAP 後等待遊戲響應（秒）
    # ── 比對相關 ─────────────────────────────
    threshold: float = 0.82             # Close button matching 信心值閾值
    anchor_threshold: float = 0.80      # Anchor 偵測信心值閾值
    # ── 路徑 ─────────────────────────────────
    ad_close_dir: str = "assets/ad_close"
    anchor_path: str = "assets/anchors/game_lobby_anchor.png"
    debug: bool = False
    debug_dir: str = "screenshots/debug"
    # ── 防護 ─────────────────────────────────
    max_tap_attempts: int = 5            # 最大 TAP 嘗試次數


# ──────────────────────────────────────────────
# 狀態定義
# ──────────────────────────────────────────────

class State(Enum):
    INITIAL_WAIT       = auto()
    FIND_CLOSE_OR_SKIP = auto()
    TAP_CLOSE          = auto()
    DONE               = auto()
    FAILED             = auto()


# ──────────────────────────────────────────────
# 主狀態機
# ──────────────────────────────────────────────

SEP = "─" * 62


class AdCloser:
    """廣告關閉 MVP 狀態機（v2）。"""

    def __init__(self, config: AdCloserConfig):
        self.cfg = config
        self.device = DeviceController(serial=config.serial)
        self.matcher: Optional[VisionMatcher] = None

        self.state = State.INITIAL_WAIT
        self.start_time: float = 0.0       # 整個流程的起始時間
        self.tap_attempts: int = 0
        self.last_match: Optional[MatchResult] = None
        self.last_screen: Optional[np.ndarray] = None
        # FIND 階段結束時的最高 confidence（用於 FAILED 輸出）
        self.best_confidence_seen: float = 0.0
        self.best_template_seen: str = ""

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def run(self) -> State:
        """執行狀態機直到 DONE 或 FAILED，回傳最終狀態。"""
        print(SEP)
        print("[AdCloser] 廣告關閉 MVP v2 啟動")
        print(f"[AdCloser] 設備     : {self.cfg.serial}")
        print(f"[AdCloser] Initial wait : {self.cfg.initial_wait_seconds}s  "
              f"(前 {self.cfg.initial_wait_seconds}s 不做 matching)")
        print(f"[AdCloser] Timeout  : {self.cfg.timeout_seconds}s  "
              f"(整個流程總上限)")
        print(f"[AdCloser] Interval : {self.cfg.interval}s  "
              f"Threshold : {self.cfg.threshold}")
        print(SEP)

        # 步驟 1：連線並初始化
        if not self._setup():
            self.state = State.FAILED
            return self.state

        self.start_time = time.time()

        # 步驟 2：狀態主循環
        while self.state not in (State.DONE, State.FAILED):
            elapsed = time.time() - self.start_time

            if elapsed >= self.cfg.timeout_seconds:
                print(f"\n[AdCloser] ⏰ TIMEOUT: 已過 {elapsed:.1f}s，"
                      f"超過總上限 {self.cfg.timeout_seconds}s")
                self._on_failed("TIMEOUT")
                break

            try:
                if self.state == State.INITIAL_WAIT:
                    self._do_initial_wait()
                elif self.state == State.FIND_CLOSE_OR_SKIP:
                    self._do_find()
                elif self.state == State.TAP_CLOSE:
                    self._do_tap()
            except AdbControllerError as e:
                print(f"[AdCloser] ADB 錯誤: {e}", file=sys.stderr)
                self._on_failed(f"ADB_ERROR: {e}")
                break
            except Exception as e:
                print(f"[AdCloser] 未預期錯誤: {e}", file=sys.stderr)
                import traceback; traceback.print_exc()
                self._on_failed(f"UNEXPECTED_ERROR: {e}")
                break

        print(f"\n{SEP}")
        print(f"[AdCloser] 最終狀態 : {self.state.name}")
        if self.state == State.DONE:
            elapsed = time.time() - self.start_time
            print(f"[AdCloser] 完成耗時 : {elapsed:.1f}s")
        print(SEP)
        return self.state

    # ------------------------------------------------------------------
    # INITIAL_WAIT
    # ------------------------------------------------------------------

    def _do_initial_wait(self) -> None:
        """
        固定等待 initial_wait_seconds 秒，不做任何截圖或 template matching。
        每 5 秒輸出一次倒數提示，方便觀察。
        """
        wait = self.cfg.initial_wait_seconds
        print(f"\n[INITIAL_WAIT] 開始等待 {wait:.0f}s（廣告播放中，不掃描）")

        remaining = wait
        tick = 5.0  # 每 5 秒印一次進度

        while remaining > 0:
            # 不要超過總 timeout
            elapsed_total = time.time() - self.start_time
            if elapsed_total >= self.cfg.timeout_seconds:
                print("[INITIAL_WAIT] 總 timeout 在等待期間已到，提前進入 FAILED")
                self._on_failed("TIMEOUT_DURING_INITIAL_WAIT")
                return

            sleep_chunk = min(tick, remaining)
            time.sleep(sleep_chunk)
            remaining -= sleep_chunk

            elapsed_total = time.time() - self.start_time
            if remaining > 0:
                print(f"[INITIAL_WAIT] 已等 {wait - remaining:.0f}s / {wait:.0f}s "
                      f"(總 elapsed: {elapsed_total:.1f}s)")

        elapsed_total = time.time() - self.start_time
        print(f"[INITIAL_WAIT] ✓ 等待完成 (總 elapsed: {elapsed_total:.1f}s) "
              f"→ 進入 FIND_CLOSE_OR_SKIP")
        self.state = State.FIND_CLOSE_OR_SKIP

    # ------------------------------------------------------------------
    # FIND_CLOSE_OR_SKIP
    # ------------------------------------------------------------------

    def _do_find(self) -> None:
        """
        每 interval 秒截圖一次，掃描四角 ROI。
        每次輸出：elapsed / confidence / template / ROI。
        找到 close/X/skip → 進入 TAP_CLOSE。
        """
        elapsed = time.time() - self.start_time

        screen = self._take_screenshot("find")
        if screen is None:
            # 擷圖失敗，等下一輪
            time.sleep(self.cfg.interval)
            return

        self.last_screen = screen

        result = self.matcher.match_templates(
            screen,
            self.cfg.ad_close_dir,
            debug_tag=f"find_{elapsed:.0f}s",
        )

        # 更新全域最佳 confidence（用於 FAILED 時輸出）
        if result is not None and result.confidence > self.best_confidence_seen:
            self.best_confidence_seen = result.confidence
            self.best_template_seen = os.path.basename(result.template_path)
        elif result is None:
            # match_templates 內部已印出 miss 行，這裡補 elapsed
            elapsed_now = time.time() - self.start_time
            remaining = max(0.0, self.cfg.timeout_seconds - elapsed_now)
            print(f"[FIND] elapsed={elapsed_now:.1f}s  "
                  f"remaining≈{remaining:.0f}s  "
                  f"best_seen={self.best_confidence_seen:.4f}")

        if result is not None:
            self.last_match = result
            elapsed_now = time.time() - self.start_time
            print(f"[FIND] ✓ 找到目標！elapsed={elapsed_now:.1f}s  "
                  f"conf={result.confidence:.4f}  "
                  f"template={os.path.basename(result.template_path)}  "
                  f"roi={result.roi_name}  "
                  f"center={result.center}")
            self.state = State.TAP_CLOSE
            return

        # 未找到，等待下一輪
        time.sleep(self.cfg.interval)

    # ------------------------------------------------------------------
    # TAP_CLOSE
    # ------------------------------------------------------------------

    def _do_tap(self) -> None:
        """
        對 last_match.center 發送 ADB tap，等待後確認是否回到遊戲。
        """
        if self.last_match is None:
            print("[TAP_CLOSE] last_match 為空，返回 FIND")
            self.state = State.FIND_CLOSE_OR_SKIP
            return

        if self.tap_attempts >= self.cfg.max_tap_attempts:
            print(f"[TAP_CLOSE] 已達最大點擊次數 ({self.cfg.max_tap_attempts})，判定 FAILED")
            self._on_failed("MAX_TAP_ATTEMPTS_EXCEEDED")
            return

        cx, cy = self.last_match.center
        self.tap_attempts += 1
        elapsed_now = time.time() - self.start_time
        print(f"\n[TAP_CLOSE] TAP #{self.tap_attempts}  "
              f"座標=({cx}, {cy})  "
              f"template={os.path.basename(self.last_match.template_path)}  "
              f"conf={self.last_match.confidence:.4f}  "
              f"elapsed={elapsed_now:.1f}s")

        self.device.tap(cx, cy)
        time.sleep(self.cfg.post_tap_wait)

        # 擷圖確認結果
        screen_after = self._take_screenshot("post_tap")
        if screen_after is None:
            # 擷圖失敗，暫時返回 FIND 繼續
            self.state = State.FIND_CLOSE_OR_SKIP
            return

        self.last_screen = screen_after

        # ① 嘗試 anchor 確認（若 anchor 圖片存在）
        if os.path.exists(self.cfg.anchor_path):
            passed, anchor_conf = self.matcher.check_anchor(
                screen_after,
                self.cfg.anchor_path,
                threshold=self.cfg.anchor_threshold,
            )
            if passed:
                print(f"[TAP_CLOSE] ✅ 偵測到遊戲 anchor，廣告已關閉。"
                      f"(anchor_conf={anchor_conf:.4f})")
                if self.cfg.debug:
                    self.matcher.save_debug_image(
                        screen_after,
                        self.last_match,
                        tag="done_anchor",
                    )
                self.state = State.DONE
                return
            else:
                print(f"[TAP_CLOSE] anchor 未通過 (conf={anchor_conf:.4f})，繼續確認...")
        else:
            print(f"[TAP_CLOSE] anchor 圖片不存在，改用 close button 消失判斷")

        # ② 檢查 close button 是否仍在
        still_has_close = self.matcher.match_templates(
            screen_after,
            self.cfg.ad_close_dir,
            debug_tag="post_tap_check",
        )

        if still_has_close is None:
            print("[TAP_CLOSE] ✅ Close button 已消失，判定廣告關閉。")
            self.state = State.DONE
        else:
            print(f"[TAP_CLOSE] Close button 仍在 "
                  f"(conf={still_has_close.confidence:.4f})，更新目標繼續嘗試...")
            self.last_match = still_has_close
            self.state = State.TAP_CLOSE

    # ------------------------------------------------------------------
    # FAILED 處理
    # ------------------------------------------------------------------

    def _on_failed(self, reason: str) -> None:
        """
        進入 FAILED：輸出最後截圖與最高 confidence，
        不發送任何 back / 重啟指令。
        """
        self.state = State.FAILED
        elapsed = time.time() - self.start_time if self.start_time else 0.0
        print(f"\n[AdCloser] ❌ FAILED")
        print(f"  原因          : {reason}")
        print(f"  總 elapsed    : {elapsed:.1f}s")
        print(f"  最高 confidence : {self.best_confidence_seen:.4f}  "
              f"template={self.best_template_seen or '(none)'}")

        # 儲存 FAILED 截圖
        try:
            screen = self.last_screen
            if screen is None:
                screen = self.device.screenshot()
            path = self.matcher.save_failed_screenshot(screen, tag="failed")
            print(f"  Debug 截圖    : {path}")
        except Exception as e:
            print(f"  無法儲存 FAILED 截圖: {e}", file=sys.stderr)

        print("[AdCloser] 不執行任何 back 或重啟操作。")

    # ------------------------------------------------------------------
    # 連線與初始化
    # ------------------------------------------------------------------

    def _setup(self) -> bool:
        """連線設備、取得解析度、初始化 VisionMatcher。"""
        print("[AdCloser] [1/3] 連線 ADB 設備...")
        if not self.device.connect():
            print(f"[AdCloser] 無法連線到 {self.cfg.serial}", file=sys.stderr)
            return False

        print("[AdCloser] [2/3] 取得設備解析度與密度...")
        try:
            w, h = self.device.get_screen_size()
            dpi = self.device.get_screen_density()
            print(f"[AdCloser] wm size={w}x{h}  wm density={dpi}")
        except AdbControllerError as e:
            print(f"[AdCloser] 無法取得設備資訊: {e}", file=sys.stderr)
            return False

        print("[AdCloser] [3/3] 驗證擷圖功能...")
        try:
            test_screen = self.device.screenshot()
            sh, sw = test_screen.shape[:2]
            print(f"[AdCloser] Screenshot OK — shape={sw}x{sh}px")
            if sw != w or sh != h:
                print(f"[AdCloser] WARNING: screenshot {sw}x{sh} ≠ wm {w}x{h}，"
                      "使用截圖實際解析度")
            w, h = sw, sh
        except AdbControllerError as e:
            print(f"[AdCloser] 擷圖失敗: {e}", file=sys.stderr)
            return False

        # 初始化 VisionMatcher
        self.matcher = VisionMatcher(
            screen_width=w,
            screen_height=h,
            threshold=self.cfg.threshold,
            debug=self.cfg.debug,
            debug_dir=self.cfg.debug_dir,
        )

        # Template 資料夾狀態
        import glob
        if not os.path.isdir(self.cfg.ad_close_dir):
            print(f"[AdCloser] WARNING: ad_close 資料夾不存在: {self.cfg.ad_close_dir!r}")
        else:
            templates = glob.glob(os.path.join(self.cfg.ad_close_dir, "*.png"))
            print(f"[AdCloser] Close templates: {len(templates)} 張 → "
                  f"{[os.path.basename(t) for t in templates]}")

        if not os.path.exists(self.cfg.anchor_path):
            print(f"[AdCloser] INFO: anchor 不存在 ({self.cfg.anchor_path})，"
                  "將改用 close button 消失判斷廣告是否關閉")

        # 確保輸出目錄存在
        os.makedirs("screenshots", exist_ok=True)
        os.makedirs(self.cfg.debug_dir, exist_ok=True)

        print("[AdCloser] 初始化完成 ✓")
        return True

    # ------------------------------------------------------------------
    # 擷圖工具
    # ------------------------------------------------------------------

    def _take_screenshot(self, tag: str = "shot") -> Optional[np.ndarray]:
        """擷圖並回傳 ndarray；失敗時回傳 None（不 raise）。"""
        try:
            screen = self.device.screenshot()
            if self.cfg.debug:
                import cv2
                ts = time.strftime("%H%M%S")
                path = os.path.join(self.cfg.debug_dir, f"raw_{tag}_{ts}.png")
                cv2.imwrite(path, screen)
            return screen
        except AdbControllerError as e:
            print(f"[AdCloser] 擷圖失敗 ({tag}): {e}", file=sys.stderr)
            return None
