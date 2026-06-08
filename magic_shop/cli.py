import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
from src.adb_controller import DeviceController
from src.vision_matcher import VisionMatcher
from src.scene_detector import SceneDetector
from src.daily_task_finder import DailyTaskFinder
from src.navigator import Navigator
from src.battle_handler import BattleHandler
from src.task_runner import TaskContext
from src.config import DEFAULT_SERIAL
from magic_shop.magic_shop_task import MagicShopTask

def main():
    parser = argparse.ArgumentParser(description="Test Magic Shop")
    parser.add_argument("--debug", action="store_true", help="Enable action debugging")
    parser.add_argument("--dry-run", action="store_true", help="Only recognize items, do not click")
    args = parser.parse_args()

    if args.debug:
        os.environ["VL_DEBUG_ACTIONS"] = "1"
        print("🛠️ 已啟用 Debug 模式：動作截圖將存放在 captures/action_debug/ 目錄下")

    print("=======================================")
    print("  魔法商店自動化 - 獨立測試腳本")
    print("=======================================")
    
    # 初始化 ADB 與控制器
    controller = DeviceController(DEFAULT_SERIAL)
    if not controller.connect():
        print(f"❌ 無法連接到 ADB 設備 ({DEFAULT_SERIAL})！請確認模擬器是否開啟。")
        return
        
    print("✅ ADB 設備連線成功！")
    
    # 初始化所有需要的元件
    matcher = VisionMatcher()
    detector = SceneDetector(matcher)
    finder = DailyTaskFinder(controller, matcher)
    navigator = Navigator(controller, matcher, detector, finder)
    battle = BattleHandler(controller, matcher, detector)
    
    # 建立 Context
    context = TaskContext(
        controller=controller,
        matcher=matcher,
        detector=detector,
        finder=finder,
        navigator=navigator,
        battle=battle
    )
    
    # 實例化並執行魔法商店任務
    task = MagicShopTask(context)
    
    print("🚀 開始執行魔法商店邏輯...")
    try:
        result_msg = task.execute(dry_run=args.dry_run)
        print(f"✅ 任務完成訊息: {result_msg}")
    except Exception as e:
        print(f"❌ 任務執行過程中發生錯誤: {e}")

if __name__ == "__main__":
    main()
