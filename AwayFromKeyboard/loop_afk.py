import time
import sys
import argparse
import traceback
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

# 加入專案目錄以利匯入 switch_account
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from switch_account.switch_account import switch_account, ACCOUNTS
from src.adb_controller import DeviceController
from src.vision_matcher import VisionMatcher
from src.scene_detector import SceneDetector
from AwayFromKeyboard.ui_recovery import UIRecovery

# 強制設定輸出為 UTF-8，以防在 Windows 終端機顯示中文出錯
sys.stdout.reconfigure(encoding='utf-8')

def parse_delay_to_seconds(delay_str: str) -> float:
    parts = delay_str.split(':')
    if len(parts) != 3:
        raise ValueError(f"時間格式錯誤 '{delay_str}'，請使用 hh:mm:ss")
    h, m, s = [float(part) for part in parts]
    if h < 0 or not 0 <= m < 60 or not 0 <= s < 60:
        raise ValueError(f"時間格式錯誤 '{delay_str}'，請使用 hh:mm:ss")
    return h * 3600 + m * 60 + s

def seconds_until_next_8am(now: datetime) -> tuple[float, datetime]:
    wake_time = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if wake_time < now:
        wake_time += timedelta(days=1)
    return (wake_time - now).total_seconds(), wake_time

def main():
    print("==================================================")
    print("🔄 開始執行掛機大循環 (AwayFromKeyboard Loop)")
    print("==================================================")
    
    accounts_to_run = list(ACCOUNTS.keys())
    total_accounts = len(accounts_to_run)
    
    if total_accounts == 0:
        print("❌ accounts.json 裡面沒有設定任何帳號！")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="AwayFromKeyboard 掛機大循環")
    parser.add_argument("--skip-current", action="store_true", help="略過起始帳號的掛機任務，直接切換到下一個帳號")
    delay_group = parser.add_mutually_exclusive_group()
    delay_group.add_argument("--delay", type=str, default=None, help="首次啟動前的延遲等待時間 (hh:mm:ss)")
    delay_group.add_argument("--delay-until-8", "--du8", action="store_true", help="延遲到下一個上午 08:00:00 再啟動")
    args = parser.parse_args()

    try:
        if args.delay_until_8:
            delay_seconds, wake_time = seconds_until_next_8am(datetime.now())
        else:
            delay_seconds = parse_delay_to_seconds(args.delay) if args.delay else 0
            wake_time = datetime.now() + timedelta(seconds=delay_seconds)
    except ValueError as e:
        print(f"❌ [錯誤] {e}")
        sys.exit(1)

    import task_config
    configured_tasks = task_config.get_tasks_to_run()

    print(f"📌 載入任務設定成功！本次將執行: {', '.join(configured_tasks)}")

    print(f"📌 總共將執行 {total_accounts} 個帳號，並從目前登入的帳號開始依序切換")
    
    python_exe = sys.executable
    run_router_script = Path(__file__).parent / "integration_task" / "run_router.py"

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
        if args.delay or args.delay_until_8:
            delay_label = "到上午 08:00:00" if args.delay_until_8 else args.delay
            print(f"\n⏳ [延遲啟動] 將先等待 {delay_label} ({int(delay_seconds)} 秒)")
            print(f"⏰ 預計啟動時間: {wake_time.strftime('%Y-%m-%d %H:%M:%S')}")
            time.sleep(delay_seconds)

        print("\n🌅 開始任務前檢查異地登入與登入畫面...")
        if recovery.handle_wakeup_exceptions():
            print("✅ 登入異常狀態已排除，確認返回主城。")
            if not recovery.recover_to_main(max_attempts=20):
                print("❌ [錯誤] 處理登入異常後仍無法回到主城。")
                sys.exit(1)

        accounts_per_round = len(list(ACCOUNTS.keys()))
        for i in range(accounts_per_round):
            print("\n" + "="*50)
            print(f"🚀 開始執行 ({i+1}/{accounts_per_round}): 第 {i+1} 個帳號任務")
            print("="*50 + "\n")
            
            try:
                # 0. 判斷是否略過起始帳號
                if args.skip_current and i == 0:
                    print(f"⚠️ [提示] 已啟用 --skip-current，跳過首發帳號的掛機任務，直接準備切換帳號...")
                else:
                    # 1. 執行掛機任務
                    for task_name in configured_tasks:
                        task_cmd = [python_exe, str(run_router_script), task_name]
                        print("\n" + "-" * 50)
                        print("🛠️ [Debug] 若此 Router 任務卡住，可複製以下指令單獨測試：")
                        print(f">>> {' '.join(task_cmd)}")
                        print("-" * 50 + "\n")
                        
                        result = subprocess.run(task_cmd, cwd=str(PROJECT_ROOT))
                        if result.returncode != 0:
                            print(f"\n❌ [錯誤] 第 {i+1} 個帳號的任務 【{task_name}】 回傳了非零錯誤碼 ({result.returncode})！")
                            print("⚠️ [Fail-Fast] 發生異常，立刻終止整支程式，不切換帳號以保留現場。")
                            sys.exit(1)
                        else:
                            print(f"✅ 第 {i+1} 個帳號的任務 【{task_name}】 順利完成！")
                            
                    print("🔍 子任務結束，交由 UIRecovery 強制驗證主城狀態...")
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
                    
                # 最後一輪不切換
                if i < accounts_per_round - 1:
                    print("\n⏳ 準備執行 [next] 帳號切換...")
                    switch_cmd = [python_exe, "-m", "switch_account.switch_account", "next"]
                    print(f"🔄 開始切換至下一個帳號 (next)...")
                    print("-" * 50)
                    print("🛠️ [Debug] 若切換帳號卡住，可手動在終端機貼上以下指令重新測試帳號切換：")
                    print(f">>> {' '.join(switch_cmd)}")
                    print("-" * 50 + "\n")
                    
                    success = switch_account("next")
                    if not success:
                        print("\n❌ [錯誤] 執行 [next] 帳號切換失敗！")
                        print("⚠️ [Fail-Fast] 切換失敗，立刻終止整支程式。")
                        sys.exit(1)
                    
                    print(f"🎉 帳號切換成功！")
                else:
                    print("\n🏁 已到達最後一輪，本循環所有帳號皆已執行完畢！")
                    
            except SystemExit:
                raise
            except Exception as e:
                print(f"\n❌ 執行時發生未預期的例外:")
                traceback.print_exc()
                print("\n⚠️ [Fail-Fast] 發生崩潰，立刻終止整支程式！")
                sys.exit(1)
    except KeyboardInterrupt:
        print("\n🛑 [中止] 接收到手動中斷指令 (Ctrl+C)，已安全退出掛機腳本。")
        sys.exit(0)

    print("\n✅ 所有帳號掛機大循環執行完畢！工作結束！")

if __name__ == "__main__":
    main()
