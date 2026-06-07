import os
import time
import subprocess
from pathlib import Path

def main():
    # 設定路徑
    base_dir = Path(__file__).parent
    comm_dir = base_dir / "assets" / "2_communication"
    comm_dir.mkdir(parents=True, exist_ok=True)
    
    # 產生時間戳記檔名
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"manual_capture_{timestamp}.png"
    filepath = comm_dir / filename
    
    print("正在透過 ADB 擷取模擬器畫面...")
    
    # 執行 ADB 截圖
    try:
        # 使用 exec-out 避免 \r\n 換行符號損壞二進位圖片檔
        result = subprocess.run(
            ["adb", "exec-out", "screencap", "-p"], 
            capture_output=True, 
            check=True
        )
        
        # 寫入檔案
        with open(filepath, "wb") as f:
            f.write(result.stdout)
            
        print(f"\n✅ 截圖成功！已儲存至: {filepath}")
        
    except Exception as e:
        print(f"\n❌ 截圖失敗！請確認模擬器是否已啟動，且 ADB 連線正常。")
        print(f"錯誤訊息: {e}")
        return

    # 開啟小畫家
    print("正在為您開啟小畫家...")
    print("--------------------------------------------------")
    print("【操作指引】")
    print("1. 請在小畫家中使用「矩形」工具，選擇「純色/無填滿」，並選用「紅色」。")
    print("2. 在你想教系統辨識的按鈕上，畫上精準的紅色空心矩形。")
    print("3. 畫完後直接按 Ctrl + S 存檔，然後關閉小畫家。")
    print("4. 若要裁切，請執行：python auto_crop_v5.py")
    print("--------------------------------------------------")
    
    try:
        # 在背景開啟 mspaint
        subprocess.Popen(["mspaint", str(filepath)])
    except Exception as e:
        print(f"無法自動開啟小畫家，請手動開啟檔案。錯誤: {e}")

if __name__ == "__main__":
    main()
