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

def parse_interval_to_seconds(interval_str: str) -> float:
    parts = interval_str.split(':')
    if len(parts) != 3:
        raise ValueError(f"時間格式錯誤 '{interval_str}'，請使用 hh:mm:ss")
    h, m, s = [float(p) for p in parts]
    return h * 3600 + m * 60 + s

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
    parser = argparse.ArgumentParser(description="AwayFromKeyboard 雙帳號定時切換掛機腳本 (點金手專用版)")
    parser.add_argument("--interval", type=str, default="08:00:00", help="休眠倒數時間 (hh:mm:ss)，預設 08:00:00")
    parser.add_argument("--toggles", type=int, default=2, help="每次大循環要執行的帳號數量與切換次數，預設 2")
    args = parser.parse_args()

    try:
        interval_seconds = parse_interval_to_seconds(args.interval)
    except ValueError as e:
        print(f"❌ [錯誤] {e}")
        sys.exit(1)
        
    router_script = current_dir / "integration_task" / "run_router.py"

    print("==================================================")
    print(f"🔄 開始執行定時雙帳號掛機 (Loop Toggle Midas)")
    print(f"⏱️ 設定休眠區間: {args.interval} ({int(interval_seconds)} 秒)")
    print(f"🔄 循環帳號數量: {args.toggles} 次")
    print("==================================================")

    try:
        while True:
            for i in range(args.toggles):
                print(f"\n▶️ === 開始處理第 {i+1}/{args.toggles} 個帳號 ===")
                
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
            
            # 執行完畢
            print("\n" + "=" * 50)
            next_time = datetime.now() + timedelta(seconds=interval_seconds)
            print(f"✅ 本輪 {args.toggles} 次帳號任務執行完畢！")
            print(f"💤 進入休眠模式，將休息 {args.interval} ({int(interval_seconds)} 秒)")
            print(f"⏰ 預計下次喚醒時間 (Local Time): {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print("=" * 50 + "\n")
            
            time.sleep(interval_seconds)
            
    except KeyboardInterrupt:
        print("\n🛑 [中止] 接收到手動中斷指令 (Ctrl+C)，已安全退出掛機腳本。")
        sys.exit(0)

if __name__ == "__main__":
    main()
