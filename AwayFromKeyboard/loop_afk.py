import time
import sys
import argparse
import traceback
import subprocess
import json
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# 加入專案目錄以利匯入 switch_account
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from switch_account.switch_account import switch_account, detect_current_account, ACCOUNTS
from src.adb_controller import DeviceController
from src.vision_matcher import VisionMatcher
from src.scene_detector import SceneDetector
from AwayFromKeyboard.ui_recovery import UIRecovery
from AwayFromKeyboard.discord_notify import notify_status

# 強制設定輸出為 UTF-8，以防在 Windows 終端機顯示中文出錯
sys.stdout.reconfigure(encoding='utf-8')

STATE_DIR = Path(__file__).resolve().parent / "state"
try:
    TAIPEI_TZ = ZoneInfo("Asia/Taipei")
except ZoneInfoNotFoundError:
    TAIPEI_TZ = timezone(timedelta(hours=8), name="Asia/Taipei")

def parse_delay_to_seconds(delay_str: str) -> float:
    parts = delay_str.split(':')
    if len(parts) != 3:
        raise ValueError(f"時間格式錯誤 '{delay_str}'，請使用 hh:mm:ss")
    h, m, s = [float(part) for part in parts]
    if h < 0 or not 0 <= m < 60 or not 0 <= s < 60:
        raise ValueError(f"時間格式錯誤 '{delay_str}'，請使用 hh:mm:ss")
    return h * 3600 + m * 60 + s

def parse_time_of_day(time_str: str) -> tuple[int, int, int]:
    parts = time_str.split(':')
    if len(parts) not in (2, 3):
        raise ValueError(f"開始時間格式錯誤 '{time_str}'，請使用 HH:MM 或 HH:MM:SS")
    try:
        values = [int(part) for part in parts]
    except ValueError as exc:
        raise ValueError(f"開始時間格式錯誤 '{time_str}'，請使用 HH:MM 或 HH:MM:SS") from exc
    if len(values) == 2:
        values.append(0)
    hour, minute, second = values
    if not 0 <= hour < 24 or not 0 <= minute < 60 or not 0 <= second < 60:
        raise ValueError(f"開始時間格式錯誤 '{time_str}'，請使用 HH:MM 或 HH:MM:SS")
    return hour, minute, second

def seconds_until_next_8am(now: datetime) -> tuple[float, datetime]:
    wake_time = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if wake_time < now:
        wake_time += timedelta(days=1)
    return (wake_time - now).total_seconds(), wake_time

def resolve_start_delay(
    *,
    delay: str | None,
    delay_until_8: bool,
    config_start_time: str | None = None,
    run_now: bool = False,
    now: datetime | None = None,
) -> tuple[float, datetime, str]:
    current = now or datetime.now()
    if run_now:
        return 0, current, "立刻執行"

    extra_delay = parse_delay_to_seconds(delay) if delay else 0
    if delay_until_8:
        base_delay, wake_time = seconds_until_next_8am(current)
        total_delay = base_delay + extra_delay
        final_wake_time = wake_time + timedelta(seconds=extra_delay)
        label = "到上午 08:00:00"
        if delay:
            label += f" 後再延遲 {delay}"
        return total_delay, final_wake_time, label

    if delay:
        wake_time = current + timedelta(seconds=extra_delay)
        return extra_delay, wake_time, delay

    if config_start_time:
        hour, minute, second = parse_time_of_day(config_start_time)
        wake_time = current.replace(hour=hour, minute=minute, second=second, microsecond=0)
        if wake_time < current:
            wake_time += timedelta(days=1)
        return (wake_time - current).total_seconds(), wake_time, f"ini start_time {config_start_time}"

    return 0, current, "0"

def today_key(now: datetime | None = None) -> str:
    current = now or datetime.now(TAIPEI_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=TAIPEI_TZ)
    taipei_now = current.astimezone(TAIPEI_TZ)
    reset_adjusted = taipei_now - timedelta(hours=8)
    return reset_adjusted.strftime("%Y-%m-%d")

def completion_file_for_date(date_key: str) -> Path:
    return STATE_DIR / f"route_completion_{date_key}.json"

def load_completion_state(date_key: str) -> dict:
    path = completion_file_for_date(date_key)
    if not path.exists():
        return {"date": date_key, "completed": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"⚠️ [警告] 完成紀錄格式錯誤，將重新建立: {path}")
        return {"date": date_key, "completed": {}}
    if data.get("date") != date_key or not isinstance(data.get("completed"), dict):
        return {"date": date_key, "completed": {}}
    return data

