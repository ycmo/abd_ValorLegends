import os
import sys
import logging
import argparse

# 確保可以 import 根目錄的 src
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.adb_controller import DeviceController
from src.vision_matcher import VisionMatcher
from arcane_forge.arcane_forge_task import ArcaneForgeTask
from arcane_forge.arcane_forge_ascend import ArcaneForgeAscendTask

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Run Arcane Forge Task")
    parser.add_argument("action", choices=['分解', '升星'], help="要執行的奧術熔爐任務")
    parser.add_argument("--debug-actions", action="store_true", help="Enable action debug screenshots")
    parser.add_argument("--debug", action="store_true", help="開啟詳細日誌輸出 (顯示 DEBUG 等級訊息)")
    parser.add_argument("--target-max-stats", type=int, default=2, help="升星上鎖所需的目標最大副屬性數量 (預設: 2)")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("已開啟詳細日誌模式。")

    logger.info("初始化 ADB 控制器與視覺辨識器...")
    ctrl = DeviceController(debug_actions=args.debug_actions)
    vm = VisionMatcher()
    
    if args.action == '分解':
        task = ArcaneForgeTask(ctrl, vm)
    elif args.action == '升星':
        task = ArcaneForgeAscendTask(ctrl, vm, target_max_stats=args.target_max_stats)
        
    task.run()

if __name__ == "__main__":
    main()
