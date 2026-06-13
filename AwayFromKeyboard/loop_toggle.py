import sys
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

# 強制設定輸出為 UTF-8，以防在 Windows 終端機顯示中文出錯
sys.stdout.reconfigure(encoding='utf-8')

# 確保專案根目錄在 sys.path 中
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from switch_account.switch_account import switch_account

def run_route(route_name: str, router_script: Path):
    print(f"\n[ToggleLoop] 準備呼叫路由任務: {route_name}")
    cmd = [sys.executable, str(router_script), route_name]
    try:
        result = subprocess.run(cmd, cwd=str(project_root))
        if result.returncode != 0:
            print(f"⚠️ [警告] 路由 '{route_name}' 回傳了錯誤碼 (returncode={result.returncode})，將靜默略過並繼續流程。")
    except Exception as e:
        print(f"⚠️ [警告] 執行路由 '{route_name}' 時發生崩潰: {e}")

def main():
    parser = argparse.ArgumentParser(description="AwayFromKeyboard 雙帳號定時切換掛機腳本")
    parser.add_argument("--interval", type=float, default=8.0, help="休眠倒數時間 (小時)，預設 8.0")
    args = parser.parse_args()

    interval_seconds = args.interval * 3600
    router_script = current_dir / "integration_task" / "run_router.py"

    print("==================================================")
    print(f"🔄 開始執行定時雙帳號掛機 (Loop Toggle)")
    print(f"⏱️ 設定休眠區間: {args.interval} 小時")
    print("==================================================")

    try:
        while True:
            for i in range(2):
                print(f"\n▶️ === 開始處理第 {i+1}/2 個帳號 ===")
                
                # a. 防呆路由：異地登入
                run_route("異地登入", router_script)
                
                # b. 主要任務：點金手
                run_route("點金手", router_script)
                
                # c. 切換帳號
                print("\n[ToggleLoop] 執行帳號切換 (toggle)...")
                try:
                    switch_account("toggle")
                except Exception as e:
                    print(f"⚠️ [警告] 切換帳號時發生錯誤: {e}，仍會繼續流程。")
            
            # 兩次執行後，帳號剛好切回原點
            print("\n" + "=" * 50)
            next_time = datetime.now() + timedelta(seconds=interval_seconds)
            print("✅ 本輪雙帳號任務執行完畢！")
            print(f"💤 進入休眠模式，預計下次喚醒時間 (Local Time): {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print("=" * 50 + "\n")
            
            time.sleep(interval_seconds)
            
    except KeyboardInterrupt:
        print("\n🛑 [中止] 接收到手動中斷指令 (Ctrl+C)，已安全退出掛機腳本。")
        sys.exit(0)

if __name__ == "__main__":
    main()