def save_completion_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = completion_file_for_date(state["date"])
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(path)

def is_route_completed(state: dict, account: str, route_name: str) -> bool:
    value = state.get("completed", {}).get(account, {}).get(route_name)
    return bool(value)

def mark_route_completed(state: dict, account: str, route_name: str) -> None:
    completed = state.setdefault("completed", {})
    account_state = completed.setdefault(account, {})
    account_state[route_name] = datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")
    save_completion_state(state)

def pending_tasks_for_account(
    state: dict,
    account: str,
    configured_tasks: list[str],
    *,
    force: bool,
) -> list[str]:
    if force:
        return list(configured_tasks)
    return [
        task_name
        for task_name in configured_tasks
        if not is_route_completed(state, account, task_name)
    ]

def build_account_rotation(accounts: list[str], current_account: str | None) -> list[str]:
    if not accounts:
        return []
    if current_account not in accounts:
        return list(accounts)
    start = accounts.index(current_account)
    return accounts[start:] + accounts[:start]

def build_account_execution_order(
    accounts: dict,
    current_account: str | None,
    state: dict,
    configured_tasks: list[str],
    *,
    force: bool,
) -> list[str]:
    pending_accounts = [
        account_name
        for account_name in accounts.keys()
        if pending_tasks_for_account(state, account_name, configured_tasks, force=force)
    ]
    if not pending_accounts:
        return []

    current_type = accounts.get(current_account, {}).get("type")
    rotated = build_account_rotation(pending_accounts, current_account)
    if not current_type:
        return rotated

    same_type = [
        account_name
        for account_name in rotated
        if accounts.get(account_name, {}).get("type") == current_type
    ]
    other_type = [
        account_name
        for account_name in rotated
        if accounts.get(account_name, {}).get("type") != current_type
    ]
    return same_type + other_type

def load_runtime_task_state():
    from AwayFromKeyboard import task_config
    configured_tasks = task_config.get_tasks_to_run()
    date_key = today_key()
    completion_state = load_completion_state(date_key)
    return configured_tasks, date_key, completion_state

def sanitize_log_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in str(value))
    return safe.strip("_") or "route"

