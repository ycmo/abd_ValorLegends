import time
import json
import subprocess
import sys
from pathlib import Path

# 將專案根目錄加入 sys.path 以便 import
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adb_controller import DeviceController
from src.vision_matcher import VisionMatcher
from src.scene_detector import SceneDetector
from switch_account.switch_account import switch_account
from AwayFromKeyboard.ui_recovery import UIRecovery

CONFIG_PATH = Path(__file__).parent / "config.json"

def load_config():
    if not CONFIG_PATH.exists():
        default_config = {
            "loop_accounts": [],
            "sleep_minutes_between_loops": 2
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=4, ensure_ascii=False)
        print(f"⚠️ 找不到設定檔，已建立預設設定檔於: {CONFIG_PATH}")
        print("請填入 loop_accounts (對應 switch_account 的帳號名稱) 後再執行。")
        sys.exit(1)
        
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def run_midas():
    print("\n💰 開始執行點金手任務...")
    # 使用 subprocess 呼叫主程式的 Midas，保持環境乾淨且不互相干擾狀態
    python_exe = sys.executable
    result = subprocess.run(
        [python_exe, "-m", "src.main", "run-task", "midas"],
        cwd=str(PROJECT_ROOT)
    )
    if result.returncode == 0:
        print("✅ 點金手任務執行腳本結束。")
    else:
        print(f"⚠️ 點金手任務可能發生錯誤 (returncode: {result.returncode})")

def main():
    config = load_config()
    accounts = config.get("loop_accounts", [])
    sleep_minutes = config.get("sleep_minutes_between_loops", 2)
    
    if not accounts:
        print("❌ 設定檔中的 loop_accounts 為空，請先填寫要循環的帳號！")
        print("例如: [\"account1\", \"account2\"]")
        sys.exit(1)

    print(f"🚀 AwayFromKeyboard 掛機排程啟動")
    print(f"📋 準備循環的帳號: {', '.join(accounts)}")
    print(f"⏱️ 每次完整循環後休眠: {sleep_minutes} 分鐘\n")

    controller = DeviceController()
    if not controller.connect():
        print("❌ 無法連線至 ADB 裝置")
        sys.exit(1)
        
    matcher = VisionMatcher()
    detector = SceneDetector(matcher)
    recovery = UIRecovery(controller, matcher, detector)

    while True:
        for i, account in enumerate(accounts):
            print(f"\n{'='*40}")
            print(f"🔄 開始處理帳號 [{i+1}/{len(accounts)}]: {account}")
            print(f"{'='*40}")
            
            # 1. 回到主城 (確保狀態正確)
            print("\n[步驟 1] 確保當前在主城畫面...")
            if not recovery.recover_to_main():
                print("⚠️ 無法確認主城狀態，為安全起見跳過此帳號的任務。")
                continue
                
            # 2. 執行點金手
            run_midas()
            
            # 3. 切換到下一個帳號 (若為最後一個帳號，則切換回第一個帳號)
            next_idx = (i + 1) % len(accounts)
            next_account = accounts[next_idx]
            
            print(f"\n[步驟 2] 準備切換至下一個帳號: {next_account}")
            switch_account(next_account)
            
            # 切換帳號後等待遊戲載入
            print("\n⏳ 帳號切換完畢，等待 15 秒讓遊戲載入首頁...")
            time.sleep(15)
            
            # 切換完帳號後，排除登入彈窗並回到主城，準備下一次迴圈或休眠
            print("\n[步驟 3] 處理登入彈窗，確認進入主城...")
            recovery.recover_to_main(max_attempts=20)
            
        print(f"\n{'='*40}")
        print(f"💤 所有帳號循環完畢，開始休眠 {sleep_minutes} 分鐘...")
        print(f"{'='*40}")
        time.sleep(sleep_minutes * 60)

if __name__ == "__main__":
    main()
