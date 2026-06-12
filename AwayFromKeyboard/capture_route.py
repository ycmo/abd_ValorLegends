import argparse
import os
import sys
import subprocess
from pathlib import Path

# 強制設定輸出為 UTF-8，以防在 Windows 終端機顯示中文出錯
sys.stdout.reconfigure(encoding='utf-8')

class SystemEnv:
    def prompt_user(self, msg: str) -> str:
        return input(msg)
        
    def run_adb_screencap(self, adb_path: str, serial: str, out_file: Path) -> int:
        with open(out_file, "wb") as f:
            result = subprocess.run(
                [str(adb_path), "-s", serial, "exec-out", "screencap", "-p"],
                stdout=f,
                stderr=subprocess.PIPE
            )
        # 印出 stderr 以供除錯
        if result.returncode != 0 and result.stderr:
            print(result.stderr.decode('utf-8', errors='ignore'))
        return result.returncode

    def open_mspaint(self, file_path: Path):
        try:
            print("🎨 正在開啟 mspaint...")
            subprocess.Popen(["mspaint", str(file_path)])
        except Exception as e:
            print(f"⚠️ [警告] 無法自動開啟小畫家，請手動開啟：{e}")

class RouteCapturer:
    def __init__(self, env=None):
        self.env = env or SystemEnv()
        
    def capture(self, route: str, tag: str, serial: str = "emulator-5554", base_dir: Path = None) -> bool:
        if base_dir is None:
            base_dir = Path(__file__).resolve().parent
            
        screenshots_dir = base_dir / "route_screenshots" / route
        out_file = screenshots_dir / f"{tag}.png"
        
        # 防呆檢查 (Overwrite Warning)
        if out_file.exists():
            print(f"⚠️ [警告] 截圖檔案已存在: {out_file}")
            ans = self.env.prompt_user("是否要覆蓋原本的截圖？(y/n): ").strip().lower()
            if ans != 'y':
                print("已取消截圖。")
                return False
                
        # 建立目錄結構
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # 嘗試優先使用專案內的 adb
            project_root = base_dir.parent
            adb_path = project_root / "tools" / "adb.exe"
            if not adb_path.exists():
                adb_path = "adb" # fallback 到環境變數的 adb
                
            code = self.env.run_adb_screencap(adb_path, serial, out_file)
            if code != 0:
                print("❌ [錯誤] ADB 截圖失敗，請確認模擬器是否已啟動並連線。")
                return False
                
            # 友善提示
            print(f"✅ [成功] 截圖已儲存至：AwayFromKeyboard/route_screenshots/{route}/{tag}.png")
            print(f"💡 [後續動作] 請用小畫家開啟此圖，在目標上畫正紅色空心框覆蓋存檔。未來的 Router 將直接讀取該紅框座標！")
            
            self.env.open_mspaint(out_file)
            return True
            
        except Exception as e:
            print(f"❌ [錯誤] 發生未預期的例外：{e}")
            return False

def main():
    parser = argparse.ArgumentParser(description="AwayFromKeyboard 路由截圖小工具")
    parser.add_argument("--route", required=True, help="任務名稱（例如 midas, call_of_gale），這會作為子目錄名稱")
    parser.add_argument("--tag", required=True, help="截圖步驟名稱（例如 001_進入任務），這會作為檔名")
    parser.add_argument("--serial", default="emulator-5554", help="指定 ADB 設備序號 (預設: emulator-5554)")
    
    args = parser.parse_args()
    
    capturer = RouteCapturer()
    success = capturer.capture(args.route, args.tag, args.serial)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
