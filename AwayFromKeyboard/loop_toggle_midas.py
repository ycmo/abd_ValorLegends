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
from src.adb_controller import DeviceController
from src.vision_matcher import VisionMatcher
from src.scene_detector import SceneDetector
from AwayFromKeyboard.ui_recovery import UIRecovery

def parse_interval_to_seconds(interval_str: str) -> float:
    parts = interval_str.split(':')
    if len(parts) != 3:
        raise ValueError(f"時間格式錯誤 '{interval_str}'，請使用 hh:mm:ss")
    h, m, s = [float(p) for p in parts]
    return h * 3600 + m * 60 + s

def run_route(route_name: str, router_script: Path, recovery: UIRecovery):
    print(f"\n[ToggleLoop] 準備呼叫路由任務: {route_name}")
    cmd = [sys.executable, str(router_script), route_name]
    try:
        result = subprocess.run(cmd, cwd=str(project_root))
        if result.returncode != 0:
            print(f"⚠️ [警告] 路由 '{route_name}' 回傳了錯誤碼 (returncode={result.returncode})，將靜默略過並繼續流程。")
    except Exception as e:
        print(f"⚠️ [警告] 執行路由 '{route_name}' 時發生崩潰: {e}")
        
    print("🔍 路由任務結束，交由 UIRecovery 強制驗證主城狀態...")
    if not recovery.recover_to_main():
        print("⚠️ [系統] 畫面卡死或無法自動回到主城。啟動浴火重生(強制重啟)機制...")
        try:
            # 1. 強制關閉遊戲
            recovery.controller.shell("am force-stop com.ageofeternity.global")
            time.sleep(3)
            # 2. 重新啟動遊戲
            recovery.controller.shell("monkey -p com.ageofeternity.global -c android.intent.category.LAUNCHER 1")
            print("⏳ 遊戲已重啟，等待載入...")
            time.sleep(10) # 給予初始載入時間
            
            # 3. 呼叫封裝好的登入重入機制
            from src.game_entry import reenter_game
            if reenter_game(recovery.controller, recovery.matcher):
                print("✅ 強制重啟並登入成功，已安全重返主城，繼續掛機流程！")
            else:
                print("❌ [錯誤] 重啟後仍無法成功進入主城，徹底終止程式。")
                sys.exit(1)
        except Exception as e:
            print(f"❌ [錯誤] 執行強制重啟時發生異常: {e}")
            sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="AwayFromKeyboard 雙帳號定時切換掛機腳本 (點金手專用版)")
    parser.add_argument("--interval", type=str, default="08:00:00", help="休眠倒數時間 (hh:mm:ss)，預設 08:00:00")
    parser.add_argument("--toggles", type=int, default=1, help="執行幾輪 (Rounds)。預設 1 輪")
    parser.add_argument("--all", action="store_true", help="切換全部 4 個帳號 (使用 next 模式)")
    parser.add_argument("--delay", type=str, default=None, help="首次啟動前的延遲等待時間 (hh:mm:ss)")
    args = parser.parse_args()

    try:
        interval_seconds = parse_interval_to_seconds(args.interval)
        delay_seconds = parse_interval_to_seconds(args.delay) if args.delay else 0
    except ValueError as e:
        print(f"❌ [錯誤] {e}")
        sys.exit(1)
        
    accounts_per_round = 4 if args.all else 2
    switch_cmd = "next" if args.all else "toggle"
    total_runs = accounts_per_round * args.toggles
        
    router_script = current_dir / "integration_task" / "run_router.py"

    print("==================================================")
    print(f"🔄 開始執行定時雙帳號掛機 (Loop Toggle Midas)")
    print(f"⏱️ 設定休眠區間: {args.interval} ({int(interval_seconds)} 秒)")
    print(f"🔄 執行輪數: {args.toggles} 輪，單輪帳號數: {accounts_per_round}")
    print(f"🔄 總執行次數: {total_runs} 次")
    print("==================================================")

    try:
        controller = DeviceController()
        if not controller.connect():
             print("❌ 無法連線至 ADB 裝置")
             sys.exit(1)
        matcher = VisionMatcher()
        detector = SceneDetector(matcher)
        recovery = UIRecovery(controller, matcher, detector)
    except Exception as e:
        print(f"❌ 初始化 UIRecovery 失敗: {e}")
        sys.exit(1)

    try:
        if args.delay:
            wake_time = datetime.now() + timedelta(seconds=delay_seconds)
            print(f"\n⏳ [延遲啟動] 接收到 --delay 指令，將先進行首次休眠: {args.delay} ({int(delay_seconds)} 秒)")
            print(f"⏰ 預計首次喚醒時間 (Local Time): {wake_time.strftime('%Y-%m-%d %H:%M:%S')}")
            time.sleep(delay_seconds)
            
        while True:
            print("\n🌅 系統喚醒，執行一次性特殊檢查...")
            if recovery.handle_remote_login():
                print("✅ 異地登入狀態已排除，準備載入遊戲大廳。")
                recovery.recover_to_main(max_attempts=20) # 排除後需確保回到大廳
                
            print(f"🔄 本次大循環將執行 {args.toggles} 輪，每輪 {accounts_per_round} 個帳號，總計 {total_runs} 次任務。")
            
            for i in range(total_runs):
                if i == 0:
                    print("\n▶️ === 本輪首發任務 (當前帳號) ===")
                else:
                    print(f"\n▶️ === 執行第 {i}/{total_runs-1} 次切換 ({switch_cmd}) ===")
                    print("[ToggleLoop] 執行帳號切換...")
                    print("\n" + "=" * 60)
                    print("🛠️ [Debug] 若腳本卡住，可手動在終端機貼上以下指令重新測試帳號切換：")
                    print(f">>> {sys.executable} -m switch_account.switch_account {switch_cmd}")
                    print("=" * 60 + "\n")
                    try:
                        switch_account(switch_cmd)
                    except Exception as e:
                        print(f"⚠️ [警告] 切換帳號發生錯誤: {e}")
                        
                # 針對當前畫面上的帳號執行任務
                run_route("點金手", router_script, recovery)
            
            # 執行完畢
            print("\n" + "=" * 50)
            next_time = datetime.now() + timedelta(seconds=interval_seconds)
            print(f"✅ 本輪 {args.toggles} 輪 ({total_runs} 次) 帳號任務執行完畢！")
            print(f"💤 進入休眠模式，將休息 {args.interval} ({int(interval_seconds)} 秒)")
            print(f"⏰ 預計下次喚醒時間 (Local Time): {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print("=" * 50 + "\n")
            
            time.sleep(interval_seconds)
            
    except KeyboardInterrupt:
        print("\n🛑 [中止] 接收到手動中斷指令 (Ctrl+C)，已安全退出掛機腳本。")
        sys.exit(0)

if __name__ == "__main__":
    main()
