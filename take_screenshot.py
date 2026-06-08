import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.adb_controller import DeviceController
import cv2

if __name__ == "__main__":
    print("📸 正在連接模擬器擷取畫面...")
    controller = DeviceController("127.0.0.1:16384")
    screen = controller.screenshot()
    save_path = Path("manual_screenshot.png")

    # 支援中文路徑的儲存方式
    ok, buf = cv2.imencode(".png", screen)
    if ok:
        save_path.write_bytes(buf.tobytes())
        print(f"✅ 截圖已儲存至目前的資料夾：{save_path.resolve()}")
    else:
        print("❌ 截圖儲存失敗")
