"""
experiments/ad_closer/run_ad_closer.py
======================================
廣告關閉支線實驗 — 獨立入口。

⚠️  此腳本與主線 Valor Legends bot（src/main.py）完全分離，
    不會被主流程呼叫，不會干擾每日任務 / navigation graph。

用途：
  驗證以下核心能力：ADB 截圖、OpenCV template matching、
  座標 tap、timeout 機制、debug screenshot 輸出。

執行方式（從專案根目錄）：
  python experiments/ad_closer/run_ad_closer.py
  python experiments/ad_closer/run_ad_closer.py --debug
  python experiments/ad_closer/run_ad_closer.py \\
      --serial 127.0.0.1:5555 \\
      --initial-wait 30 \\
      --interval 1.0 \\
      --timeout 90 \\
      --threshold 0.82 \\
      --debug

狀態流程：
  INITIAL_WAIT → FIND_CLOSE_OR_SKIP → TAP_CLOSE → DONE
                                                  → FAILED

共用模組（只 import，不修改）：
  src/adb_controller.py
  src/vision_matcher.py
"""

import argparse
import os
import sys
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

import numpy as np

# ── 讓此腳本從專案根目錄或任意位置執行時都能找到 src/ ──────────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from adb_controller import DeviceController, AdbControllerError  # noqa: E402
from vision_matcher import VisionMatcher, MatchResult             # noqa: E402


# ══════════════════════════════════════════════════════════════════
# 設定結構
# ══════════════════════════════════════════════════════════════════

@dataclass
class AdCloserConfig:
    """廣告關閉實驗的所有可調參數。"""
    serial: str = "127.0.0.1:5555"
    # ── 時間 ─────────────────────────────────────────────────────
    initial_wait_seconds: float = 30.0   # INITIAL_WAIT 固定等待（不掃描）
    timeout_seconds: float = 90.0        # 整個流程總 timeout（含 initial_wait）
    interval: float = 1.0                # FIND 階段每次截圖間隔（秒）
    post_tap_wait: float = 2.5           # TAP 後等待遊戲響應（秒）
    # ── 比對 ─────────────────────────────────────────────────────
    threshold: float = 0.82             # Close button matching 信心值閾值
    anchor_threshold: float = 0.80      # Anchor 偵測信心值閾值
    # ── 路徑 ─────────────────────────────────────────────────────
    ad_close_dir: str = ""              # 若空則自動解析為本實驗的 assets/ad_close/
    anchor_path: str = ""              # 若空則自動解析為本實驗的 assets/anchors/game_lobby_anchor.png
    debug: bool = False
    debug_dir: str = ""                # 若空則自動解析為本實驗的 debug/
    # ── 防護 ─────────────────────────────────────────────────────
    max_tap_attempts: int = 5

    def __post_init__(self) -> None:
        """自動填充空路徑為相對本實驗目錄的預設值。"""
        base = _THIS_DIR
        if not self.ad_close_dir:
            self.ad_close_dir = os.path.join(base, "assets", "ad_close")
        if not self.anchor_path:
            self.anchor_path = os.path.join(base, "assets", "anchors", "game_lobby_anchor.png")
        if not self.debug_dir:
            self.debug_dir = os.path.join(base, "debug")


# ══════════════════════════════════════════════════════════════════
# 狀態定義
# ══════════════════════════════════════════════════════════════════

class State(Enum):
    INITIAL_WAIT        = auto()
    FIND_CLOSE_OR_SKIP  = auto()
    TAP_CLOSE           = auto()
    DONE                = auto()
    FAILED              = auto()


# ══════════════════════════════════════════════════════════════════
# 主狀態機
# ══════════════════════════════════════════════════════════════════

SEP = "─" * 62


