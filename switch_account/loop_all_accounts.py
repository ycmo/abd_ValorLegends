import time
import sys
import argparse
from switch_account import switch_account, ACCOUNTS

def main():
    print("==================================================")
    print("🔄 開始執行全帳號自動切換循環")
    print("==================================================")
    
    accounts_to_run = list(ACCOUNTS.keys())
    total_accounts = len(accounts_to_run)
    
    if total_accounts == 0:
        print("❌ accounts.json 裡面沒有設定任何帳號！")
        sys.exit(1)

    print(f"📌 總共偵測到 {total_accounts} 個帳號: {', '.join(accounts_to_run)}")
    
    parser = argparse.ArgumentParser(description="自動切換所有帳號")
    parser.add_argument("--start", type=str, help="設定起始帳號 (目前所在的帳號)，程式會跳過此帳號，並切換後續的帳號")
    args = parser.parse_args()

    current_account = args.start

    if current_account:
        if current_account not in accounts_to_run:
            print(f"❌ 找不到帳號 {current_account}，請確認輸入是否正確！支援的帳號有: {', '.join(accounts_to_run)}")
            sys.exit(1)
            
        start_idx = accounts_to_run.index(current_account)
        # 重新排列名單：從目前帳號的下一個開始，並繞一圈回到前面，但不包含自己
        accounts_to_run = accounts_to_run[start_idx+1:] + accounts_to_run[:start_idx]
        print(f"\n✅ 已設定目前帳號為 【{current_account}】")
        print(f"即將為你切換剩下的 {len(accounts_to_run)} 個帳號，順序為: {', '.join(accounts_to_run)}")

    for idx, account in enumerate(accounts_to_run):
        print("\n" + "="*50)
        print(f"🚀 開始執行 ({idx+1}/{len(accounts_to_run)}): 帳號 【{account}】")
        print("="*50 + "\n")
        
        try:
            success = switch_account(account)
            if success:
                print(f"\n🎉 帳號 【{account}】 流程完整執行完畢！")
            else:
                print(f"\n⚠️ 帳號 【{account}】 發生致命錯誤，立刻終止所有流程！")
                sys.exit(1)
            
        except Exception as e:
            import traceback
            print(f"\n❌ 執行帳號 【{account}】 時發生未預期的錯誤:")
            traceback.print_exc()
            print("\n⚠️ 發生崩潰，立刻終止所有流程！")
            sys.exit(1)
        
        # 只要不是最後一個帳號，或者是你想讓最後一個帳號也掛機一分鐘
        print("\n⏳ 進入掛機休息時間，等待 60 秒...")
        for i in range(60, 0, -1):
            # 每 10 秒印一次倒數，避免畫面太乾
            if i % 10 == 0 or i <= 5:
                print(f"   倒數 {i} 秒...")
            time.sleep(1)

    print("\n✅ 所有帳號循環執行完畢！工作結束！")

if __name__ == "__main__":
    main()
