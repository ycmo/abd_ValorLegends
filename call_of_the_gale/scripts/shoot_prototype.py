import sys
import os
import time
import math
import random
import argparse
from pathlib import Path

# 設定路徑以引入 src/ 底下的 adb_controller
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

try:
    from adb_controller import DeviceController
except ImportError as e:
    import traceback
    traceback.print_exc()
    print(f"錯誤: 載入 adb_controller 失敗: {e}")
    sys.exit(1)

def shoot_shuriken(controller: DeviceController, start_x: int, start_y: int, pull_distance: int = 100):
    """
    模擬發射手裡劍的操作。
    從 (start_x, start_y) 向下拖曳 pull_distance 的距離，並帶有 3~5 度的隨機左右偏移。
    """
    # 隨機決定偏移方向 (-1 為左，1 為右)
    direction = random.choice([-1, 1])
    
    # 隨機產生 3 到 5 度的偏移角度
    offset_angle_deg = random.uniform(3.0, 5.0) * direction
    
    # 基礎向下角度為 90 度 (假設 0 度為正右方，往下為 90 度)
    angle_deg = 90.0 + offset_angle_deg
    angle_rad = math.radians(angle_deg)
    
    # 計算終點座標
    end_x = start_x + int(pull_distance * math.cos(angle_rad))
    end_y = start_y + int(pull_distance * math.sin(angle_rad))
    
    print(f"準備發射！")
    print(f"起點: ({start_x}, {start_y})")
    print(f"終點: ({end_x}, {end_y}) (距離: {pull_distance}, 偏移角度: {offset_angle_deg:.2f} 度)")
    
    # 執行拖曳操作 (可以稍微調整 duration_ms 控制拖曳速度，發射通常需要稍微停頓或直接放開)
    # 這裡使用 500 毫秒的拖曳時間，讓系統能確實判定為拖曳而非點擊
    controller.swipe(start_x, start_y, end_x, end_y, duration_ms=500)
    print("發射完成！")

def main():
    parser = argparse.ArgumentParser(description="疾風的呼喚發射測試")
    parser.add_argument("--serial", default="emulator-5554", help="ADB 設備 (預設: emulator-5554)")
    parser.add_argument("--x", type=int, default=320, help="手裡劍的 X 座標 (請根據實際畫面調整)")
    parser.add_argument("--y", type=int, default=400, help="手裡劍的 Y 座標 (請根據實際畫面調整)")
    parser.add_argument("--dist", type=int, default=100, help="向下的拖曳距離")
    args = parser.parse_args()

    device = DeviceController(serial=args.serial)
    if not device.connect():
        print("[Error] Failed to connect to ADB device.")
        sys.exit(1)

    shoot_shuriken(device, args.x, args.y, args.dist)

if __name__ == "__main__":
    main()