class AdCloser:
    """廣告關閉支線實驗狀態機。"""

    def __init__(self, config: AdCloserConfig):
        self.cfg = config
        self.device = DeviceController(serial=config.serial)
        self.matcher: Optional[VisionMatcher] = None

        self.state = State.INITIAL_WAIT
        self.start_time: float = 0.0
        self.tap_attempts: int = 0
        self.last_match: Optional[MatchResult] = None
        self.last_screen: Optional[np.ndarray] = None
        # FIND 階段追蹤最佳 confidence（FAILED 時輸出）
        self.best_confidence_seen: float = 0.0
        self.best_template_seen: str = ""

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def run(self) -> State:
        """執行狀態機直到 DONE 或 FAILED，回傳最終狀態。"""
        print(SEP)
        print("[AdCloser] 廣告關閉支線實驗 — 啟動")
        print(f"[AdCloser] 設備          : {self.cfg.serial}")
        print(f"[AdCloser] Initial wait  : {self.cfg.initial_wait_seconds}s "
              f"（前 {self.cfg.initial_wait_seconds:.0f}s 不做 matching）")
        print(f"[AdCloser] Total timeout : {self.cfg.timeout_seconds}s "
              f"（整個流程上限）")
        print(f"[AdCloser] Scan interval : {self.cfg.interval}s  "
              f"Threshold : {self.cfg.threshold}")
        print(f"[AdCloser] Template dir  : {self.cfg.ad_close_dir}")
        print(f"[AdCloser] Debug dir     : {self.cfg.debug_dir}")
        print(SEP)

        if not self._setup():
            self.state = State.FAILED
            return self.state

        self.start_time = time.time()

        while self.state not in (State.DONE, State.FAILED):
            elapsed = time.time() - self.start_time

            if elapsed >= self.cfg.timeout_seconds:
                print(f"\n[AdCloser] ⏰ TIMEOUT: elapsed={elapsed:.1f}s "
                      f"≥ {self.cfg.timeout_seconds}s")
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
        固定等待 initial_wait_seconds 秒。
        不截圖、不 matching、不點擊。
        每 5 秒輸出倒數進度，方便人工觀察。
        """
        wait = self.cfg.initial_wait_seconds
        print(f"\n[INITIAL_WAIT] 開始等待 {wait:.0f}s（廣告播放中，不掃描）")

        remaining = wait
        tick = 5.0

        while remaining > 0:
            # 檢查是否已超出總 timeout
            elapsed_total = time.time() - self.start_time
            if elapsed_total >= self.cfg.timeout_seconds:
                print("[INITIAL_WAIT] 總 timeout 在等待期間已到，提前結束")
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
        每次輸出 elapsed / confidence / template / ROI。
        找到 → 進入 TAP_CLOSE。
        """
        elapsed = time.time() - self.start_time

        screen = self._take_screenshot(f"find_{elapsed:.0f}s")
        if screen is None:
            time.sleep(self.cfg.interval)
            return

        self.last_screen = screen

        result = self.matcher.match_templates(
            screen,
            self.cfg.ad_close_dir,
            debug_tag=f"find_{elapsed:.0f}s",
        )

        if result is not None:
            # 更新最佳 confidence
            if result.confidence > self.best_confidence_seen:
                self.best_confidence_seen = result.confidence
                self.best_template_seen = os.path.basename(result.template_path)

            elapsed_now = time.time() - self.start_time
            print(f"[FIND] ✓ elapsed={elapsed_now:.1f}s  "
                  f"conf={result.confidence:.4f}  "
                  f"template={os.path.basename(result.template_path)}  "
                  f"roi={result.roi_name}  "
                  f"center={result.center}")
            self.last_match = result
            self.state = State.TAP_CLOSE
        else:
            # match_templates 內部已印 miss 行，這裡補 elapsed / best_seen
            elapsed_now = time.time() - self.start_time
            remaining = max(0.0, self.cfg.timeout_seconds - elapsed_now)
            print(f"[FIND] miss  elapsed={elapsed_now:.1f}s  "
                  f"remaining≈{remaining:.0f}s  "
                  f"best_seen={self.best_confidence_seen:.4f}")
            time.sleep(self.cfg.interval)

    # ------------------------------------------------------------------
    # TAP_CLOSE
    # ------------------------------------------------------------------

    def _do_tap(self) -> None:
        """
        對 last_match.center 發送 ADB tap，
        等 post_tap_wait 後確認廣告是否已關閉。
        成功條件：anchor 通過 OR close button 消失。
        """
        if self.last_match is None:
            print("[TAP_CLOSE] last_match 為空，返回 FIND")
            self.state = State.FIND_CLOSE_OR_SKIP
            return

        if self.tap_attempts >= self.cfg.max_tap_attempts:
            print(f"[TAP_CLOSE] 已達最大點擊次數 ({self.cfg.max_tap_attempts})，FAILED")
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

        screen_after = self._take_screenshot("post_tap")
        if screen_after is None:
            self.state = State.FIND_CLOSE_OR_SKIP
            return

        self.last_screen = screen_after

        # ① anchor 確認（若 anchor 圖片存在）
        if os.path.exists(self.cfg.anchor_path):
            passed, anchor_conf = self.matcher.check_anchor(
                screen_after,
                self.cfg.anchor_path,
                threshold=self.cfg.anchor_threshold,
            )
            if passed:
                print(f"[TAP_CLOSE] ✅ anchor 通過，廣告已關閉。"
                      f"(anchor_conf={anchor_conf:.4f})")
                self.state = State.DONE
                return
            print(f"[TAP_CLOSE] anchor 未通過 (conf={anchor_conf:.4f})")
        else:
            print(f"[TAP_CLOSE] anchor 圖片不存在，改用 close button 消失判斷")

        # ② close button 消失確認
        still_has_close = self.matcher.match_templates(
            screen_after,
            self.cfg.ad_close_dir,
            debug_tag="post_tap_check",
        )
        if still_has_close is None:
            print("[TAP_CLOSE] ✅ Close button 消失，判定廣告已關閉。")
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
        進入 FAILED 狀態。
        輸出最後截圖與最高 confidence。
        不執行任何 back / 重啟操作。
        """
        self.state = State.FAILED
        elapsed = time.time() - self.start_time if self.start_time else 0.0
        print(f"\n[AdCloser] ❌ FAILED")
        print(f"  原因             : {reason}")
        print(f"  總 elapsed       : {elapsed:.1f}s")
        print(f"  最高 confidence  : {self.best_confidence_seen:.4f}  "
              f"template={self.best_template_seen or '(none)'}")

        # 儲存 FAILED debug 截圖
        try:
            screen = self.last_screen
            if screen is None:
                screen = self.device.screenshot()
            if self.matcher:
                path = self.matcher.save_failed_screenshot(screen, tag="failed")
                print(f"  Debug 截圖       : {path}")
        except Exception as e:
            print(f"  無法儲存 FAILED 截圖: {e}", file=sys.stderr)

        print("[AdCloser] 不執行任何 back 或重啟操作。請手動檢查模擬器狀態。")

        # ── Template Discovery 提示（僅供開發階段參考） ──
        # 若要分析此截圖並產生候選 template，請執行：
        try:
            _debug_dir = self.cfg.debug_dir if self.matcher else "experiments/ad_closer/debug"
            print("\n[AdCloser] 💡 Template Discovery（開發工具）：")
            print(f"  python tools/template_discovery.py discover-template \\")
            print(f"      --screenshot \"<上面的 debug 截圖路徑>\" \\")
            print(f"      --screen-type ad_endcard \\")
            print(f"      --target close_button \\")
            print(f"      --source-module ad_closer \\")
            print(f"      --best-conf {self.best_confidence_seen:.4f}")
            print(f"  # 然後執行 ai-analyze 或手動 add-candidate")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 連線與初始化
    # ------------------------------------------------------------------

    def _setup(self) -> bool:
        """連線設備、取得解析度、初始化 VisionMatcher。"""
        print("[AdCloser] [1/3] 連線 ADB 設備...")
        if not self.device.connect():
            print(f"[AdCloser] 無法連線到 {self.cfg.serial}", file=sys.stderr)
            return False

        print("[AdCloser] [2/3] 取得設備解析度...")
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

        self.matcher = VisionMatcher(
            screen_width=w,
            screen_height=h,
            threshold=self.cfg.threshold,
            debug=self.cfg.debug,
            debug_dir=self.cfg.debug_dir,
        )

        # Template 狀態報告
        import glob
        if not os.path.isdir(self.cfg.ad_close_dir):
            print(f"[AdCloser] WARNING: ad_close dir 不存在: {self.cfg.ad_close_dir!r}")
            print("[AdCloser]   請參閱 experiments/ad_closer/README.md 了解如何放置 template")
        else:
            templates = glob.glob(os.path.join(self.cfg.ad_close_dir, "*.png"))
            print(f"[AdCloser] Close templates: {len(templates)} 張 — "
                  f"{[os.path.basename(t) for t in templates]}")

        if not os.path.exists(self.cfg.anchor_path):
            print(f"[AdCloser] INFO: anchor 不存在，將改用 close button 消失判斷")

        # 確保輸出目錄存在
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


# ══════════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════════

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_ad_closer.py",
        description=(
            "廣告關閉支線實驗\n"
            "此腳本與主線 Valor Legends bot 完全分離，不干擾每日任務主流程。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  # 使用全部預設值
  python experiments/ad_closer/run_ad_closer.py

  # 指定所有參數
  python experiments/ad_closer/run_ad_closer.py \\
      --serial 127.0.0.1:5555 \\
      --initial-wait 30 \\
      --interval 1.0 \\
      --timeout 90 \\
      --threshold 0.82 \\
      --debug

  # 廣告較短時（縮短等待）
  python experiments/ad_closer/run_ad_closer.py \\
      --initial-wait 15 --timeout 60 --debug
        """,
    )
    parser.add_argument(
        "--serial", type=str, default="127.0.0.1:5555",
        help="ADB 設備 serial（預設: 127.0.0.1:5555）",
    )
    parser.add_argument(
        "--initial-wait", type=float, default=30.0, dest="initial_wait_seconds",
        help="INITIAL_WAIT 固定等待秒數，期間不做 matching（預設: 30）",
    )
    parser.add_argument(
        "--timeout", type=float, default=90.0, dest="timeout_seconds",
        help="整個流程的總 timeout 秒數（含 initial-wait，預設: 90）",
    )
    parser.add_argument(
        "--interval", type=float, default=1.0,
        help="FIND 階段每次截圖間隔秒數（預設: 1.0）",
    )
    parser.add_argument(
        "--threshold", type=float, default=0.82,
        help="Template matching 信心值閾值 0.0~1.0（預設: 0.82）",
    )
    parser.add_argument(
        "--anchor-threshold", type=float, default=0.80, dest="anchor_threshold",
        help="Anchor 偵測信心值閾值（預設: 0.80）",
    )
    parser.add_argument(
        "--ad-close-dir", type=str, default="", dest="ad_close_dir",
        help="Close button template 資料夾（預設: experiments/ad_closer/assets/ad_close/）",
    )
    parser.add_argument(
        "--anchor-path", type=str, default="", dest="anchor_path",
        help="遊戲大廳 anchor 圖片（預設: experiments/ad_closer/assets/anchors/game_lobby_anchor.png）",
    )
    parser.add_argument(
        "--post-tap-wait", type=float, default=2.5, dest="post_tap_wait",
        help="TAP 後等待遊戲響應的秒數（預設: 2.5）",
    )
    parser.add_argument(
        "--max-taps", type=int, default=5, dest="max_tap_attempts",
        help="最大 TAP 嘗試次數（預設: 5）",
    )
    parser.add_argument(
        "--debug", action="store_true", default=False,
        help="輸出帶 bbox 的 debug 截圖到 debug/ 子目錄",
    )
    parser.add_argument(
        "--debug-dir", type=str, default="", dest="debug_dir",
        help="Debug 截圖輸出目錄（預設: experiments/ad_closer/debug/）",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    cfg = AdCloserConfig(
        serial=args.serial,
        initial_wait_seconds=args.initial_wait_seconds,
        timeout_seconds=args.timeout_seconds,
        interval=args.interval,
        threshold=args.threshold,
        anchor_threshold=args.anchor_threshold,
        ad_close_dir=args.ad_close_dir,      # 空字串 → __post_init__ 自動填充
        anchor_path=args.anchor_path,         # 同上
        debug=args.debug,
        debug_dir=args.debug_dir,             # 同上
        post_tap_wait=args.post_tap_wait,
        max_tap_attempts=args.max_tap_attempts,
    )

    closer = AdCloser(cfg)
    final_state = closer.run()

    if final_state == State.DONE:
        print("\n✅ 廣告關閉成功！")
        sys.exit(0)
    else:
        print(f"\n❌ 廣告關閉失敗（{final_state.name}）。"
              f"請查看 {cfg.debug_dir}/ 中的截圖進行排查。")
        sys.exit(2)


if __name__ == "__main__":
    main()
