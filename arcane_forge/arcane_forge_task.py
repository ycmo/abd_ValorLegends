import os
import sys

# 通用根目錄解析：自動定位專案根目錄並加入系統路徑
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

import logging
import time
from pathlib import Path

from src.adb_controller import DeviceController
from src.config import EXPECTED_SCREEN_SIZE
from src.vision_matcher import VisionMatcher

logger = logging.getLogger(__name__)

class ArcaneForgeTask:
    """
    奧術熔爐 (Arcane Forge) 獨立執行任務
    """
    def __init__(self, ctrl: DeviceController, vm: VisionMatcher):
        self.ctrl = ctrl
        self.vm = vm

        # 預設 Template 路徑
        self.asset_dir = Path("arcane_forge/assets")
        self.title_tpl = self.asset_dir / "arcane_forge_title.png" # 暫無
        self.quick_put_tpl = self.asset_dir / "quick_put_btn.png"
        self.deconstruct_tpl = self.asset_dir / "deconstruct_btn.png"
        self.obtain_popup_tpl = self.asset_dir / "obtain_items_popup.png"
        self.back_tpl = self.asset_dir / "back_btn.png" # 暫無

    def run(self):
        """
        執行奧術熔爐任務的主邏輯
        """
        logger.info("開始執行奧術熔爐 (Arcane Forge) 任務...")

        screen = self.ctrl.screenshot()
        if self.title_tpl.exists():
            title_res = self.vm.match_template(screen, self.title_tpl)
            if not title_res:
                logger.error("畫面特徵不符：未找到奧術熔爐/分解標題，防呆中斷")
                return False
            logger.info("確認位於奧術熔爐，開始分解循環...")
        else:
            logger.warning("缺乏標題 Template，跳過防呆確認，直接開始分解循環...")

        loop_count = 1
        while True:
            logger.info(f"--- 分解循環第 {loop_count} 次 ---")
            screen = self.ctrl.screenshot()

            # 點擊「自動裝填」
            quick_put_res = self.vm.match_template(screen, self.quick_put_tpl)
            if not quick_put_res:
                logger.info("未找到「自動裝填」按鈕，可能已無英雄可分解或畫面異常")
                break

            logger.info("點擊「自動裝填」")
            self.ctrl.tap(quick_put_res.x, quick_put_res.y)
            time.sleep(1.0)

            # 判斷「分解」按鈕是否可點擊 (如果按鈕反灰，check_brightness=True 會濾除)
            screen = self.ctrl.screenshot()
            deconstruct_res = self.vm.match_template(screen, self.deconstruct_tpl)
            if not deconstruct_res:
                logger.info("「分解」按鈕無法點擊（無英雄放入），結束分解循環")
                break

            logger.info("點擊「分解」")
            self.ctrl.tap(deconstruct_res.x, deconstruct_res.y)

            # 判斷是否有「獲得道具」彈窗（需等待動畫，加入 polling）
            logger.info("等待「獲得道具」彈窗出現...")
            popup_res = None
            for _ in range(20):
                screen = self.ctrl.screenshot()
                popup_res = self.vm.match_template(screen, self.obtain_popup_tpl)
                if popup_res:
                    break
                time.sleep(1.0)

            if not popup_res:
                logger.info("點擊分解後等待 20 秒未出現「獲得道具」彈窗，視為結束")
                break

            logger.info("點擊空白處關閉「獲得道具」彈窗")
            # 點擊畫面最上方安全區域 (以 960x540 為例，480, 50 為上方置中)
            self.ctrl.tap(480, 50)
            time.sleep(1.0)
            loop_count += 1

        # 分解完畢後，點擊左上返回箭頭退出
        logger.info("任務結束，嘗試退出奧術熔爐...")
        if self.back_tpl.exists():
            screen = self.ctrl.screenshot()
            back_res = self.vm.match_template(screen, self.back_tpl)
            if back_res:
                self.ctrl.tap(back_res.x, back_res.y)
            else:
                logger.warning("找不到返回鍵 Template，停止自動退出，請人工接手")
        else:
            logger.warning("找不到返回鍵 Template，停止自動退出，請人工接手")

        return True


if __name__ == "__main__":
    import argparse
    from src.adb_controller import DeviceController
    from src.vision_matcher import VisionMatcher

    parser = argparse.ArgumentParser(description="獨立執行奧術熔爐-分解任務 (開發測試用)")
    parser.add_argument("--debug-actions", action="store_true", help="開啟截圖除錯模式")
    parser.add_argument("--debug", action="store_true", help="開啟詳細日誌輸出")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s')
    else:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

    ctrl = DeviceController(debug_actions=args.debug_actions)
    if not ctrl.connect():
        raise SystemExit("Cannot connect to ADB device")
    ctrl.ensure_screen_size(EXPECTED_SCREEN_SIZE)
    vm = VisionMatcher()

    task = ArcaneForgeTask(ctrl, vm)
    task.run()

    from AwayFromKeyboard.discord_notify import notify_status
    notify_status("奧術熔爐", "分解任務已結束")
