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
from src.account_state import TAIPEI_TZ, clear_activity_state, write_activity_state, write_current_account
from src.tasks.midas import MidasAutoResult, MidasTask
from src.vision_matcher import write_image
from AwayFromKeyboard.ui_recovery import UIRecovery
from AwayFromKeyboard.integration_task.router import RouteNavigator
from AwayFromKeyboard.discord_notify import notify_status

AUTO_SHORT_COOLDOWN_SECONDS = 5 * 60
AUTO_OCR_FAILURE_SLEEP_SECONDS = 2 * 60 * 60
AUTO_WAKEUP_BUFFER_SECONDS = 4 * 60
AUTO_ALL_ACCOUNT_ORDER = ("em3", "311", "tiger", "14")
MIDAS_POPUP_RECOVERY_ATTEMPTS = 3
MIDAS_TITLE_ROI = MidasTask.TITLE_ROI
MIDAS_ACTIVITY_NAME = "midas_auto"

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
        raise ValueError(f"auto 缺少必要帳號設定: {', '.join(missing)}")

    return configured


def build_sweep_first_order(current_account: str | None, accounts: dict, use_all: bool) -> list[str]:
    """First-run order that minimizes Google/email account switching before returning to em3."""
    if not use_all:
        configured = [current_account] if current_account else []
        if "em3" not in configured:
            configured.append("em3")
        if "311" not in configured and current_account == "em3":
            configured.insert(1, "311")
        elif "311" not in configured and current_account not in (None, "311"):
            configured.append("311")
    elif current_account == "em3":
        configured = ["em3", "311", "tiger", "14"]
    elif current_account == "311":
        configured = ["311", "tiger", "14"]
    elif current_account == "tiger":
        configured = ["tiger", "14", "311"]
    elif current_account == "14":
        configured = ["14", "tiger", "311"]
    else:
        configured = ["em3", "311", "tiger", "14"]

    deduped: list[str] = []
    for account in configured:
        if account not in deduped:
            deduped.append(account)
    if deduped[-1] != "em3":
        deduped.append("em3")

    missing = [account for account in deduped if account not in accounts]
    if missing:
        raise ValueError(f"--sweep-first 缺少必要帳號設定: {', '.join(missing)}")

    return deduped


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


def _record_current_account(account: str | None, source: str) -> None:
    if account:
        write_current_account(account, source=source)


def _set_midas_activity_active(source: str) -> None:
    write_activity_state(MIDAS_ACTIVITY_NAME, active=True, source=source)


def _refresh_midas_activity(source: str) -> None:
    _set_midas_activity_active(source)


def _clear_midas_activity_active(source: str, *, wake_at: datetime | None = None) -> None:
    if wake_at is not None:
        if wake_at.tzinfo is None:
            wake_at = wake_at.replace(tzinfo=TAIPEI_TZ)
        clear_activity_state(
            MIDAS_ACTIVITY_NAME,
            source=source,
            extra={"wake_at": wake_at.astimezone(TAIPEI_TZ).isoformat(timespec="seconds")},
        )
        return
    clear_activity_state(MIDAS_ACTIVITY_NAME, source=source)


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


