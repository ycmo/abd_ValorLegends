import sys
import time
import argparse
import json
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timedelta

try:
    from AwayFromKeyboard.time_utils import smart_sleep
except ModuleNotFoundError:
    from time_utils import smart_sleep

# 強制設定輸出為 UTF-8，以防在 Windows 終端機顯示中文出錯
sys.stdout.reconfigure(encoding='utf-8')

# 確保專案根目錄在 sys.path 中
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from switch_account.switch_account import detect_current_account, switch_account, load_accounts
from src.daily_runner import build_context
from src.exceptions import BotError, TaskFailedError
from src.account_state import TAIPEI_TZ, clear_activity_state, write_activity_state, write_current_account
from src.tasks.midas import MidasAutoResult, MidasTask
from src.vision_matcher import write_image
from AwayFromKeyboard.ui_recovery import UIRecovery
from AwayFromKeyboard.integration_task.router import RouteNavigator
from AwayFromKeyboard.discord_notify import notify_status
from AwayFromKeyboard.afk_daily import (
    DEFAULT_STUCK_PROBE_INTERVAL_SECONDS,
    DEFAULT_STUCK_PROBE_SECONDS,
    DEFAULT_TASK_HARD_TIMEOUT_SECONDS,
    DEFAULT_TASK_TIMEOUT_SECONDS,
    TaskWatchdogConfig,
    build_action_debug_label,
    parse_duration_to_seconds,
    run_with_direct_retry_then_recovery,
    switch_account_with_recovery,
)

AUTO_SHORT_COOLDOWN_SECONDS = 5 * 60
AUTO_OCR_FAILURE_SLEEP_SECONDS = 2 * 60 * 60
AUTO_WAKEUP_BUFFER_SECONDS = 4 * 60
AUTO_ALL_ACCOUNT_ORDER = ("em3", "311", "tiger", "14")
MIDAS_POPUP_RECOVERY_ATTEMPTS = 3
MIDAS_TASK_RETRY_ATTEMPTS = 1
MIDAS_TITLE_ROI = MidasTask.TITLE_ROI
MIDAS_ACTIVITY_NAME = "midas_auto"
DEFAULT_RECOVERY_BLUESTACKS_BOOT_WAIT_SECONDS = 180.0
MIDAS_ACTION_DEBUG_LABEL = "midas"
MIDAS_SCHEDULE_FILE = current_dir / "state" / "midas_schedule.json"
DEFAULT_SWITCH_SECONDS = 3 * 60
DEFAULT_MIDAS_RUN_SECONDS = 60
TIMING_ALPHA = 0.2
MIN_DISCORD_SLEEP_REPORT_SECONDS = 5 * 60
OCR_RETRY_FALLBACK_SECONDS = AUTO_OCR_FAILURE_SLEEP_SECONDS
SAME_ACCOUNT_READY_BIAS_SECONDS = 60
MIDAS_PREPARE_BUFFER_SECONDS = 5 * 60

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


def _taipei_now(now: datetime | None = None) -> datetime:
    current = now or datetime.now(TAIPEI_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=TAIPEI_TZ)
    return current.astimezone(TAIPEI_TZ)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TAIPEI_TZ)
    return parsed.astimezone(TAIPEI_TZ)


def _iso_time(value: datetime) -> str:
    return _taipei_now(value).isoformat(timespec="seconds")


def _account_type(accounts: dict, account: str | None) -> str:
    if not account:
        return "unknown"
    return str(accounts.get(account, {}).get("type") or "unknown")


def switch_timing_key(accounts: dict, from_account: str | None, to_account: str) -> str:
    return f"switch_{_account_type(accounts, from_account)}_{_account_type(accounts, to_account)}"


def _default_timing() -> dict:
    return {
        "switch_google_google": {"seconds": DEFAULT_SWITCH_SECONDS, "samples": 0},
        "switch_google_email": {"seconds": DEFAULT_SWITCH_SECONDS, "samples": 0},
        "switch_email_google": {"seconds": DEFAULT_SWITCH_SECONDS, "samples": 0},
        "switch_email_email": {"seconds": DEFAULT_SWITCH_SECONDS, "samples": 0},
        "switch_unknown_google": {"seconds": DEFAULT_SWITCH_SECONDS, "samples": 0},
        "switch_unknown_email": {"seconds": DEFAULT_SWITCH_SECONDS, "samples": 0},
        "midas_run": {"seconds": DEFAULT_MIDAS_RUN_SECONDS, "samples": 0},
    }


def load_midas_schedule(path: Path = MIDAS_SCHEDULE_FILE) -> dict:
    path = Path(path)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    else:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("accounts", {})
    data.setdefault("timing", {})
    defaults = _default_timing()
    for key, value in defaults.items():
        data["timing"].setdefault(key, value.copy())
    return data