def build_route_log_file(log_dir: str | None, *, account_name: str, task_name: str, now: datetime | None = None) -> Path | None:
    if not log_dir:
        return None
    directory = Path(log_dir).expanduser()
    if not directory.is_absolute():
        directory = PROJECT_ROOT / directory
    current = now or datetime.now(TAIPEI_TZ)
    timestamp = current.strftime("%Y%m%d_%H%M%S")
    filename = f"afk_{timestamp}_{sanitize_log_name(account_name)}_{sanitize_log_name(task_name)}.txt"
    return directory / filename

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
    parser.add_argument("-f", "--force", action="store_true", help="忽略今日完成紀錄，強制執行所有帳號與 route")
    parser.add_argument("--config", "--ini", dest="config_path", default=None, help="指定 afk tasks ini 檔案路徑")
    parser.add_argument("--debug-actions", action="store_true", help="儲存 Router 與任務每次操作前後的偵錯截圖")
    parser.add_argument("--force-subprocess", action="store_true", help="Router 任務強制使用舊的 subprocess 執行模式")
    parser.add_argument("--log-dir", default=None, help="每個 Router 任務各自輸出一份 UTF-8 log 到指定目錄")
    parser.add_argument("--no-discord", action="store_true", help="關閉 Discord 狀態通知")
    parser.add_argument("--delay", type=str, default=None, help="首次啟動前的額外延遲等待時間 (hh:mm:ss)")
    parser.add_argument("--delay-until-8", "--du8", action="store_true", help="先延遲到下一個上午 08:00:00；可再搭配 --delay 額外等待")
    parser.add_argument("--now", action="store_true", help="忽略 ini 的 start_time，立刻執行")
    args = parser.parse_args()

    if args.config_path:
        config_path = Path(args.config_path).expanduser().resolve()
        os.environ["AFK_TASKS_INI"] = str(config_path)
    else:
        config_path = None

    from AwayFromKeyboard import task_config
    config_start_time = task_config.get_start_time()

    try:
        delay_seconds, wake_time, delay_label = resolve_start_delay(
            delay=args.delay,
            delay_until_8=args.delay_until_8,
            config_start_time=config_start_time,
            run_now=args.now,
        )
    except ValueError as e:
        print(f"❌ [錯誤] {e}")
        sys.exit(1)

    print(f"📌 總共將執行 {total_accounts} 個帳號，並從目前登入的帳號開始依序切換")
    notify_enabled = not args.no_discord
    notify_status(
        "AFK",
        "啟動",
        detail=f"accounts={total_accounts}, force={args.force}, config={config_path or 'default'}",
        enabled=notify_enabled,
    )
    
    python_exe = sys.executable
    run_router_script = Path(__file__).parent / "integration_task" / "run_router.py"

    try:
        controller = DeviceController()
        if not controller.connect():
             print("❌ 無法連線至 ADB 裝置")
             notify_status("AFK", "ADB 連線失敗", enabled=notify_enabled)
             sys.exit(1)
        matcher = VisionMatcher()
        detector = SceneDetector(matcher)
        recovery = UIRecovery(controller, matcher, detector)
    except Exception as e:
        print(f"❌ 初始化 UIRecovery 失敗: {e}")
        notify_status("AFK", "初始化失敗", detail=str(e), enabled=notify_enabled)
        sys.exit(1)

    try:
        if delay_seconds > 0:
            print(f"\n⏳ [延遲啟動] 將先等待 {delay_label} ({int(delay_seconds)} 秒)")
            print(f"⏰ 預計啟動時間: {wake_time.strftime('%Y-%m-%d %H:%M:%S')}")
            notify_status(
                "AFK",
                "延遲啟動",
                detail=f"{delay_label}; wake={wake_time.strftime('%Y-%m-%d %H:%M:%S')}",
                enabled=notify_enabled,
            )
            time.sleep(delay_seconds)

        configured_tasks, date_key, completion_state = load_runtime_task_state()

        if not configured_tasks:
            print("⚠️ [提示] afk_tasks.ini 目前沒有任何 enable=Y 的任務，直接結束。")
            notify_status("AFK", "無任務", detail="afk_tasks.ini 沒有 enable=Y", enabled=notify_enabled)
            return

        print(f"📌 載入任務設定成功！本次將執行: {', '.join(configured_tasks)}")
        if config_path:
            print(f"📌 使用指定任務設定檔: {config_path}")
        print(f"📌 今日完成紀錄: {completion_file_for_date(date_key)}")
        notify_status(
            "AFK",
            "任務清單",
            detail=", ".join(configured_tasks),
            enabled=notify_enabled,
        )
        if args.force:
            print("⚠️ 已啟用 --force，將忽略今日完成紀錄並強制執行。")

        print("\n🌅 開始任務前檢查異地登入與登入畫面...")
        if recovery.handle_wakeup_exceptions():
            print("✅ 登入異常狀態已排除，確認返回主城。")
            if not recovery.recover_to_main(max_attempts=20):
                print("❌ [錯誤] 處理登入異常後仍無法回到主城。")
                sys.exit(1)

        current_account = detect_current_account(controller, matcher)
        account_order = build_account_execution_order(
            ACCOUNTS,
            current_account,
            completion_state,
            configured_tasks,
            force=args.force,
        )
        accounts_per_round = len(account_order)

        if not account_order:
            print("✅ 今日所有帳號的 route 都已完成，沒有需要切換或執行的帳號。")
            notify_status(
                "AFK",
                "全部已完成",
                detail="沒有需要切換或執行的帳號",
                enabled=notify_enabled,
            )
            return

        for i, account_name in enumerate(account_order):
            pending_tasks = pending_tasks_for_account(
                completion_state,
                account_name,
                configured_tasks,
                force=args.force,
            )

            if not pending_tasks:
                print("\n" + "="*50)
                print(f"⏭️  跳過帳號 【{account_name}】：今日所有 route 已完成。")
                print("="*50 + "\n")
                notify_status(
                    "AFK",
                    "跳過",
                    account=account_name,
                    detail="今日所有 route 已完成",
                    enabled=notify_enabled,
                )
                continue

            print("\n" + "="*50)
            print(f"🚀 開始執行 ({i+1}/{accounts_per_round}): 帳號 【{account_name}】")
            print(f"📌 待執行 route: {', '.join(pending_tasks)}")
            print("="*50 + "\n")
            
            try:
                if current_account != account_name:
                    print(f"\n⏳ 準備切換至帳號 【{account_name}】...")
                    notify_status(
                        "AFK",
                        "切換帳號開始",
                        account=account_name,
                        enabled=notify_enabled,
                    )
                    switch_cmd = [python_exe, "-m", "switch_account.switch_account", account_name]
                    print("-" * 50)
                    print("🛠️ [Debug] 若切換帳號卡住，可手動在終端機貼上以下指令重新測試帳號切換：")
                    print(f">>> {' '.join(switch_cmd)}")
                    print("-" * 50 + "\n")

                    success = switch_account(account_name)
                    if not success:
                        print(f"\n❌ [錯誤] 切換至帳號 【{account_name}】 失敗！")
                        print("⚠️ [Fail-Fast] 切換失敗，立刻終止整支程式。")
                        notify_status(
                            "AFK",
                            "切換帳號失敗",
                            account=account_name,
                            enabled=notify_enabled,
                        )
                        sys.exit(1)
                    current_account = account_name
                    print("🎉 帳號切換成功！")
                    notify_status(
                        "AFK",
                        "切換帳號完成",
                        account=account_name,
                        enabled=notify_enabled,
                    )

                # 1. 執行掛機任務
                for task_name in pending_tasks:
                    notify_status(
                        "AFK",
                        "開始",
                        account=account_name,
                        route=task_name,
                        enabled=notify_enabled,
                    )
                    task_cmd = [python_exe, str(run_router_script), task_name]
                    if args.debug_actions:
                        task_cmd.append("--debug-actions")
                    if args.force_subprocess:
                        task_cmd.append("--force-subprocess")
                    route_log_file = build_route_log_file(
                        args.log_dir,
                        account_name=account_name,
                        task_name=task_name,
                    )
                    if route_log_file is not None:
                        task_cmd.extend(["--log-file", str(route_log_file)])
                    print("\n" + "-" * 50)
                    print("🛠️ [Debug] 若此 Router 任務卡住，可複製以下指令單獨測試：")
                    print(f">>> {' '.join(task_cmd)}")
                    print("-" * 50 + "\n")
                    
                    child_env = os.environ.copy()
                    result = subprocess.run(task_cmd, cwd=str(PROJECT_ROOT), env=child_env)
                    if result.returncode != 0:
                        print(f"\n❌ [錯誤] 帳號 【{account_name}】 的任務 【{task_name}】 回傳了非零錯誤碼 ({result.returncode})！")
                        print("⚠️ [Fail-Fast] 發生異常，立刻終止整支程式，不切換帳號以保留現場。")
                        notify_status(
                            "AFK",
                            "失敗",
                            account=account_name,
                            route=task_name,
                            detail=f"returncode={result.returncode}",
                            enabled=notify_enabled,
                        )
                        sys.exit(1)
                    else:
                        mark_route_completed(completion_state, account_name, task_name)
                        print(f"✅ 帳號 【{account_name}】 的任務 【{task_name}】 順利完成，已寫入今日完成紀錄！")
                        notify_status(
                            "AFK",
                            "完成",
                            account=account_name,
                            route=task_name,
                            enabled=notify_enabled,
                        )
                            
                print("🔍 子任務結束，交由 UIRecovery 強制驗證主城狀態...")
                if not recovery.recover_to_main():
                    print("⚠️ [系統] 畫面卡死或無法自動回到主城。啟動浴火重生(強制重啟)機制...")
                    try:
                        # 1. 強制關閉遊戲
                        recovery.controller.shell(["am", "force-stop", "com.ageofeternity.global"])
                        time.sleep(3)
                        # 2. 重新啟動遊戲
                        recovery.controller.shell(
                            ["monkey", "-p", "com.ageofeternity.global", "-c", "android.intent.category.LAUNCHER", "1"]
                        )
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
                    
            except SystemExit:
                raise
            except Exception as e:
                print(f"\n❌ 執行時發生未預期的例外:")
                traceback.print_exc()
                print("\n⚠️ [Fail-Fast] 發生崩潰，立刻終止整支程式！")
                notify_status(
                    "AFK",
                    "崩潰",
                    detail=str(e),
                    enabled=notify_enabled,
                )
                sys.exit(1)
    except KeyboardInterrupt:
        print("\n🛑 [中止] 接收到手動中斷指令 (Ctrl+C)，已安全退出掛機腳本。")
        sys.exit(0)

    print("\n✅ 所有帳號掛機大循環執行完畢！工作結束！")
    notify_status("AFK", "全部完成", enabled=notify_enabled)

if __name__ == "__main__":
    main()