def process_auto_account(context, recovery: UIRecovery, account: str, *, notify_enabled: bool = False) -> bool:
    while True:
        print(f"\n💰 [Auto] 執行帳號 【{account}】 點金手")
        notify_status("Midas", "開始", account=account, route="點金手", enabled=notify_enabled)
        result = run_midas_auto_once(context, recovery, require_cooldown=False)
        if result.clicked:
            print(f"✅ [Auto] 帳號 【{account}】 點金成功，前往下一帳號。")
            notify_status("Midas", "完成", account=account, route="點金手", enabled=notify_enabled)
            return True
        if not result.cooldown_valid:
            print(
                "⚠️ [Auto] 點金手冷卻 OCR 失敗："
                f"text={result.ocr_text!r}, confidence={result.ocr_confidence:.3f}；"
                "視為冷卻超過 5 分鐘，前往下一帳號。"
            )
            notify_status(
                "Midas",
                "OCR 失敗",
                account=account,
                route="點金手",
                detail=f"text={result.ocr_text!r}, conf={result.ocr_confidence:.3f}",
                enabled=notify_enabled,
            )
            return True

        cooldown = result.cooldown_seconds or 0
        print(f"⏱️ [Auto] 帳號 【{account}】 剩餘冷卻 {_format_seconds(cooldown)}")
        if cooldown > AUTO_SHORT_COOLDOWN_SECONDS:
            print("➡️ [Auto] 冷卻超過 5 分鐘，前往下一帳號。")
            notify_status(
                "Midas",
                "冷卻中",
                account=account,
                route="點金手",
                detail=_format_seconds(cooldown),
                enabled=notify_enabled,
            )
            return True

        wait_seconds = cooldown
        wake_time = datetime.now() + timedelta(seconds=wait_seconds)
        print(
            f"💤 [Auto] 短冷卻，原帳號等待 {_format_seconds(wait_seconds)}；"
            f"預計 {wake_time.strftime('%Y-%m-%d %H:%M:%S')} 重試。"
        )
        notify_status(
            "Midas",
            "短冷卻等待",
            account=account,
            route="點金手",
            detail=f"{_format_seconds(wait_seconds)}; wake={wake_time.strftime('%Y-%m-%d %H:%M:%S')}",
            enabled=notify_enabled,
        )
        _refresh_midas_activity("midas.auto.short_cooldown_sleep")
        time.sleep(wait_seconds)
        print("🌅 [Auto] 短冷卻結束，檢查異地登入與登入畫面...")
        if recovery.handle_wakeup_exceptions():
            print("✅ [Auto] 短冷卻喚醒異常狀態已排除。")
        _recover_or_restart(recovery)


def _read_em3_sleep_seconds(context, recovery: UIRecovery, *, notify_enabled: bool = False) -> int:
    print("\n🔎 [Auto] 已回到 em3，讀取大休眠冷卻時間...")
    final_result = run_midas_auto_once(context, recovery, require_cooldown=True)
    if not final_result.cooldown_valid:
        _print_ocr_failure(final_result)
        notify_status(
            "Midas",
            "em3 OCR 失敗",
            account="em3",
            route="點金手",
            detail=f"text={final_result.ocr_text!r}, conf={final_result.ocr_confidence:.3f}; sleep=02:00:00",
            enabled=notify_enabled,
        )
        return AUTO_OCR_FAILURE_SLEEP_SECONDS

    cooldown = final_result.cooldown_seconds or 0
    sleep_seconds = max(0, cooldown - AUTO_WAKEUP_BUFFER_SECONDS)
    print(
        f"⏰ [Auto] em3 冷卻 {_format_seconds(cooldown)}，"
        f"扣除 4 分鐘登入緩衝後休眠 {_format_seconds(sleep_seconds)}。"
    )
    wake_time = datetime.now() + timedelta(seconds=sleep_seconds)
    notify_status(
        "Midas",
        "進入大休眠",
        account="em3",
        route="點金手",
        detail=f"cooldown={_format_seconds(cooldown)}, sleep={_format_seconds(sleep_seconds)}, wake={wake_time.strftime('%Y-%m-%d %H:%M:%S')}",
        enabled=notify_enabled,
    )
    return sleep_seconds


def run_auto_initial_round(context, recovery: UIRecovery, *, notify_enabled: bool = False) -> int:
    print("\n🌅 [Auto] 初始輪啟動，先檢查異地登入與登入畫面...")
    if recovery.handle_wakeup_exceptions():
        print("✅ [Auto] 初始輪喚醒異常狀態已排除。")
    _recover_or_restart(recovery)

    current_account = detect_current_account(context.controller, context.matcher)
    _record_current_account(current_account, "afk.midas.detect.initial")
    current_label = current_account or "目前帳號"
    print(
        "\n▶️ [Auto] 初始輪：先執行當前畫面帳號點金，"
        "再回 em3 讀取第一次大休眠時間。"
    )
    process_auto_account(context, recovery, current_label, notify_enabled=notify_enabled)

    if current_account != "em3":
        print("🔄 [Auto] 初始輪返回起點帳號 【em3】")
        notify_status("Midas", "切換帳號開始", account="em3", enabled=notify_enabled)
        _refresh_midas_activity("midas.auto.before_switch")
        if not switch_account("em3"):
            raise RuntimeError("初始輪返回 em3 失敗")
        _record_current_account("em3", "afk.midas.switch")
        notify_status("Midas", "切換帳號完成", account="em3", enabled=notify_enabled)

    return _read_em3_sleep_seconds(context, recovery, notify_enabled=notify_enabled)