def save_midas_schedule(schedule: dict, path: Path = MIDAS_SCHEDULE_FILE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(schedule, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(path)
    return path


def timing_seconds(schedule: dict, key: str, default_seconds: float) -> float:
    item = schedule.get("timing", {}).get(key, {})
    try:
        return float(item.get("seconds", default_seconds))
    except (TypeError, ValueError):
        return float(default_seconds)


def switch_estimate_seconds(schedule: dict, accounts: dict, from_account: str | None, to_account: str) -> float:
    if from_account == to_account:
        return 0.0
    return timing_seconds(schedule, switch_timing_key(accounts, from_account, to_account), DEFAULT_SWITCH_SECONDS)


def midas_estimate_seconds(schedule: dict) -> float:
    return timing_seconds(schedule, "midas_run", DEFAULT_MIDAS_RUN_SECONDS)


def update_timing_average(schedule: dict, key: str, measured_seconds: float) -> None:
    measured = max(0.0, float(measured_seconds))
    timing = schedule.setdefault("timing", {})
    item = timing.setdefault(key, {"seconds": measured, "samples": 0})
    samples = int(item.get("samples") or 0)
    if samples <= 0:
        item["seconds"] = measured
    else:
        old = float(item.get("seconds", measured))
        item["seconds"] = old * (1.0 - TIMING_ALPHA) + measured * TIMING_ALPHA
    item["samples"] = samples + 1


def update_account_schedule(
    schedule: dict,
    account: str,
    result: MidasAutoResult,
    *,
    now: datetime | None = None,
    source: str,
) -> datetime:
    current = _taipei_now(now)
    cooldown = result.cooldown_seconds if result.cooldown_valid else OCR_RETRY_FALLBACK_SECONDS
    ready_at = current + timedelta(seconds=max(0, int(cooldown or 0)))
    account_state = schedule.setdefault("accounts", {}).setdefault(account, {})
    account_state.update(
        {
            "updated_at": _iso_time(current),
            "ready_at": _iso_time(ready_at),
            "cooldown_seconds": int(cooldown or 0),
            "cooldown_source": source,
            "ocr_text": result.ocr_text,
            "ocr_confidence": result.ocr_confidence,
            "last_result": "clicked" if result.clicked else "cooldown",
        }
    )
    return ready_at


def account_ready_at(schedule: dict, account: str, *, now: datetime | None = None) -> datetime:
    ready_at = _parse_time(schedule.get("accounts", {}).get(account, {}).get("ready_at"))
    return ready_at or _taipei_now(now)


def schedule_entries(schedule: dict, accounts_order: list[str], *, now: datetime | None = None) -> list[tuple[str, datetime]]:
    current = _taipei_now(now)
    return [(account, account_ready_at(schedule, account, now=current)) for account in accounts_order]


def choose_next_account(
    schedule: dict,
    accounts: dict,
    accounts_order: list[str],
    current_account: str | None,
    *,
    now: datetime | None = None,
) -> tuple[str, datetime, float]:
    current = _taipei_now(now)
    midas_estimate = midas_estimate_seconds(schedule)
    best: tuple[datetime, int, str, float, datetime] | None = None
    for order_index, account in enumerate(accounts_order):
        switch_estimate = switch_estimate_seconds(schedule, accounts, current_account, account)
        ready_at = account_ready_at(schedule, account, now=current)
        start_at = max(ready_at, current + timedelta(seconds=switch_estimate))
        finish_at = start_at + timedelta(seconds=midas_estimate)
        candidate = (finish_at, order_index, account, switch_estimate, start_at)
        if best is None or candidate < best:
            best = candidate

    assert best is not None
    _, _, selected, switch_estimate, start_at = best
    if current_account in accounts_order and current_account != selected:
        current_ready = account_ready_at(schedule, current_account, now=current)
        current_start = max(current_ready, current)
        selected_start = start_at
        if current_start <= selected_start + timedelta(seconds=SAME_ACCOUNT_READY_BIAS_SECONDS):
            return current_account, current_start, 0.0
    return selected, start_at, switch_estimate


def format_schedule_table(schedule: dict, accounts_order: list[str], *, now: datetime | None = None) -> str:
    current = _taipei_now(now)
    lines = ["Midas schedule:"]
    account_width = max((len(account) for account in accounts_order), default=0)
    for account, ready_at in sorted(schedule_entries(schedule, accounts_order, now=current), key=lambda item: item[1]):
        delta = max(0, int((ready_at - current).total_seconds()))
        lines.append(f"- {account:<{account_width}} : ready {ready_at.strftime('%H:%M:%S')} ({_format_seconds(delta)})")
    return "\n".join(lines)


def format_schedule_decision(
    schedule: dict,
    accounts: dict,
    accounts_order: list[str],
    current_account: str | None,
    *,
    now: datetime | None = None,
) -> str:
    current = _taipei_now(now)
    lines = ["Midas schedule from file:"]
    account_width = max((len(account) for account in accounts_order), default=0)
    for account in accounts_order:
        account_state = schedule.get("accounts", {}).get(account, {})
        ready_at = _parse_time(account_state.get("ready_at"))
        if ready_at is None:
            lines.append(f"- {account:<{account_width}} : no ready_at; treated ready now")
            continue
        delta = max(0, int((ready_at - current).total_seconds()))
        lines.append(
            f"- {account:<{account_width}} : ready = {ready_at.strftime('%Y-%m-%d %H:%M:%S')} "
            f"({_format_seconds(delta)})"
        )
    selected, start_at, switch_estimate = choose_next_account(
        schedule,
        accounts,
        accounts_order,
        current_account,
        now=current,
    )
    wake_at = calculate_midas_wake_at(current, start_at, switch_estimate)
    sleep_seconds = max(0, int((wake_at - current).total_seconds()))
    wait_after_wake = max(0, int((start_at - wake_at).total_seconds()))
    lines.extend(
        [
            "Midas strategy:",
            (
                f"current={current_account or 'unknown'} next={selected}; "
                f"wake={wake_at.strftime('%Y-%m-%d %H:%M:%S')}; "
                f"start={start_at.strftime('%Y-%m-%d %H:%M:%S')}"
            ),
            (
                f"sleep={_format_seconds(sleep_seconds)}; "
                f"prepare/wait={_format_seconds(wait_after_wake)}; "
                f"switch_est={_format_seconds(switch_estimate)}"
            ),
        ]
    )
    return "\n".join(lines)


def calculate_midas_wake_at(now: datetime, start_at: datetime, switch_estimate_seconds: float) -> datetime:
    prepare_seconds = max(0, switch_estimate_seconds) + MIDAS_PREPARE_BUFFER_SECONDS
    return max(now, start_at - timedelta(seconds=prepare_seconds))


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


def _handle_wakeup_exceptions_if_available(recovery) -> bool:
    handler = getattr(recovery, "handle_wakeup_exceptions", None)
    if handler is None:
        return False
    return bool(
        run_with_direct_retry_then_recovery(
            handler,
            label="wakeup exception check",
            retry_exceptions=(BotError,),
            direct_retries=1,
            recovery_action=lambda: _recover_or_restart(recovery),
        )
    )


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


def rotate_midas_action_debug_dir_if_new_day(context) -> None:
    controller = getattr(context, "controller", None)
    if controller is None or not getattr(controller, "debug_actions", False):
        return

    today = datetime.now(TAIPEI_TZ).strftime("%Y%m%d")
    state = getattr(context, "_midas_action_debug_rotation_state", None)
    if state is None:
        state = {}
        try:
            setattr(context, "_midas_action_debug_rotation_state", state)
        except Exception:
            return

    if state.get("date") == today:
        return

    reset_debug_dir = getattr(controller, "reset_action_debug_dir", None)
    if reset_debug_dir is None:
        return

    debug_dir = reset_debug_dir(MIDAS_ACTION_DEBUG_LABEL)
    state["date"] = today
    print(f"[debug] Midas action_debug_dir={debug_dir}")


@contextmanager
def midas_task_debug_actions(context, enabled: bool):
    controller = getattr(context, "controller", None)
    if enabled or controller is None or not hasattr(controller, "debug_actions"):
        yield
        return

    original = controller.debug_actions
    controller.debug_actions = False
    try:
        yield
    finally:
        controller.debug_actions = original


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
            _execute_route_enter_with_recovery(context, recovery, route)

    raise AssertionError("unreachable")


def _execute_route_enter_with_recovery(context, recovery: UIRecovery, route) -> None:
    for recovery_count in range(MIDAS_POPUP_RECOVERY_ATTEMPTS + 1):
        try:
            route.execute_route(phase="enter")
            return
        except Exception:
            if recovery_count >= MIDAS_POPUP_RECOVERY_ATTEMPTS:
                raise
            attempt = recovery_count + 1
            try:
                screen = context.controller.screenshot()
                _save_midas_popup_recovery_debug(context, screen, attempt)
                route.handle_blocking_popup(screen)
            except Exception as exc:
                print(f"?? [Midas] route enter recovery screenshot/popup handling failed: {exc}")

            print(
                f"?? [Midas] route enter failed; restarting/recovering before retry "
                f"({attempt}/{MIDAS_POPUP_RECOVERY_ATTEMPTS})"
            )
            _recover_or_restart(recovery)

    raise AssertionError("unreachable")


def run_midas_auto_once(
    context,
    recovery: UIRecovery,
    *,
    require_cooldown: bool,
    midas_debug_actions: bool = False,
) -> MidasAutoResult:
    route = RouteNavigator(route_name="點金手", controller=context.controller)
    _execute_route_enter_with_recovery(context, recovery, route)
    try:
        return _execute_midas_with_popup_recovery(
            context,
            recovery,
            route,
            lambda: _execute_midas_auto_task(
                context,
                require_cooldown=require_cooldown,
                midas_debug_actions=midas_debug_actions,
            ),
        )
    finally:
        try:
            route.execute_route(phase="exit")
        finally:
            _recover_or_restart(recovery)


def run_midas_auto_with_ocr_retry(
    context,
    recovery: UIRecovery,
    *,
    account: str,
    notify_enabled: bool,
    midas_debug_actions: bool = False,
) -> MidasAutoResult:
    first = run_midas_auto_once(
        context,
        recovery,
        require_cooldown=True,
        midas_debug_actions=midas_debug_actions,
    )
    if first.cooldown_valid:
        return first

    print(
        "⚠️ [Auto] 點金手冷卻 OCR 第一次失敗，將離開後重新進入再讀一次："
        f"account={account}, text={first.ocr_text!r}, confidence={first.ocr_confidence:.3f}"
    )
    notify_status(
        "Midas",
        "OCR retry",
        account=account,
        route="點金手",
        detail=f"first text={first.ocr_text!r}, conf={first.ocr_confidence:.3f}",
        enabled=notify_enabled,
    )
    second = run_midas_auto_once(
        context,
        recovery,
        require_cooldown=True,
        midas_debug_actions=midas_debug_actions,
    )
    if second.cooldown_valid:
        return second

    detail = (
        f"🚨 OCR failed twice; account={account}; "
        f"first text={first.ocr_text!r} conf={first.ocr_confidence:.3f}; "
        f"second text={second.ocr_text!r} conf={second.ocr_confidence:.3f}; "
        f"fallback={_format_seconds(OCR_RETRY_FALLBACK_SECONDS)}"
    )
    print(detail)
    notify_status(
        "Midas",
        "🚨 OCR failed twice",
        account=account,
        route="點金手",
        detail=detail,
        enabled=notify_enabled,
    )
    return second


def _execute_midas_auto_task(
    context,
    *,
    require_cooldown: bool,
    midas_debug_actions: bool,
) -> MidasAutoResult:
    with midas_task_debug_actions(context, midas_debug_actions):
        return MidasTask(context).execute_auto(
            require_cooldown_after_success=require_cooldown
        )


def _execute_midas_task(context, *, midas_debug_actions: bool) -> str:
    with midas_task_debug_actions(context, midas_debug_actions):
        return MidasTask(context).execute()


def run_midas_once(context, recovery: UIRecovery, *, midas_debug_actions: bool = False) -> str:
    route = RouteNavigator(route_name="點金手", controller=context.controller)
    _execute_route_enter_with_recovery(context, recovery, route)
    try:
        result = _execute_midas_with_popup_recovery(
            context,
            recovery,
            route,
            lambda: _execute_midas_task(context, midas_debug_actions=midas_debug_actions),
        )
        print(f"✅ [AFKMidas] 點金手執行完成：{result}")
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


def process_auto_account(
    context,
    recovery: UIRecovery,
    account: str,
    *,
    notify_enabled: bool = False,
    midas_debug_actions: bool = False,
) -> bool:
    while True:
        print(f"\n💰 [Auto] 執行帳號 【{account}】 點金手")
        notify_status("Midas", "開始", account=account, route="點金手", enabled=notify_enabled)
        result = run_midas_auto_once(
            context,
            recovery,
            require_cooldown=False,
            midas_debug_actions=midas_debug_actions,
        )
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
        smart_sleep(wait_seconds)
        print("🌅 [Auto] 短冷卻結束，檢查異地登入與登入畫面...")
        if _handle_wakeup_exceptions_if_available(recovery):
            print("✅ [Auto] 短冷卻喚醒異常狀態已排除。")
        _recover_or_restart(recovery)


def _read_em3_sleep_seconds(
    context,
    recovery: UIRecovery,
    *,
    notify_enabled: bool = False,
    midas_debug_actions: bool = False,
) -> int:
    print("\n🔎 [Auto] 已回到 em3，讀取大休眠冷卻時間...")
    final_result = run_midas_auto_once(
        context,
        recovery,
        require_cooldown=True,
        midas_debug_actions=midas_debug_actions,
    )
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


def robust_switch_account(
    account_name: str,
    recovery: UIRecovery,
    max_retries: int = 2,
    *,
    recover_account_switch: bool = False,
    task_timeout_seconds: float = DEFAULT_TASK_TIMEOUT_SECONDS,
    hard_timeout_seconds: float = DEFAULT_TASK_HARD_TIMEOUT_SECONDS,
    stuck_probe_seconds: float = DEFAULT_STUCK_PROBE_SECONDS,
    stuck_probe_interval_seconds: float = DEFAULT_STUCK_PROBE_INTERVAL_SECONDS,
    bluestacks_boot_wait_seconds: float = DEFAULT_RECOVERY_BLUESTACKS_BOOT_WAIT_SECONDS,
) -> bool:
    """
    附帶崩潰重啟機制的帳號切換包裝函數。
    如果切換時卡死或失敗，將自動重啟遊戲並回到主城後再重試。
    """
    if recover_account_switch:
        watchdog = TaskWatchdogConfig(
            enabled=True,
            task_timeout_seconds=task_timeout_seconds,
            hard_timeout_seconds=hard_timeout_seconds,
            stuck_probe_seconds=stuck_probe_seconds,
            stuck_probe_interval_seconds=stuck_probe_interval_seconds,
            debug_label=build_action_debug_label(account_name, "midas_switch_account"),
        )
        success, stage = switch_account_with_recovery(
            account_name=account_name,
            switch_cmd=[sys.executable, "-m", "switch_account.switch_account", account_name],
            recovery=recovery,
            enabled=True,
            bluestacks_boot_wait_seconds=bluestacks_boot_wait_seconds,
            watchdog=watchdog,
        )
        if not success:
            print(f"?? [Auto] ??撣唾? {account_name} recovery 憭望?: {stage}")
        return success

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                print(f"🔄 [Auto] 嘗試切換帳號 {account_name} (第 {attempt + 1}/{max_retries} 次)...")
            if switch_account(account_name):
                return True
            print(f"⚠️ [Auto] 切換帳號 {account_name} 回傳 False。")
        except Exception as e:
            print(f"⚠️ [Auto] 切換帳號 {account_name} 時發生異常: {e}")
            
        if attempt < max_retries - 1:
            print("🔄 [Auto] 準備強制重啟遊戲並重新嘗試切換...")
            if recovery.restart_game_app_and_reenter():
                print("✅ [Auto] 遊戲重啟成功，回到主畫面，準備重試帳號切換。")
            else:
                print("❌ [Auto] 遊戲重啟失敗！")
                
    return False


def switch_to_account_if_needed(
    target_account: str,
    *,
    active_account: str | None,
    accounts: dict,
    recovery: UIRecovery,
    schedule: dict,
    notify_enabled: bool,
    switch_recovery_options: dict | None,
) -> str:
    if active_account == target_account:
        return target_account

    print(f"🔄 [Auto] 切換至帳號 【{target_account}】")
    notify_status("Midas", "切換帳號開始", account=target_account, enabled=notify_enabled)
    _refresh_midas_activity("midas.auto.before_switch")
    timing_key = switch_timing_key(accounts, active_account, target_account)
    started = time.monotonic()
    if not robust_switch_account(target_account, recovery, **(switch_recovery_options or {})):
        raise RuntimeError(f"切換至帳號 {target_account} 失敗")
    elapsed = time.monotonic() - started
    update_timing_average(schedule, timing_key, elapsed)
    save_midas_schedule(schedule)
    timing_item = schedule.get("timing", {}).get(timing_key, {})
    average_seconds = timing_seconds(schedule, timing_key, elapsed)
    samples = int(timing_item.get("samples") or 0)
    _record_current_account(target_account, "afk.midas.switch")
    notify_status(
        "Midas",
        "切換帳號完成",
        account=target_account,
        detail=(
            f"{timing_key} measured={_format_seconds(elapsed)}; "
            f"avg={_format_seconds(average_seconds)}; samples={samples}"
        ),
        enabled=notify_enabled,
    )
    print(
        f"⏱️ [Auto] 切換耗時已更新: {timing_key} "
        f"measured={_format_seconds(elapsed)}, avg={_format_seconds(average_seconds)}, samples={samples}"
    )
    return target_account


def execute_scheduled_midas_account(
    context,
    recovery: UIRecovery,
    *,
    account: str,
    schedule: dict,
    notify_enabled: bool,
    midas_debug_actions: bool,
) -> MidasAutoResult:
    print(f"\n💰 [Auto] 排程執行帳號 【{account}】 點金手")
    notify_status("Midas", "開始", account=account, route="點金手", enabled=notify_enabled)
    started = time.monotonic()
    def _run_midas_action() -> MidasAutoResult:
        return run_midas_auto_with_ocr_retry(
            context,
            recovery,
            account=account,
            notify_enabled=notify_enabled,
            midas_debug_actions=midas_debug_actions,
        )

    def _notify_direct_retry(exc: BaseException, attempt: int, total: int) -> None:
        notify_status(
            "Midas",
            "task retry",
            account=account,
            route="midas",
            detail=f"retrying same account after error ({attempt}/{total}): {exc}",
            enabled=notify_enabled,
        )

    def _notify_recovery(exc: BaseException) -> None:
        notify_status(
            "Midas",
            "task recovery",
            account=account,
            route="midas",
            detail=f"direct retry failed; recovering then retrying same account: {exc}",
            enabled=notify_enabled,
        )

    def _notify_failure(exc: BaseException) -> None:
        notify_status(
            "Midas",
            "failed",
            account=account,
            route="midas",
            detail=f"Midas task failed after direct retry and recovery: {exc}",
            enabled=notify_enabled,
        )

    result = run_with_direct_retry_then_recovery(
        _run_midas_action,
        label="Midas task",
        retry_exceptions=(BotError,),
        direct_retries=MIDAS_TASK_RETRY_ATTEMPTS,
        recovery_action=lambda: _recover_or_restart(recovery),
        on_retry=_notify_direct_retry,
        on_recovery=_notify_recovery,
        on_failure=_notify_failure,
    )
    elapsed = time.monotonic() - started
    update_timing_average(schedule, "midas_run", elapsed)
    source = "ocr" if result.cooldown_valid else "ocr_failed_fallback"
    ready_at = update_account_schedule(schedule, account, result, source=source)
    save_midas_schedule(schedule)
    timing_item = schedule.get("timing", {}).get("midas_run", {})
    run_average = timing_seconds(schedule, "midas_run", elapsed)
    run_samples = int(timing_item.get("samples") or 0)
    print(
        f"⏱️ [Auto] 點金耗時與冷卻已更新: account={account}, "
        f"ready={ready_at.strftime('%Y-%m-%d %H:%M:%S')}, "
        f"run={_format_seconds(elapsed)}, avg={_format_seconds(run_average)}, samples={run_samples}"
    )
    if result.clicked:
        status = "完成"
    elif result.cooldown_valid:
        status = "冷卻中"
    else:
        status = "OCR fallback"
    notify_status(
        "Midas",
        status,
        account=account,
        route="點金手",
        detail=f"ready={ready_at.strftime('%H:%M:%S')}; run={_format_seconds(elapsed)}",
        enabled=notify_enabled,
    )
    return result


def sweep_all_accounts_for_schedule(
    context,
    recovery: UIRecovery,
    *,
    accounts: dict,
    accounts_order: list[str],
    schedule: dict,
    notify_enabled: bool,
    switch_recovery_options: dict | None,
    midas_debug_actions: bool,
) -> str | None:
    print(f"🔎 [Auto] sweep-all 建立點金排程資料: {' -> '.join(accounts_order)}")
    current_account = detect_current_account(context.controller, context.matcher)
    _record_current_account(current_account, "afk.midas.detect.sweep_all")
    active_account = current_account
    for account in accounts_order:
        active_account = switch_to_account_if_needed(
            account,
            active_account=active_account,
            accounts=accounts,
            recovery=recovery,
            schedule=schedule,
            notify_enabled=notify_enabled,
            switch_recovery_options=switch_recovery_options,
        )
        execute_scheduled_midas_account(
            context,
            recovery,
            account=account,
            schedule=schedule,
            notify_enabled=notify_enabled,
            midas_debug_actions=midas_debug_actions,
        )
    return active_account


def sleep_until_next_midas(
    schedule: dict,
    accounts: dict,
    accounts_order: list[str],
    current_account: str | None,
    *,
    notify_enabled: bool,
) -> None:
    now = _taipei_now()
    next_account, start_at, switch_estimate = choose_next_account(
        schedule,
        accounts,
        accounts_order,
        current_account,
        now=now,
    )
    wake_at = calculate_midas_wake_at(now, start_at, switch_estimate)
    sleep_seconds = max(0, int((wake_at - now).total_seconds()))
    _clear_midas_activity_active("midas.auto.smart_sleep", wake_at=wake_at)
    decision = format_schedule_decision(schedule, accounts, accounts_order, current_account, now=now)
    print(decision)
    prepare_seconds = max(0, int((start_at - wake_at).total_seconds()))
    print(
        f"💤 [Auto] 下一個帳號 {next_account}，預計 {wake_at.strftime('%Y-%m-%d %H:%M:%S')} 醒來準備；"
        f"{start_at.strftime('%Y-%m-%d %H:%M:%S')} 開始點金；"
        f"提早 {_format_seconds(prepare_seconds)}；睡眠 {_format_seconds(sleep_seconds)}。"
    )
    if sleep_seconds >= MIN_DISCORD_SLEEP_REPORT_SECONDS:
        notify_status(
            "Midas",
            "進入智能休眠",
            account=next_account,
            detail=(
                f"wake_at={wake_at.strftime('%Y-%m-%d %H:%M:%S')}; "
                f"start_at={start_at.strftime('%Y-%m-%d %H:%M:%S')}; "
                f"prepare={_format_seconds(prepare_seconds)}; "
                f"sleep={_format_seconds(sleep_seconds)}; "
                f"switch_est={_format_seconds(switch_estimate)}\n{decision}"
            ),
            enabled=notify_enabled,
        )
    smart_sleep(sleep_seconds)


def wait_until_scheduled_midas_start(start_at: datetime, *, notify_enabled: bool) -> None:
    now = _taipei_now()
    wait_seconds = max(0, int((start_at - now).total_seconds()))
    if wait_seconds <= 0:
        return
    _refresh_midas_activity("midas.auto.pre_ready_sleep")
    print(
        f"⏳ [Auto] 已提前完成準備，等待 {_format_seconds(wait_seconds)} "
        f"至 {start_at.strftime('%Y-%m-%d %H:%M:%S')} 再點金。"
    )
    if wait_seconds >= MIN_DISCORD_SLEEP_REPORT_SECONDS:
        notify_status(
            "Midas",
            "提前就位等待",
            detail=f"wait={_format_seconds(wait_seconds)}; start={start_at.strftime('%Y-%m-%d %H:%M:%S')}",
            enabled=notify_enabled,
        )
    smart_sleep(wait_seconds)


def run_auto_initial_round(
    context,
    recovery: UIRecovery,
    *,
    notify_enabled: bool = False,
    switch_recovery_options: dict | None = None,
    midas_debug_actions: bool = False,
) -> int:
    print("\n🌅 [Auto] 初始輪啟動，先檢查異地登入與登入畫面...")
    if _handle_wakeup_exceptions_if_available(recovery):
        print("✅ [Auto] 初始輪喚醒異常狀態已排除。")
    _recover_or_restart(recovery)

    current_account = detect_current_account(context.controller, context.matcher)
    _record_current_account(current_account, "afk.midas.detect.initial")
    current_label = current_account or "目前帳號"
    print(
        "\n▶️ [Auto] 初始輪：先執行當前畫面帳號點金，"
        "再回 em3 讀取第一次大休眠時間。"
    )
    process_auto_account(
        context,
        recovery,
        current_label,
        notify_enabled=notify_enabled,
        midas_debug_actions=midas_debug_actions,
    )

    if current_account != "em3":
        print("🔄 [Auto] 初始輪返回起點帳號 【em3】")
        notify_status("Midas", "切換帳號開始", account="em3", enabled=notify_enabled)
        _refresh_midas_activity("midas.auto.before_switch")
        if not robust_switch_account("em3", recovery, **(switch_recovery_options or {})):
            raise RuntimeError("初始輪返回 em3 失敗")
        _record_current_account("em3", "afk.midas.switch")
        notify_status("Midas", "切換帳號完成", account="em3", enabled=notify_enabled)

    return _read_em3_sleep_seconds(
        context,
        recovery,
        notify_enabled=notify_enabled,
        midas_debug_actions=midas_debug_actions,
    )


def run_auto_sweep_first_round(
    context,
    recovery: UIRecovery,
    *,
    accounts: dict,
    use_all: bool,
    notify_enabled: bool = False,
    switch_recovery_options: dict | None = None,
    midas_debug_actions: bool = False,
) -> int:
    print("\n🌅 [Auto] sweep-first 初始輪啟動，先檢查異地登入與登入畫面...")
    if _handle_wakeup_exceptions_if_available(recovery):
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
            if not robust_switch_account(account, recovery, **(switch_recovery_options or {})):
                raise RuntimeError(f"sweep-first 切換至帳號 {account} 失敗")
            active_account = account
            _record_current_account(account, "afk.midas.switch")
            notify_status("Midas", "切換帳號完成", account=account, enabled=notify_enabled)
        process_auto_account(
            context,
            recovery,
            account,
            notify_enabled=notify_enabled,
            midas_debug_actions=midas_debug_actions,
        )

    if active_account != final_account:
        print(f"🔄 [Auto] sweep-first 返回起點帳號 【{final_account}】")
        notify_status("Midas", "切換帳號開始", account=final_account, enabled=notify_enabled)
        _refresh_midas_activity("midas.auto.before_switch")
        if not robust_switch_account(final_account, recovery, **(switch_recovery_options or {})):
            raise RuntimeError(f"sweep-first 返回 {final_account} 失敗")
        _record_current_account(final_account, "afk.midas.switch")
        notify_status("Midas", "切換帳號完成", account=final_account, enabled=notify_enabled)

    return _read_em3_sleep_seconds(
        context,
        recovery,
        notify_enabled=notify_enabled,
        midas_debug_actions=midas_debug_actions,
    )


def run_auto_round(
    context,
    recovery: UIRecovery,
    *,
    accounts: dict,
    use_all: bool,
    notify_enabled: bool = False,
    switch_recovery_options: dict | None = None,
    midas_debug_actions: bool = False,
) -> int:
    print("\n🌅 [Auto] 新一輪啟動，先檢查異地登入與登入畫面...")
    if _handle_wakeup_exceptions_if_available(recovery):
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
            if not robust_switch_account(account, recovery, **(switch_recovery_options or {})):
                raise RuntimeError(f"切換至帳號 {account} 失敗")
            active_account = account
            _record_current_account(account, "afk.midas.switch")
            notify_status("Midas", "切換帳號完成", account=account, enabled=notify_enabled)
        process_auto_account(
            context,
            recovery,
            account,
            notify_enabled=notify_enabled,
            midas_debug_actions=midas_debug_actions,
        )

    if active_account != "em3":
        print("🔄 [Auto] 返回起點帳號 【em3】")
        notify_status("Midas", "切換帳號開始", account="em3", enabled=notify_enabled)
        _refresh_midas_activity("midas.auto.before_switch")
        if not robust_switch_account("em3", recovery, **(switch_recovery_options or {})):
            raise RuntimeError("返回 em3 失敗")
        _record_current_account("em3", "afk.midas.switch")
        notify_status("Midas", "切換帳號完成", account="em3", enabled=notify_enabled)

    return _read_em3_sleep_seconds(
        context,
        recovery,
        notify_enabled=notify_enabled,
        midas_debug_actions=midas_debug_actions,
    )


def run_auto_loop(
    context,
    recovery: UIRecovery,
    *,
    use_all: bool,
    sweep_first: bool = False,
    sweep_all: bool = False,
    notify_enabled: bool = False,
    midas_debug_actions: bool = False,
    recover_account_switch: bool = False,
    task_timeout_seconds: float = DEFAULT_TASK_TIMEOUT_SECONDS,
    hard_timeout_seconds: float = DEFAULT_TASK_HARD_TIMEOUT_SECONDS,
    stuck_probe_seconds: float = DEFAULT_STUCK_PROBE_SECONDS,
    stuck_probe_interval_seconds: float = DEFAULT_STUCK_PROBE_INTERVAL_SECONDS,
    bluestacks_boot_wait_seconds: float = DEFAULT_RECOVERY_BLUESTACKS_BOOT_WAIT_SECONDS,
) -> None:
    accounts = load_accounts()
    accounts_order = build_auto_account_order(accounts, use_all)
    schedule = load_midas_schedule()
    switch_recovery_options = {
        "recover_account_switch": recover_account_switch,
        "task_timeout_seconds": task_timeout_seconds,
        "hard_timeout_seconds": hard_timeout_seconds,
        "stuck_probe_seconds": stuck_probe_seconds,
        "stuck_probe_interval_seconds": stuck_probe_interval_seconds,
        "bluestacks_boot_wait_seconds": bluestacks_boot_wait_seconds,
    }
    notify_status(
        "Midas",
        "啟動",
        detail=f"accounts={'all' if use_all else 'em3/311'}, sweep_all={sweep_all or sweep_first}",
        enabled=notify_enabled,
    )
    rotate_midas_action_debug_dir_if_new_day(context)
    current_account: str | None = None
    if sweep_all or sweep_first:
        _set_midas_activity_active("midas.auto.sweep_all.start")
        if _handle_wakeup_exceptions_if_available(recovery):
            print("✅ [Auto] sweep-all 喚醒異常狀態已排除。")
        _recover_or_restart(recovery)
        current_account = sweep_all_accounts_for_schedule(
            context,
            recovery,
            accounts=accounts,
            accounts_order=accounts_order,
            schedule=schedule,
            notify_enabled=notify_enabled,
            switch_recovery_options=switch_recovery_options,
            midas_debug_actions=midas_debug_actions,
        )
        save_midas_schedule(schedule)

    while True:
        rotate_midas_action_debug_dir_if_new_day(context)
        _set_midas_activity_active("midas.auto.smart_round.start")
        if _handle_wakeup_exceptions_if_available(recovery):
            print("✅ [Auto] 喚醒異常狀態已排除。")
        _recover_or_restart(recovery)
        detected_account = detect_current_account(context.controller, context.matcher)
        if detected_account:
            current_account = detected_account
            _record_current_account(current_account, "afk.midas.detect.smart_round")

        now = _taipei_now()
        next_account, start_at, switch_estimate = choose_next_account(
            schedule,
            accounts,
            accounts_order,
            current_account,
            now=now,
        )
        wake_at = calculate_midas_wake_at(now, start_at, switch_estimate)
        if wake_at > now:
            sleep_until_next_midas(
                schedule,
                accounts,
                accounts_order,
                current_account,
                notify_enabled=notify_enabled,
            )
            continue

        print(format_schedule_decision(schedule, accounts, accounts_order, current_account, now=now))
        current_account = switch_to_account_if_needed(
            next_account,
            active_account=current_account,
            accounts=accounts,
            recovery=recovery,
            schedule=schedule,
            notify_enabled=notify_enabled,
            switch_recovery_options=switch_recovery_options,
        )
        wait_until_scheduled_midas_start(start_at, notify_enabled=notify_enabled)
        execute_scheduled_midas_account(
            context,
            recovery,
            account=next_account,
            schedule=schedule,
            notify_enabled=notify_enabled,
            midas_debug_actions=midas_debug_actions,
        )

def main():
    parser = argparse.ArgumentParser(description="AwayFromKeyboard 點金手掛機腳本")
    parser.set_defaults(use_all=True)
    parser.add_argument("--all", dest="use_all", action="store_true", help="自動循環全部帳號 (預設)")
    parser.add_argument("--two-accounts", dest="use_all", action="store_false", help="只循環 em3 與 311")
    parser.add_argument(
        "--sweep-first",
        action="store_true",
        help="相容舊參數；等同 --sweep-all",
    )
    parser.add_argument(
        "--sweep-all",
        action="store_true",
        help="啟動後先全部帳號點金一次，建立 cooldown 與耗時排程資料",
    )
    parser.add_argument(
        "--debug-actions",
        action="store_true",
        help="儲存 Midas loop、route、recovery 每次操作前後的偵錯截圖",
    )
    parser.add_argument(
        "--midas-debug-actions",
        action="store_true",
        help="同時儲存 MidasTask 本體內部操作偵錯截圖",
    )
    parser.add_argument("--no-discord", action="store_true", help="關閉 Discord 狀態通知")
    parser.set_defaults(recover_account_switch=True)
    parser.add_argument("--no-recover-account-switch", dest="recover_account_switch", action="store_false", help="disable account switch recovery")
    parser.add_argument("--task-timeout", default=str(DEFAULT_TASK_TIMEOUT_SECONDS), help="seconds or hh:mm:ss before switch stuck monitor starts")
    parser.add_argument("--task-hard-timeout", default=str(DEFAULT_TASK_HARD_TIMEOUT_SECONDS), help="seconds or hh:mm:ss before the switch subprocess is killed")
    parser.add_argument("--stuck-probe-seconds", type=float, default=DEFAULT_STUCK_PROBE_SECONDS, help="static-screen seconds required to classify switch as stuck")
    parser.add_argument("--stuck-probe-interval", type=float, default=DEFAULT_STUCK_PROBE_INTERVAL_SECONDS, help="seconds between stuck monitor screenshots")
    parser.add_argument("--recovery-bluestacks-boot-wait", type=float, default=DEFAULT_RECOVERY_BLUESTACKS_BOOT_WAIT_SECONDS, help="seconds to wait after BlueStacks restart during account-switch recovery")
    args = parser.parse_args()

    try:
        task_timeout_seconds = parse_duration_to_seconds(args.task_timeout)
        hard_timeout_seconds = parse_duration_to_seconds(args.task_hard_timeout)
        if task_timeout_seconds is None or hard_timeout_seconds is None:
            raise ValueError("task timeout values cannot be empty")
    except ValueError as e:
        print(f"??[?航炊] {e}")
        sys.exit(1)

    if args.use_all:
        try:
            accounts_map = load_accounts()
            accounts_per_round = len(accounts_map)
        except Exception as e:
            print(f"⚠️ [警告] 無法讀取 accounts.json ({e})，預設改為 4 個帳號。")
            accounts_per_round = 4
    else:
        accounts_per_round = 2
        
    print("==================================================")
    print("🔄 開始執行點金手掛機 (AFK Midas)")
    print(f"🔄 循環帳號數: {accounts_per_round}")
    if args.sweep_all or args.sweep_first:
        initial_strategy = "sweep-all then smart schedule"
    else:
        initial_strategy = "smart schedule from saved ready_at"
    print(f"🔄 初始策略: {initial_strategy}")
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
            use_all=args.use_all,
            sweep_first=args.sweep_first,
            sweep_all=args.sweep_all,
            notify_enabled=not args.no_discord,
            midas_debug_actions=args.midas_debug_actions,
            recover_account_switch=args.recover_account_switch,
            task_timeout_seconds=task_timeout_seconds,
            hard_timeout_seconds=hard_timeout_seconds,
            stuck_probe_seconds=args.stuck_probe_seconds,
            stuck_probe_interval_seconds=args.stuck_probe_interval,
            bluestacks_boot_wait_seconds=args.recovery_bluestacks_boot_wait,
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
