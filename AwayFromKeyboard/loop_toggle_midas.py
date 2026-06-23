import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta

# 強制設定輸出為 UTF-8，以防在 Windows 終端機顯示中文出錯
sys.stdout.reconfigure(encoding='utf-8')

# 確保專案根目錄在 sys.path 中
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from switch_account.switch_account import detect_current_account, switch_account, load_accounts
from src.daily_runner import build_context
from src.exceptions import TaskFailedError
from src.tasks.midas import MidasAutoResult, MidasTask
from src.vision_matcher import write_image
from AwayFromKeyboard.ui_recovery import UIRecovery
from AwayFromKeyboard.integration_task.router import RouteNavigator

AUTO_SHORT_COOLDOWN_SECONDS = 5 * 60
AUTO_OCR_FAILURE_SLEEP_SECONDS = 2 * 60 * 60
AUTO_WAKEUP_BUFFER_SECONDS = 4 * 60
AUTO_ALL_ACCOUNT_ORDER = ("em3", "311", "tiger", "14")
MIDAS_POPUP_RECOVERY_ATTEMPTS = 3
MIDAS_TITLE_ROI = MidasTask.TITLE_ROI

def parse_interval_to_seconds(interval_str: str) -> float:
    parts = interval_str.split(':')
    if len(parts) != 3:
        raise ValueError(f"時間格式錯誤 '{interval_str}'，請使用 hh:mm:ss")
    h, m, s = [float(p) for p in parts]
    return h * 3600 + m * 60 + s

def build_auto_account_order(
    accounts: dict,
    use_all: bool,
) -> list[str]:
    configured = ["em3"]
    if use_all:
        configured = list(AUTO_ALL_ACCOUNT_ORDER)
    else:
        configured.append("311")

    missing = [account for account in configured if account not in accounts]
    if missing:
        raise ValueError(f"--auto 缺少必要帳號設定: {', '.join(missing)}")

    return configured


