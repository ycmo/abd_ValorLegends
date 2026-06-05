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
    parser = argparse.ArgumentParser(description="疾風的呼喚截圖工具")
    parser.add_argument("--serial", default="emulator-5554", help="ADB 設備 (預設: emulator-5554)")
    parser.add_argument("--index", type=int, help="截圖的順序編號 (選填)")
    parser.add_argument("--name", default="", help="截圖的名稱標籤 (選填)")
    args = parser.parse_args()

    # 1. 建立目標資料夾
    captures_dir = os.path.join(_THIS_DIR, "runtime_captures")
    os.makedirs(captures_dir, exist_ok=True)

    # 2. 組合檔名與輸出路徑
    ts = time.strftime("%Y%m%d_%H%M%S")
    parts = []
    if args.index is not None:
        parts.append(f"{args.index:02d}")
    if args.name:
        parts.append(args.name)
    else:
        parts.append(f"raw_{ts}")
        
    filename = "_".join(parts) + ".png"
    output_path = os.path.join(captures_dir, filename)
    
    # 3. 檔案存在保護：如果不是產生帶有 timestamp 的檔名，且檔案已存在，則警告並退出
    if os.path.exists(output_path):
        print(f"[Warning] 截圖檔案已存在，為了避免覆蓋，已取消截圖：{filename}")
        sys.exit(0)

    # 4. 連線並擷圖
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
    
    # 處理 cv2.imwrite 不支援中文路徑的問題
    ok, buf = cv2.imencode(".png", screen)
    if ok:
        with open(output_path, "wb") as f:
            f.write(buf.tobytes())
        print(f"[OK] Screenshot saved to: {output_path}")
    else:
        print(f"[Error] Failed to encode screenshot")
        sys.exit(1)

    # 4. 用小畫家開啟
    print(f"[Info] Opening mspaint...")
    try:
        # 使用 subprocess 在背景開啟 mspaint
        subprocess.Popen(["mspaint", str(output_path)])
    except Exception as e:
        print(f"[Warning] Could not open mspaint: {e}")

if __name__ == "__main__":
    main()
