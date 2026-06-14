import time
import sys
import argparse
import traceback
import subprocess
from pathlib import Path

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
    parser.add_argument("--start", type=str, help="設定起始帳號 (目前所在的帳號)，程式會直接從此帳號開始做任務")
    parser.add_argument("--skip-current", action="store_true", help="略過起始帳號的掛機任務，直接切換到下一個帳號")
    args = parser.parse_args()

    import task_config
    configured_tasks = task_config.get_tasks_to_run()

    print(f"📌 載入任務設定成功！本次將執行: {', '.join(configured_tasks)}")

    if args.start:
        if args.start not in accounts_to_run:
            print(f"❌ 找不到帳號 {args.start}，請確認輸入是否正確！支援的帳號有: {', '.join(accounts_to_run)}")
            sys.exit(1)
        start_idx = accounts_to_run.index(args.start)
        # 從指定的帳號開始，後面的接在前面 (包含自己作為第一個)
        accounts_to_run = accounts_to_run[start_idx:] + accounts_to_run[:start_idx]

    print(f"📌 總共將執行 {total_accounts} 個帳號，順序為: {', '.join(accounts_to_run)}")
    
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

    for idx, account in enumerate(accounts_to_run):
        print("\n" + "="*50)
        print(f"🚀 開始執行 ({idx+1}/{len(accounts_to_run)}): 帳號 【{account}】 任務")
        print("="*50 + "\n")
        
        try:
            # 0. 判斷是否略過起始帳號
            if args.skip_current and idx == 0:
                print(f"⚠️ [提示] 已啟用 --skip-current，跳過帳號 【{account}】 的掛機任務，直接準備切換帳號...")
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
                        print(f"\n❌ [錯誤] 帳號 【{account}】 的任務 【{task_name}】 回傳了非零錯誤碼 ({result.returncode})！")
                        print("⚠️ [Fail-Fast] 發生異常，立刻終止整支程式，不切換帳號以保留現場。")
                        sys.exit(1)
                    else:
                        print(f"✅ 帳號 【{account}】 的任務 【{task_name}】 順利完成！")
                        
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
                
            # 2. 任務完成後，決定下一個要切換的帳號
            if idx < len(accounts_to_run) - 1:
                next_account = accounts_to_run[idx + 1]
            else:
                next_account = accounts_to_run[0]
                print("\n🏁 已到達最後一個帳號，準備切換回初始帳號，完成大循環復原。")
                
            print(f"\n⏳ 準備切換至帳號 【{next_account}】...")
            
            # 3. 執行帳號切換
            switch_cmd = [python_exe, "-m", "switch_account.switch_account", next_account]
            print(f"🔄 開始切換至帳號 【{next_account}】...")
            print("-" * 50)
            print("🛠️ [Debug] 若切換帳號卡住，可手動在終端機貼上以下指令重新測試帳號切換：")
            print(f">>> {' '.join(switch_cmd)}")
            print("-" * 50 + "\n")
            
            success = switch_account(next_account)
            if not success:
                print(f"\n❌ [錯誤] 切換至帳號 【{next_account}】 失敗！")
                print("⚠️ [Fail-Fast] 切換失敗，立刻終止整支程式。")
                sys.exit(1)
            
            print(f"🎉 帳號切換成功！")
            
        except SystemExit:
            # sys.exit(1) 會拋出 SystemExit，我們應該讓它直接結束，不被下面的 Exception 攔截
            raise
        except Exception as e:
            print(f"\n❌ 執行時發生未預期的例外:")
            traceback.print_exc()
            print("\n⚠️ [Fail-Fast] 發生崩潰，立刻終止整支程式！")
            sys.exit(1)

    print("\n✅ 所有帳號掛機大循環執行完畢！工作結束！")

if __name__ == "__main__":
    main()