def _format_seconds(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _recover_or_restart(recovery: UIRecovery) -> None:
    if recovery.recover_to_main():
        return

    print("⚠️ [系統] 畫面卡死或無法自動回到主城，啟動強制重啟機制...")
    recovery.controller.shell(["am", "force-stop", "com.ageofeternity.global"])
    time.sleep(3)
    recovery.controller.shell(
        ["monkey", "-p", "com.ageofeternity.global", "-c", "android.intent.category.LAUNCHER", "1"]
    )
    print("⏳ 遊戲已重啟，等待載入...")
    time.sleep(10)
    from src.game_entry import reenter_game

    if not reenter_game(recovery.controller, recovery.matcher):
        raise RuntimeError("重啟後仍無法成功進入主城")


def _save_midas_popup_recovery_debug(context, screen, attempt: int) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    failure_path = (
        project_root
        / "captures"
        / "failures"
        / "midas"
        / f"midas_dialog_missing_before_popup_recovery_{timestamp}_attempt{attempt}.png"
    )
    write_image(failure_path, screen)
    print(f"📷 [Midas] 已保存點金視窗缺失畫面: {failure_path}")

    save_debug = getattr(context.controller, "save_annotated_debug", None)
    if save_debug is None:
        return
    x, y, w, h = MIDAS_TITLE_ROI
    save_debug(
        f"midas_dialog_missing_popup_recovery_{attempt}",
        screen,
        lines=[
            f"Midas dialog missing; popup recovery attempt {attempt}/{MIDAS_POPUP_RECOVERY_ATTEMPTS}",
            "checking known gift-pack blocker before retrying route",
        ],
        boxes=[(x, y, w, h, "expected Midas title ROI")],
    )


def _execute_midas_with_popup_recovery(context, recovery: UIRecovery, route, action):
    for recovery_count in range(MIDAS_POPUP_RECOVERY_ATTEMPTS + 1):
        try:
            return action()
        except TaskFailedError:
            if recovery_count >= MIDAS_POPUP_RECOVERY_ATTEMPTS:
                raise
            attempt = recovery_count + 1
            screen = context.controller.screenshot()
            _save_midas_popup_recovery_debug(context, screen, attempt)
            if not route.handle_blocking_popup(screen):
                raise

            print(
                f"⚠️ [Midas] 已關閉臨時禮包廣告，"
                f"恢復主城並重新進入點金手 ({attempt}/{MIDAS_POPUP_RECOVERY_ATTEMPTS})。"
            )
            _recover_or_restart(recovery)
            route.execute_route(phase="enter")

    raise AssertionError("unreachable")


def run_midas_auto_once(context, recovery: UIRecovery, *, require_cooldown: bool) -> MidasAutoResult:
    route = RouteNavigator(route_name="點金手", controller=context.controller)
    route.execute_route(phase="enter")
    try:
        return _execute_midas_with_popup_recovery(
            context,
            recovery,
            route,
            lambda: MidasTask(context).execute_auto(
                require_cooldown_after_success=require_cooldown
            ),
        )
    finally:
        try:
            route.execute_route(phase="exit")
        finally:
            _recover_or_restart(recovery)


def run_midas_once(context, recovery: UIRecovery) -> str:
    route = RouteNavigator(route_name="點金手", controller=context.controller)
    route.execute_route(phase="enter")
    try:
        result = _execute_midas_with_popup_recovery(
            context,
            recovery,
            route,
            lambda: MidasTask(context).execute(),
        )
        print(f"✅ [ToggleLoop] 點金手執行完成：{result}")
        return result
    finally:
        try:
            route.execute_route(phase="exit")
        finally:
            _recover_or_restart(recovery)


def _print_ocr_failure(result: MidasAutoResult) -> None:
    print(
        "⚠️ [Auto] 點金手冷卻 OCR 失敗："
        f"text={result.ocr_text!r}, confidence={result.ocr_confidence:.3f}；"
        "將休息 02:00:00 後重新開始。"
    )


def process_auto_account(context, recovery: UIRecovery, account: str) -> bool:
    while True:
        print(f"\n💰 [Auto] 執行帳號 【{account}】 點金手")
        result = run_midas_auto_once(context, recovery, require_cooldown=False)
        if result.clicked:
            print(f"✅ [Auto] 帳號 【{account}】 點金成功，前往下一帳號。")
            return True
        if not result.cooldown_valid:
            print(
                "⚠️ [Auto] 點金手冷卻 OCR 失敗："
                f"text={result.ocr_text!r}, confidence={result.ocr_confidence:.3f}；"
                "視為冷卻超過 5 分鐘，前往下一帳號。"
            )
            return True

        cooldown = result.cooldown_seconds or 0
        print(f"⏱️ [Auto] 帳號 【{account}】 剩餘冷卻 {_format_seconds(cooldown)}")
        if cooldown > AUTO_SHORT_COOLDOWN_SECONDS:
            print("➡️ [Auto] 冷卻超過 5 分鐘，前往下一帳號。")
            return True

        wait_seconds = cooldown
        wake_time = datetime.now() + timedelta(seconds=wait_seconds)
        print(
            f"💤 [Auto] 短冷卻，原帳號等待 {_format_seconds(wait_seconds)}；"
            f"預計 {wake_time.strftime('%Y-%m-%d %H:%M:%S')} 重試。"
        )
        time.sleep(wait_seconds)
        print("🌅 [Auto] 短冷卻結束，檢查異地登入與登入畫面...")
        if recovery.handle_wakeup_exceptions():
            print("✅ [Auto] 短冷卻喚醒異常狀態已排除。")
        _recover_or_restart(recovery)


def run_auto_round(
    context,
    recovery: UIRecovery,
    *,
    accounts: dict,
    use_all: bool,
) -> int:
    print("\n🌅 [Auto] 新一輪啟動，先檢查異地登入與登入畫面...")
    if recovery.handle_wakeup_exceptions():
        print("✅ [Auto] 喚醒異常狀態已排除。")
    _recover_or_restart(recovery)

    current_account = detect_current_account(context.controller, context.matcher)
    order = build_auto_account_order(accounts, use_all)
    displayed_order = order if order[-1] == "em3" else order + ["em3"]
    print(f"🔄 [Auto] 本輪帳號順序: {' -> '.join(displayed_order)}")

    active_account = current_account
    for account in order:
        if active_account != account:
            print(f"🔄 [Auto] 切換至帳號 【{account}】")
            if not switch_account(account):
                raise RuntimeError(f"切換至帳號 {account} 失敗")
            active_account = account
        process_auto_account(context, recovery, account)

    if active_account != "em3":
        print("🔄 [Auto] 返回起點帳號 【em3】")
        if not switch_account("em3"):
            raise RuntimeError("返回 em3 失敗")

    print("\n🔎 [Auto] 已回到 em3，讀取大休眠冷卻時間...")
    final_result = run_midas_auto_once(context, recovery, require_cooldown=True)
    if not final_result.cooldown_valid:
        _print_ocr_failure(final_result)
        return AUTO_OCR_FAILURE_SLEEP_SECONDS
    cooldown = final_result.cooldown_seconds or 0
    sleep_seconds = max(0, cooldown - AUTO_WAKEUP_BUFFER_SECONDS)
    print(
        f"⏰ [Auto] em3 冷卻 {_format_seconds(cooldown)}，"
        f"扣除 4 分鐘登入緩衝後休眠 {_format_seconds(sleep_seconds)}。"
    )
    return sleep_seconds


def run_auto_loop(context, recovery: UIRecovery, *, use_all: bool) -> None:
    accounts = load_accounts()
    while True:
        sleep_seconds = run_auto_round(
            context,
            recovery,
            accounts=accounts,
            use_all=use_all,
        )
        next_time = datetime.now() + timedelta(seconds=sleep_seconds)
        print(
            f"💤 [Auto] 本輪結束，休眠 {_format_seconds(sleep_seconds)}；"
            f"預計 {next_time.strftime('%Y-%m-%d %H:%M:%S')} 喚醒。"
        )
        time.sleep(sleep_seconds)

def main():
    parser = argparse.ArgumentParser(description="AwayFromKeyboard 雙帳號定時切換掛機腳本 (點金手專用版)")
    parser.add_argument("--interval", type=str, default="08:00:00", help="休眠倒數時間 (hh:mm:ss)，預設 08:00:00")
    parser.add_argument("--toggles", type=int, default=1, help="執行幾輪 (Rounds)。預設 1 輪")
    parser.add_argument("--all", action="store_true", help="切換全部 4 個帳號 (使用 next 模式)")
    parser.add_argument("--delay", type=str, default=None, help="首次啟動前的延遲等待時間 (hh:mm:ss)")
    parser.add_argument("--auto", action="store_true", help="依點金手冷卻時間自動輪轉帳號並休眠")
    parser.add_argument(
        "--debug-actions",
        action="store_true",
        help="儲存 Router 與點金手每次操作前後的偵錯截圖",
    )
    args = parser.parse_args()

    try:
        interval_seconds = parse_interval_to_seconds(args.interval)
        delay_seconds = parse_interval_to_seconds(args.delay) if args.delay else 0
    except ValueError as e:
        print(f"❌ [錯誤] {e}")
        sys.exit(1)
        
    if args.all:
        try:
            accounts_map = load_accounts()
            accounts_per_round = len(accounts_map)
        except Exception as e:
            print(f"⚠️ [警告] 無法讀取 accounts.json ({e})，預設改為 4 個帳號。")
            accounts_per_round = 4
    else:
        accounts_per_round = 2
        
    switch_cmd = "next" if args.all else "toggle"
    total_runs = accounts_per_round * args.toggles
        
    print("==================================================")
    print(f"🔄 開始執行定時雙帳號掛機 (Loop Toggle Midas)")
    print(f"⏱️ 設定休眠區間: {args.interval} ({int(interval_seconds)} 秒)")
    print(f"🔄 執行輪數: {args.toggles} 輪，單輪帳號數: {accounts_per_round}")
    print(f"🔄 總執行次數: {total_runs} 次")
    print("==================================================")

    try:
        context = build_context(debug=args.debug_actions, console_debug=True)
        if not context.controller.connect():
             print("❌ 無法連線至 ADB 裝置")
             sys.exit(1)
        recovery = UIRecovery(context.controller, context.matcher, context.detector)
    except Exception as e:
        print(f"❌ 初始化 UIRecovery 失敗: {e}")
        sys.exit(1)

    try:
        if args.auto:
            if args.delay:
                print("ℹ️ [Auto] --auto 模式忽略 --delay。")
            if args.interval != "08:00:00" or args.toggles != 1:
                print("ℹ️ [Auto] --auto 模式忽略 --interval 與 --toggles。")
            run_auto_loop(context, recovery, use_all=args.all)
            return

        if args.delay:
            wake_time = datetime.now() + timedelta(seconds=delay_seconds)
            print(f"\n⏳ [延遲啟動] 接收到 --delay 指令，將先進行首次休眠: {args.delay} ({int(delay_seconds)} 秒)")
            print(f"⏰ 預計首次喚醒時間 (Local Time): {wake_time.strftime('%Y-%m-%d %H:%M:%S')}")
            time.sleep(delay_seconds)
            
        while True:
            print("\n🌅 系統喚醒，執行一次性特殊檢查...")
            if recovery.handle_wakeup_exceptions():
                print("✅ 喚醒異常狀態已排除，準備載入遊戲大廳。")
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
                run_midas_once(context, recovery)
            
            # 執行完畢
            print(f"\n▶️ === 結尾復原切換 ({switch_cmd})：準備回到首發帳號 ===")
            print("[ToggleLoop] 執行結尾帳號切換...")
            try:
                switch_account(switch_cmd)
            except Exception as e:
                print(f"⚠️ [警告] 結尾切換帳號發生錯誤: {e}")
                
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