def run_auto_sweep_first_round(
    context,
    recovery: UIRecovery,
    *,
    accounts: dict,
    use_all: bool,
    notify_enabled: bool = False,
) -> int:
    print("\n🌅 [Auto] sweep-first 初始輪啟動，先檢查異地登入與登入畫面...")
    if recovery.handle_wakeup_exceptions():
        print("✅ [Auto] sweep-first 初始輪喚醒異常狀態已排除。")
    _recover_or_restart(recovery)

    current_account = detect_current_account(context.controller, context.matcher)
    _record_current_account(current_account, "afk.midas.detect.sweep_first")
    order = build_sweep_first_order(current_account, accounts, use_all)
    process_order = order[:-1]
    final_account = order[-1]
    print(f"🔄 [Auto] sweep-first 初始輪帳號順序: {' -> '.join(order)}")

    active_account = current_account
    for account in process_order:
        if active_account != account:
            print(f"🔄 [Auto] 切換至帳號 【{account}】")
            notify_status("Midas", "切換帳號開始", account=account, enabled=notify_enabled)
            _refresh_midas_activity("midas.auto.before_switch")
            if not switch_account(account):
                raise RuntimeError(f"sweep-first 切換至帳號 {account} 失敗")
            active_account = account
            _record_current_account(account, "afk.midas.switch")
            notify_status("Midas", "切換帳號完成", account=account, enabled=notify_enabled)
        process_auto_account(context, recovery, account, notify_enabled=notify_enabled)

    if active_account != final_account:
        print(f"🔄 [Auto] sweep-first 返回起點帳號 【{final_account}】")
        notify_status("Midas", "切換帳號開始", account=final_account, enabled=notify_enabled)
        _refresh_midas_activity("midas.auto.before_switch")
        if not switch_account(final_account):
            raise RuntimeError(f"sweep-first 返回 {final_account} 失敗")
        _record_current_account(final_account, "afk.midas.switch")
        notify_status("Midas", "切換帳號完成", account=final_account, enabled=notify_enabled)

    return _read_em3_sleep_seconds(context, recovery, notify_enabled=notify_enabled)


def run_auto_round(
    context,
    recovery: UIRecovery,
    *,
    accounts: dict,
    use_all: bool,
    notify_enabled: bool = False,
) -> int:
    print("\n🌅 [Auto] 新一輪啟動，先檢查異地登入與登入畫面...")
    if recovery.handle_wakeup_exceptions():
        print("✅ [Auto] 喚醒異常狀態已排除。")
    _recover_or_restart(recovery)

    current_account = detect_current_account(context.controller, context.matcher)
    _record_current_account(current_account, "afk.midas.detect.round")
    order = build_auto_account_order(accounts, use_all)
    displayed_order = order if order[-1] == "em3" else order + ["em3"]
    print(f"🔄 [Auto] 本輪帳號順序: {' -> '.join(displayed_order)}")

    active_account = current_account
    for account in order:
        if active_account != account:
            print(f"🔄 [Auto] 切換至帳號 【{account}】")
            notify_status("Midas", "切換帳號開始", account=account, enabled=notify_enabled)
            _refresh_midas_activity("midas.auto.before_switch")
            if not switch_account(account):
                raise RuntimeError(f"切換至帳號 {account} 失敗")
            active_account = account
            _record_current_account(account, "afk.midas.switch")
            notify_status("Midas", "切換帳號完成", account=account, enabled=notify_enabled)
        process_auto_account(context, recovery, account, notify_enabled=notify_enabled)

    if active_account != "em3":
        print("🔄 [Auto] 返回起點帳號 【em3】")
        notify_status("Midas", "切換帳號開始", account="em3", enabled=notify_enabled)
        _refresh_midas_activity("midas.auto.before_switch")
        if not switch_account("em3"):
            raise RuntimeError("返回 em3 失敗")
        _record_current_account("em3", "afk.midas.switch")
        notify_status("Midas", "切換帳號完成", account="em3", enabled=notify_enabled)

    return _read_em3_sleep_seconds(context, recovery, notify_enabled=notify_enabled)


