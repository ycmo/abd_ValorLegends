import os
import sys
import time
import cv2
import subprocess
import argparse

# 設定路徑以引入 src/ 底下的 adb_controller
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, ".."))
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

def main():
    parser = argparse.ArgumentParser(description="一鍵廣告截圖工具")
    parser.add_argument("--serial", default="emulator-5554", help="ADB 設備 (預設: emulator-5554)")
    parser.add_argument("--tag", default="", help="截圖的標籤名稱 (選填)")
    args = parser.parse_args()

    # 1. 建立目標資料夾
    captures_dir = os.path.join(_THIS_DIR, "captures")
    os.makedirs(captures_dir, exist_ok=True)

    # 2. 連線並擷圖
    print(f"[Info] Connecting to {args.serial} and capturing screen...")
    device = DeviceController(serial=args.serial)
    if not device.connect():
        print("[Error] Failed to connect to ADB device.")
        sys.exit(1)

    try:
        screen = device.screenshot()
    except Exception as e:
        print(f"[Error] Failed to capture: {e}")
        sys.exit(1)

    # 3. 儲存檔案
    ts = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{args.tag}_{ts}.png" if args.tag else f"raw_{ts}.png"
    output_path = os.path.join(captures_dir, filename)
    
    cv2.imwrite(output_path, screen)
    print(f"[OK] Screenshot saved to: {output_path}")

    # 4. 用小畫家開啟
    print(f"[Info] Opening mspaint...")
    try:
        # 使用 subprocess 在背景開啟 mspaint
        subprocess.Popen(["mspaint", str(output_path)])
    except Exception as e:
        print(f"[Warning] Could not open mspaint: {e}")

if __name__ == "__main__":
    main()