def run_auto_loop(
    context,
    recovery: UIRecovery,
    *,
    use_all: bool,
    sweep_first: bool = False,
    notify_enabled: bool = False,
) -> None:
    accounts = load_accounts()
    notify_status(
        "Midas",
        "啟動",
        detail=f"accounts={'all' if use_all else 'em3/311'}, sweep_first={sweep_first}",
        enabled=notify_enabled,
    )
    _set_midas_activity_active("midas.auto.initial.start")
    if sweep_first:
        sleep_seconds = run_auto_sweep_first_round(
            context,
            recovery,
            accounts=accounts,
            use_all=use_all,
            notify_enabled=notify_enabled,
        )
    else:
        sleep_seconds = run_auto_initial_round(context, recovery, notify_enabled=notify_enabled)
    next_time = datetime.now(TAIPEI_TZ) + timedelta(seconds=sleep_seconds)
    print(
        f"💤 [Auto] 初始輪結束，休眠 {_format_seconds(sleep_seconds)}；"
        f"預計 {next_time.strftime('%Y-%m-%d %H:%M:%S')} 喚醒後進入第一輪。"
    )
    _clear_midas_activity_active("midas.auto.big_sleep", wake_at=next_time)
    time.sleep(sleep_seconds)

    while True:
        _set_midas_activity_active("midas.auto.round.start")
        sleep_seconds = run_auto_round(
            context,
            recovery,
            accounts=accounts,
            use_all=use_all,
            notify_enabled=notify_enabled,
        )
        next_time = datetime.now(TAIPEI_TZ) + timedelta(seconds=sleep_seconds)
        print(
            f"💤 [Auto] 本輪結束，休眠 {_format_seconds(sleep_seconds)}；"
            f"預計 {next_time.strftime('%Y-%m-%d %H:%M:%S')} 喚醒。"
        )
        _clear_midas_activity_active("midas.auto.big_sleep", wake_at=next_time)
        time.sleep(sleep_seconds)

def main():
    parser = argparse.ArgumentParser(description="AwayFromKeyboard 雙帳號定時切換掛機腳本 (點金手專用版)")
    parser.add_argument("--all", action="store_true", help="自動循環全部 4 個帳號；預設只循環 em3 與 311")
    parser.add_argument(
        "--sweep-first",
        action="store_true",
        help="第一輪先把其他帳號掃過一次，再回 em3 點金、讀冷卻並睡眠",
    )
    parser.add_argument(
        "--debug-actions",
        action="store_true",
        help="儲存 Router 與點金手每次操作前後的偵錯截圖",
    )
    parser.add_argument("--no-discord", action="store_true", help="關閉 Discord 狀態通知")
    args = parser.parse_args()

    if args.all:
        try:
            accounts_map = load_accounts()
            accounts_per_round = len(accounts_map)
        except Exception as e:
            print(f"⚠️ [警告] 無法讀取 accounts.json ({e})，預設改為 4 個帳號。")
            accounts_per_round = 4
    else:
        accounts_per_round = 2
        
    print("==================================================")
    print("🔄 開始執行點金手自動循環 (Loop Toggle Midas)")
    print(f"🔄 循環帳號數: {accounts_per_round}")
    print(f"🔄 初始策略: {'sweep-first' if args.sweep_first else 'current-account then em3'}")
    print("==================================================")

    try:
        context = build_context(debug=args.debug_actions, console_debug=True)
        if not context.controller.connect():
             print("❌ 無法連線至 ADB 裝置")
             notify_status("Midas", "ADB 連線失敗", enabled=not args.no_discord)
             sys.exit(1)
        recovery = UIRecovery(context.controller, context.matcher, context.detector)
    except Exception as e:
        print(f"❌ 初始化 UIRecovery 失敗: {e}")
        notify_status("Midas", "初始化失敗", detail=str(e), enabled=not args.no_discord)
        sys.exit(1)

    try:
        run_auto_loop(
            context,
            recovery,
            use_all=args.all,
            sweep_first=args.sweep_first,
            notify_enabled=not args.no_discord,
        )
            
    except KeyboardInterrupt:
        _clear_midas_activity_active("midas.auto.ctrl_c")
        print("\n🛑 [中止] 接收到手動中斷指令 (Ctrl+C)，已安全退出掛機腳本。")
        sys.exit(0)
    except Exception as e:
        _clear_midas_activity_active("midas.auto.exception")
        notify_status(
            "Midas",
            "崩潰",
            detail=str(e),
            enabled=not args.no_discord,
        )
        raise

if __name__ == "__main__":
    main()
