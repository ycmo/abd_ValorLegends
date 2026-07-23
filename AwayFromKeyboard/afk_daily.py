import time
import sys
import argparse
import traceback
import subprocess
import json
import os
import re
import shutil
import threading
import cv2
import numpy as np
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from AwayFromKeyboard.time_utils import smart_sleep
except ModuleNotFoundError:
    from time_utils import smart_sleep

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
from src.account_state import read_activity_state, write_current_account
from src.config import LOG_DIR
from src.stdio_utils import configure_utf8_stdio

configure_utf8_stdio()

STATE_DIR = Path(__file__).resolve().parent / "state"
GAME_PACKAGE = "com.ageofeternity.global"
MIDAS_ACTIVITY_NAME = "midas_auto"
MIDAS_ACTIVITY_POLL_SECONDS = 5 * 60
MIDAS_ACTIVE_STALE_SECONDS = 10 * 60
MIDAS_WAKE_GUARD_SECONDS = 20 * 60
MIDAS_WAKE_GRACE_SECONDS = 2 * 60 * 60
MIDAS_TASK_SAFETY_MARGIN_SECONDS = 2 * 60
DEFAULT_TASK_TIMEOUT_SECONDS = 10 * 60
DEFAULT_TASK_HARD_TIMEOUT_SECONDS = 20 * 60
DEFAULT_STUCK_PROBE_SECONDS = 60
DEFAULT_STUCK_PROBE_INTERVAL_SECONDS = 10
STATIC_SCREEN_DIFF_THRESHOLD = 2.0
ROUTE_EXIT_AFTER_COMMAND_SUCCESS_RETURNCODE = 20
MAX_ACTION_DEBUG_LABEL_LENGTH = 80
try:
    TAIPEI_TZ = ZoneInfo("Asia/Taipei")
except ZoneInfoNotFoundError:
    TAIPEI_TZ = timezone(timedelta(hours=8), name="Asia/Taipei")

@dataclass(frozen=True)
class TaskWatchdogConfig:
    enabled: bool
    task_timeout_seconds: float
    hard_timeout_seconds: float
    stuck_probe_seconds: float
    stuck_probe_interval_seconds: float
    debug_label: str | None = None

def parse_delay_to_seconds(delay_str: str) -> float:
    parts = delay_str.split(':')
    if len(parts) != 3:
        raise ValueError(f"時間格式錯誤 '{delay_str}'，請使用 hh:mm:ss")
    h, m, s = [float(part) for part in parts]
    if h < 0 or not 0 <= m < 60 or not 0 <= s < 60:
        raise ValueError(f"時間格式錯誤 '{delay_str}'，請使用 hh:mm:ss")
    return h * 3600 + m * 60 + s

def parse_duration_to_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if ":" in text:
        return parse_delay_to_seconds(text)
    seconds = float(text)
    if seconds < 0:
        raise ValueError(f"duration must be non-negative: {value!r}")
    return seconds

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
    wake_time = now.replace(hour=8, minute=0, second=30, microsecond=0)
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
        label = "到上午 08:00:30"
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
    return STATE_DIR / f"route_completion_{date_key}.jsonc"

def legacy_completion_file_for_date(date_key: str) -> Path:
    return STATE_DIR / f"route_completion_{date_key}.json"

def _strip_jsonc_line_comments(text: str) -> str:
    stripped_lines = []
    for line in text.splitlines():
        in_string = False
        escaped = False
        cut_at = None
        for index in range(len(line) - 1):
            char = line[index]
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = in_string
                continue
            if char == '"':
                in_string = not in_string
                continue
            if not in_string and char == "/" and line[index + 1] == "/":
                cut_at = index
                break
        stripped_lines.append(line if cut_at is None else line[:cut_at].rstrip())
    return "\n".join(stripped_lines)

def _read_completion_jsonc(path: Path) -> dict:
    return json.loads(_strip_jsonc_line_comments(path.read_text(encoding="utf-8")))


class CompletionStateError(RuntimeError):
    pass


def _completion_backup_dir() -> Path:
    return STATE_DIR / "backups"


def _backup_completion_file(path: Path, reason: str) -> Path | None:
    if not path.exists():
        return None
    backup_dir = _completion_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(TAIPEI_TZ).strftime("%Y%m%d_%H%M%S_%f")
    safe_reason = re.sub(r"[^a-zA-Z0-9_.-]+", "_", reason).strip("_") or "backup"
    backup_path = backup_dir / f"{path.stem}_{timestamp}_{safe_reason}{path.suffix}"
    shutil.copy2(path, backup_path)
    return backup_path


def _prune_completion_backups(date_key: str, keep: int = 20) -> None:
    backup_dir = _completion_backup_dir()
    if not backup_dir.exists():
        return
    backups = sorted(
        backup_dir.glob(f"route_completion_{date_key}_*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for old_backup in backups[keep:]:
        old_backup.unlink()


def _dump_completion_jsonc(state: dict) -> str:
    text = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
    lines = text.splitlines()
    completed = state.get("completed") if isinstance(state.get("completed"), dict) else {}
    failed = state.get("failed_this_round") if isinstance(state.get("failed_this_round"), dict) else {}
    account_stack: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        match = re.match(r'"([^"]+)": \{', stripped)
        if match:
            key = match.group(1)
            if key in completed or key in failed:
                account_stack.append(key)
            continue
        if stripped in ("}", "},") and account_stack:
            account = account_stack.pop()
            suffix = "," if stripped.endswith(",") else ""
            lines[index] = f"{line[:-len(suffix)]}{suffix} // account: {account}" if suffix else f"{line} // account: {account}"
    return "\n".join(lines) + "\n"

def load_completion_state(date_key: str) -> dict:
    path = completion_file_for_date(date_key)
    legacy_path = legacy_completion_file_for_date(date_key)
    if not path.exists():
        path = legacy_path if legacy_path.exists() else path
    if not path.exists():
        return {"date": date_key, "completed": {}}
    try:
        data = _read_completion_jsonc(path)
    except json.JSONDecodeError as exc:
        raise CompletionStateError(
            f"完成紀錄格式錯誤，已保留原檔且不會自動重建: {path}; "
            f"line={exc.lineno}, column={exc.colno}, detail={exc.msg}"
        ) from exc
    if data.get("date") != date_key or not isinstance(data.get("completed"), dict):
        raise CompletionStateError(
            f"完成紀錄內容不符合預期，已保留原檔且不會自動重建: {path}; "
            f"expected date={date_key} and completed object"
        )
    return data

def save_completion_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = completion_file_for_date(state["date"])
    if path.exists():
        try:
            _read_completion_jsonc(path)
        except json.JSONDecodeError as exc:
            backup_path = _backup_completion_file(path, "invalid_before_save")
            raise CompletionStateError(
                f"refusing to overwrite invalid completion state: {path}; "
                f"backup={backup_path}; line={exc.lineno}, column={exc.colno}, detail={exc.msg}"
            ) from exc
        _backup_completion_file(path, "before_save")
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(
        _dump_completion_jsonc(state),
        encoding="utf-8",
    )
    tmp_path.replace(path)
    legacy_path = legacy_completion_file_for_date(state["date"])
    if legacy_path.exists():
        _backup_completion_file(legacy_path, "legacy_removed")
        legacy_path.unlink()
    _prune_completion_backups(state["date"])

def is_route_completed(state: dict, account: str, route_name: str) -> bool:
    value = state.get("completed", {}).get(account, {}).get(route_name)
    return bool(value)

def mark_route_completed(state: dict, account: str, route_name: str) -> None:
    completed = state.setdefault("completed", {})
    account_state = completed.setdefault(account, {})
    account_state[route_name] = datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")
    save_completion_state(state)

def clear_failed_this_round(state: dict) -> bool:
    if "failed_this_round" not in state:
        return False
    state.pop("failed_this_round", None)
    save_completion_state(state)
    return True

def clear_stale_failed_this_round_for_new_run(state: dict) -> bool:
    """Clear per-process failure skips left by an earlier AFK invocation."""
    if not clear_failed_this_round(state):
        return False
    print("[AFK recovery] cleared stale failed_this_round entries from previous run")
    return True

def mark_route_failed_this_round(state: dict, account: str, route_name: str, detail: str) -> None:
    failed = state.setdefault("failed_this_round", {})
    account_state = failed.setdefault(account, {})
    account_state[route_name] = {
        "detail": detail,
        "updated_at": datetime.now(TAIPEI_TZ).isoformat(timespec="seconds"),
    }
    save_completion_state(state)

def is_route_failed_this_round(state: dict, account: str, route_name: str) -> bool:
    return bool(state.get("failed_this_round", {}).get(account, {}).get(route_name))

def record_current_account(account: str | None, source: str) -> None:
    if account:
        write_current_account(account, source=source)


def detect_and_record_current_account(
    controller: DeviceController,
    matcher: VisionMatcher,
    source: str,
) -> str | None:
    account = detect_current_account(controller, matcher)
    record_current_account(account, source)
    return account


def replan_account_order_from_detected(
    detected_account: str | None,
    completion_state: dict,
    configured_tasks: list[str],
    *,
    force: bool,
) -> list[str] | None:
    if not detected_account or detected_account not in ACCOUNTS:
        return None
    return build_account_execution_order(
        ACCOUNTS,
        detected_account,
        completion_state,
        configured_tasks,
        force=force,
    )

def pending_tasks_for_account(
    state: dict,
    account: str,
    configured_tasks: list[str],
    *,
    force: bool,
) -> list[str]:
    from AwayFromKeyboard import task_config

    allowed_tasks = [
        task_name
        for task_name in configured_tasks
        if task_config.is_task_allowed_for_account(task_name, account)
    ]
    if force:
        return allowed_tasks
    return [
        task_name
        for task_name in allowed_tasks
        if not is_route_completed(state, account, task_name)
        and not is_route_failed_this_round(state, account, task_name)
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

def build_route_log_file(enabled: bool, *, account_name: str, task_name: str, now: datetime | None = None) -> Path | None:
    if not enabled:
        return None
    current = now or datetime.now(TAIPEI_TZ)
    timestamp = current.strftime("%Y%m%d_%H%M%S")
    filename = f"afk_{timestamp}_{sanitize_log_name(account_name)}_{sanitize_log_name(task_name)}.txt"
    return LOG_DIR / filename

def build_router_argv(
    task_name: str,
    *,
    debug_actions: bool,
    force_subprocess: bool,
    route_log_file: Path | None,
) -> list[str]:
    argv = [task_name]
    if debug_actions:
        argv.append("--debug-actions")
    if force_subprocess:
        argv.append("--force-subprocess")
    if route_log_file is not None:
        argv.extend(["--log-file", str(route_log_file)])
    return argv

def build_action_debug_label(account_name: str, task_name: str, now: datetime | None = None) -> str:
    current = now or datetime.now(TAIPEI_TZ)
    raw = f"afk_{current.strftime('%Y%m%d_%H%M%S')}_{account_name}_{task_name}"
    return re.sub(r"[^\w.-]+", "_", raw, flags=re.UNICODE).strip("._-")[:80]

def build_stage_action_debug_label(base_label: str | None, stage: str) -> str | None:
    if not base_label:
        return None
    suffix = f"_{stage}"
    if len(base_label) + len(suffix) <= MAX_ACTION_DEBUG_LABEL_LENGTH:
        return f"{base_label}{suffix}"
    return f"{base_label[:MAX_ACTION_DEBUG_LABEL_LENGTH - len(suffix)]}{suffix}"

def is_route_exit_after_command_success(returncode: int) -> bool:
    return int(returncode) == ROUTE_EXIT_AFTER_COMMAND_SUCCESS_RETURNCODE

def _reduced_screen_signature(screen: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA)

def _screen_diff_score(previous: np.ndarray, current: np.ndarray) -> float:
    diff = cv2.absdiff(previous, current)
    return float(np.mean(diff))

def terminate_process_tree(process: subprocess.Popen, *, timeout_seconds: float = 30.0) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.kill()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout_seconds)

def rename_action_debug_dirs_for_failure(debug_label: str | None, reason: str) -> list[Path]:
    if not debug_label or not LOG_DIR.exists():
        return []
    safe_reason = re.sub(r"[^A-Za-z0-9_.-]+", "_", reason).strip("_")[:80] or "failure"
    renamed: list[Path] = []
    for path in list(LOG_DIR.iterdir()):
        if not path.is_dir() or debug_label not in path.name or "_fail_" in path.name:
            continue
        target = path.with_name(f"{path.name}_fail_{safe_reason}")
        suffix = 1
        while target.exists():
            target = path.with_name(f"{path.name}_fail_{safe_reason}_{suffix}")
            suffix += 1
        try:
            path.rename(target)
            renamed.append(target)
        except OSError as exc:
            print(f"[AFK recovery] failed to rename debug dir {path}: {exc}")
    return renamed

def rename_latest_stage_action_debug_dir_for_failure(debug_label: str | None, reason: str) -> list[Path]:
    if not debug_label or not LOG_DIR.exists():
        return []
    candidates: list[Path] = []
    for stage in ("route_enter", "task", "route_exit"):
        stage_label = build_stage_action_debug_label(debug_label, stage)
        if not stage_label:
            continue
        candidates.extend(
            path
            for path in LOG_DIR.iterdir()
            if path.is_dir() and stage_label in path.name and "_fail_" not in path.name
        )
    if not candidates:
        return rename_action_debug_dirs_for_failure(debug_label, reason)
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    return rename_action_debug_dirs_for_failure(latest.name, reason)

def rename_router_debug_dirs_for_failure(debug_label: str | None, reason: str, returncode: int) -> list[Path]:
    if is_route_exit_after_command_success(returncode):
        return rename_action_debug_dirs_for_failure(
            build_stage_action_debug_label(debug_label, "route_exit"),
            reason,
        )
    if reason in ("stuck_static", "hard_timeout"):
        return rename_latest_stage_action_debug_dir_for_failure(debug_label, reason)
    return rename_action_debug_dirs_for_failure(
        build_stage_action_debug_label(debug_label, "task"),
        reason,
    )

def run_router_task_subprocess_watchdog(
    *,
    task_cmd: list[str],
    env: dict[str, str],
    watchdog: TaskWatchdogConfig,
    recovery: UIRecovery,
) -> tuple[int, str]:
    process = subprocess.Popen(task_cmd, cwd=str(PROJECT_ROOT), env=env)
    started = time.time()
    monitor_started = False
    last_signature: np.ndarray | None = None
    static_elapsed = 0.0
    last_probe_at = 0.0

    while True:
        returncode = process.poll()
        if returncode is not None:
            code = int(returncode)
            if is_route_exit_after_command_success(code):
                return code, "route_exit_after_task_success"
            return code, "success" if code == 0 else f"returncode_{code}"

        elapsed = time.time() - started
        if elapsed >= watchdog.hard_timeout_seconds:
            print(f"[AFK watchdog] hard timeout after {elapsed:.1f}s; terminating router")
            terminate_process_tree(process)
            return 124, "hard_timeout"

        if elapsed < watchdog.task_timeout_seconds:
            time.sleep(1)
            continue

        if not monitor_started:
            monitor_started = True
            print(
                "[AFK watchdog] task timeout reached; starting stuck probe "
                f"interval={watchdog.stuck_probe_interval_seconds:.0f}s "
                f"window={watchdog.stuck_probe_seconds:.0f}s"
            )

        now = time.time()
        if now - last_probe_at < watchdog.stuck_probe_interval_seconds:
            time.sleep(1)
            continue
        last_probe_at = now

        try:
            signature = _reduced_screen_signature(recovery.controller.screenshot())
        except Exception as exc:
            print(f"[AFK watchdog] screenshot probe failed: {exc}")
            last_signature = None
            static_elapsed = 0.0
            continue

        if last_signature is None:
            last_signature = signature
            static_elapsed = 0.0
            continue

        score = _screen_diff_score(last_signature, signature)
        last_signature = signature
        if score <= STATIC_SCREEN_DIFF_THRESHOLD:
            static_elapsed += watchdog.stuck_probe_interval_seconds
            print(
                f"[AFK watchdog] static screen diff={score:.3f}; "
                f"static={static_elapsed:.0f}/{watchdog.stuck_probe_seconds:.0f}s"
            )
        else:
            print(f"[AFK watchdog] screen changed diff={score:.3f}; continuing")
            static_elapsed = 0.0

        if static_elapsed >= watchdog.stuck_probe_seconds:
            print("[AFK watchdog] stuck static screen detected; terminating router")
            terminate_process_tree(process)
            return 124, "stuck_static"

def run_command_subprocess_watchdog(
    *,
    cmd: list[str],
    env: dict[str, str],
    watchdog: TaskWatchdogConfig,
    recovery: UIRecovery,
) -> tuple[int, str]:
    process = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), env=env)
    started = time.time()
    monitor_started = False
    last_signature: np.ndarray | None = None
    static_elapsed = 0.0
    last_probe_at = 0.0

    while True:
        returncode = process.poll()
        if returncode is not None:
            code = int(returncode)
            return code, "success" if code == 0 else f"returncode_{code}"

        elapsed = time.time() - started
        if elapsed >= watchdog.hard_timeout_seconds:
            print(f"[AFK watchdog] hard timeout after {elapsed:.1f}s; terminating subprocess")
            terminate_process_tree(process)
            return 124, "hard_timeout"

        if elapsed < watchdog.task_timeout_seconds:
            time.sleep(1)
            continue

        if not monitor_started:
            monitor_started = True
            print(
                "[AFK watchdog] switch timeout reached; starting stuck probe "
                f"interval={watchdog.stuck_probe_interval_seconds:.0f}s "
                f"window={watchdog.stuck_probe_seconds:.0f}s"
            )

        now = time.time()
        if now - last_probe_at < watchdog.stuck_probe_interval_seconds:
            time.sleep(1)
            continue
        last_probe_at = now

        try:
            signature = _reduced_screen_signature(recovery.controller.screenshot())
        except Exception as exc:
            print(f"[AFK watchdog] screenshot probe failed: {exc}")
            last_signature = None
            static_elapsed = 0.0
            continue

        if last_signature is None:
            last_signature = signature
            static_elapsed = 0.0
            continue

        score = _screen_diff_score(last_signature, signature)
        last_signature = signature
        if score <= STATIC_SCREEN_DIFF_THRESHOLD:
            static_elapsed += watchdog.stuck_probe_interval_seconds
            print(
                f"[AFK watchdog] static screen diff={score:.3f}; "
                f"static={static_elapsed:.0f}/{watchdog.stuck_probe_seconds:.0f}s"
            )
        else:
            print(f"[AFK watchdog] screen changed diff={score:.3f}; continuing")
            static_elapsed = 0.0

        if static_elapsed >= watchdog.stuck_probe_seconds:
            print("[AFK watchdog] stuck static screen detected; terminating subprocess")
            terminate_process_tree(process)
            return 124, "stuck_static"

def run_router_task_in_process(argv: list[str]) -> int:
    from AwayFromKeyboard.integration_task import run_router

    original_cwd = os.getcwd()
    try:
        os.chdir(PROJECT_ROOT)
        run_router.main(argv)
        return 0
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        try:
            return int(code)
        except (TypeError, ValueError):
            return 1
    finally:
        os.chdir(original_cwd)

def run_router_task(
    *,
    task_cmd: list[str],
    router_argv: list[str],
    force_subprocess: bool,
    watchdog: TaskWatchdogConfig | None = None,
    recovery: UIRecovery | None = None,
) -> int:
    if force_subprocess or (watchdog is not None and watchdog.enabled):
        child_env = os.environ.copy()
        child_env.setdefault("PYTHONIOENCODING", "utf-8")
        child_env.setdefault("PYTHONUTF8", "1")
        if watchdog is not None and watchdog.debug_label:
            child_env["VL_ACTION_DEBUG_LABEL"] = watchdog.debug_label
        if watchdog is not None and watchdog.enabled:
            if recovery is None:
                raise ValueError("recovery is required when watchdog is enabled")
            returncode, reason = run_router_task_subprocess_watchdog(
                task_cmd=task_cmd,
                env=child_env,
                watchdog=watchdog,
                recovery=recovery,
            )
            if returncode != 0:
                rename_router_debug_dirs_for_failure(watchdog.debug_label, reason, returncode)
            return returncode
        result = subprocess.run(task_cmd, cwd=str(PROJECT_ROOT), env=child_env)
        if result.returncode != 0 and watchdog is not None:
            rename_router_debug_dirs_for_failure(
                watchdog.debug_label,
                f"returncode_{result.returncode}",
                int(result.returncode),
            )
        return int(result.returncode)

    print("[AFK] Router 執行模式: in-process")
    return run_router_task_in_process(router_argv)

def reenter_game_from_current_app(recovery: UIRecovery) -> bool:
    from src.game_entry import reenter_game

    return bool(reenter_game(recovery.controller, recovery.matcher))

def restart_game_app_and_reenter(
    recovery: UIRecovery,
    *,
    launch_wait_seconds: float = 10.0,
) -> bool:
    try:
        print(f"[AFK recovery] force-stop app: {GAME_PACKAGE}")
        recovery.controller.shell(["am", "force-stop", GAME_PACKAGE])
        time.sleep(3)
        print(f"[AFK recovery] launch app: {GAME_PACKAGE}")
        recovery.controller.shell(
            ["monkey", "-p", GAME_PACKAGE, "-c", "android.intent.category.LAUNCHER", "1"]
        )
        time.sleep(launch_wait_seconds)
        return reenter_game_from_current_app(recovery)
    except Exception as exc:
        print(f"[AFK recovery] app restart failed: {exc}")
        return False

def restart_bluestacks_and_reenter(
    recovery: UIRecovery,
    *,
    boot_wait_seconds: float,
) -> bool:
    try:
        from restart_bluestacks import restart_bluestacks

        print("[AFK recovery] restart BlueStacks")
        if restart_bluestacks(boot_wait_seconds=boot_wait_seconds) != 0:
            return False
        if not recovery.controller.connect():
            print("[AFK recovery] ADB reconnect failed after BlueStacks restart")
            return False
        return reenter_game_from_current_app(recovery)
    except Exception as exc:
        print(f"[AFK recovery] BlueStacks restart failed: {exc}")
        return False

def run_with_direct_retry_then_recovery(
    action,
    *,
    label: str,
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,),
    direct_retries: int = 1,
    recovery_action=None,
    on_retry=None,
    on_recovery=None,
    on_failure=None,
):
    last_error: BaseException | None = None
    for failure_count in range(direct_retries + 1):
        try:
            return action()
        except retry_exceptions as exc:
            last_error = exc
            if failure_count >= direct_retries:
                break
            attempt = failure_count + 1
            print(f"[AFK recovery] {label} failed; retrying once without recovery ({attempt}/{direct_retries}): {exc}")
            if on_retry is not None:
                on_retry(exc, attempt, direct_retries)

    if recovery_action is None:
        if on_failure is not None and last_error is not None:
            on_failure(last_error)
        raise last_error or RuntimeError(f"{label} failed")

    print(f"[AFK recovery] {label} direct retry failed; recovering then retrying: {last_error}")
    if on_recovery is not None and last_error is not None:
        on_recovery(last_error)
    recovery_action()
    try:
        return action()
    except retry_exceptions as exc:
        if on_failure is not None:
            on_failure(exc)
        raise

def run_switch_account_command(
    *,
    switch_cmd: list[str],
    watchdog: TaskWatchdogConfig,
    recovery: UIRecovery,
) -> tuple[bool, str]:
    child_env = os.environ.copy()
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    child_env.setdefault("PYTHONUTF8", "1")
    returncode, reason = run_command_subprocess_watchdog(
        cmd=switch_cmd,
        env=child_env,
        watchdog=watchdog,
        recovery=recovery,
    )
    return returncode == 0, reason if returncode != 0 else "success"

def switch_account_with_recovery(
    *,
    account_name: str,
    switch_cmd: list[str],
    recovery: UIRecovery,
    enabled: bool,
    bluestacks_boot_wait_seconds: float,
    watchdog: TaskWatchdogConfig,
) -> tuple[bool, str]:
    if not enabled:
        return bool(switch_account(account_name)), "initial"

    success, reason = run_switch_account_command(
        switch_cmd=switch_cmd,
        watchdog=watchdog,
        recovery=recovery,
    )
    if success:
        return True, "initial"

    print(f"[AFK recovery] switch account failed ({reason}); restarting app")
    if restart_game_app_and_reenter(recovery):
        success, reason = run_switch_account_command(
            switch_cmd=switch_cmd,
            watchdog=watchdog,
            recovery=recovery,
        )
        if success:
            return True, "app_restart_retry"
    else:
        print("[AFK recovery] app restart did not reenter game before switch retry")

    print("[AFK recovery] switch account still failed; restarting BlueStacks")
    if restart_bluestacks_and_reenter(
        recovery,
        boot_wait_seconds=bluestacks_boot_wait_seconds,
    ):
        success, reason = run_switch_account_command(
            switch_cmd=switch_cmd,
            watchdog=watchdog,
            recovery=recovery,
        )
        if success:
            return True, "bluestacks_restart_retry"
    else:
        print("[AFK recovery] BlueStacks restart did not reenter game before switch retry")

    return False, reason

def run_router_task_with_recovery(
    *,
    task_cmd: list[str],
    router_argv: list[str],
    force_subprocess: bool,
    recovery: UIRecovery,
    enabled: bool,
    bluestacks_boot_wait_seconds: float,
    watchdog: TaskWatchdogConfig | None = None,
) -> tuple[int, str]:
    returncode = run_router_task(
        task_cmd=task_cmd,
        router_argv=router_argv,
        force_subprocess=force_subprocess or enabled,
        watchdog=watchdog,
        recovery=recovery,
    )
    if is_route_exit_after_command_success(returncode):
        if not enabled:
            return returncode, "route_exit_after_task_success"
        print("[AFK recovery] route exit failed after task success; recovering UI without rerunning task")
        if recovery.recover_to_main():
            return 0, "route_exit_recovered"
        print("[AFK recovery] route exit recovery did not reach main; restarting app")
        if restart_game_app_and_reenter(recovery):
            return 0, "route_exit_app_restart_recovered"
        print("[AFK recovery] route exit app recovery failed; restarting BlueStacks")
        if restart_bluestacks_and_reenter(
            recovery,
            boot_wait_seconds=bluestacks_boot_wait_seconds,
        ):
            return 0, "route_exit_bluestacks_restart_recovered"
        return returncode, "route_exit_recovery_failed_after_task_success"
    if returncode == 0 or not enabled:
        return returncode, "initial"

    print(f"[AFK recovery] task failed returncode={returncode}; retrying once without restart")
    returncode = run_router_task(
        task_cmd=task_cmd,
        router_argv=router_argv,
        force_subprocess=force_subprocess or enabled,
        watchdog=watchdog,
        recovery=recovery,
    )
    if returncode == 0:
        return 0, "direct_retry"

    print(f"[AFK recovery] direct retry failed returncode={returncode}; restarting app")
    if restart_game_app_and_reenter(recovery):
        returncode = run_router_task(
            task_cmd=task_cmd,
            router_argv=router_argv,
            force_subprocess=force_subprocess or enabled,
            watchdog=watchdog,
            recovery=recovery,
        )
        if returncode == 0:
            return 0, "app_restart_retry"
    else:
        print("[AFK recovery] app restart did not reenter game")

    print("[AFK recovery] app recovery failed; restarting BlueStacks")
    if restart_bluestacks_and_reenter(
        recovery,
        boot_wait_seconds=bluestacks_boot_wait_seconds,
    ):
        returncode = run_router_task(
            task_cmd=task_cmd,
            router_argv=router_argv,
            force_subprocess=force_subprocess or enabled,
            watchdog=watchdog,
            recovery=recovery,
        )
        if returncode == 0:
            return 0, "bluestacks_restart_retry"
    else:
        print("[AFK recovery] BlueStacks restart did not reenter game")

    return returncode, "failed_after_recovery"

def resolve_task_watchdog_config(
    *,
    enabled: bool,
    account_name: str,
    task_name: str,
    cli_task_timeout_seconds: float,
    cli_hard_timeout_seconds: float,
    stuck_probe_seconds: float,
    stuck_probe_interval_seconds: float,
    ini_timeout: str | None,
    ini_hard_timeout: str | None,
) -> TaskWatchdogConfig:
    task_timeout = parse_duration_to_seconds(ini_timeout)
    if task_timeout is None:
        task_timeout = cli_task_timeout_seconds

    hard_timeout = parse_duration_to_seconds(ini_hard_timeout)
    if hard_timeout is None:
        if ini_timeout:
            hard_timeout = task_timeout * 2
        else:
            hard_timeout = cli_hard_timeout_seconds

    hard_timeout = max(hard_timeout, task_timeout + stuck_probe_interval_seconds)
    return TaskWatchdogConfig(
        enabled=enabled,
        task_timeout_seconds=task_timeout,
        hard_timeout_seconds=hard_timeout,
        stuck_probe_seconds=stuck_probe_seconds,
        stuck_probe_interval_seconds=stuck_probe_interval_seconds,
        debug_label=build_action_debug_label(account_name, task_name) if enabled else None,
    )

def previous_log_date_prefix(now: datetime | None = None) -> str:
    current = now or datetime.now(TAIPEI_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=TAIPEI_TZ)
    taipei_now = current.astimezone(TAIPEI_TZ)
    return (taipei_now.date() - timedelta(days=1)).strftime("%Y%m%d")

def is_log_from_date(path: Path, date_prefix: str) -> bool:
    name = path.name
    return name.startswith(f"{date_prefix}_") or name.startswith(f"afk_{date_prefix}_")

def cleanup_previous_day_logs(log_dir: Path = LOG_DIR, now: datetime | None = None) -> int:
    if not log_dir.exists():
        return 0
    date_prefix = previous_log_date_prefix(now)
    removed = 0
    for path in list(log_dir.iterdir()):
        if not is_log_from_date(path, date_prefix):
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed += 1
    return removed

def start_previous_day_log_cleanup(log_dir: Path = LOG_DIR, now: datetime | None = None) -> threading.Thread:
    def worker() -> None:
        try:
            removed = cleanup_previous_day_logs(log_dir, now)
            if removed:
                print(f"🧹 已清除前一天 log：{removed} 個項目")
        except Exception as exc:
            print(f"⚠️ 清理前一天 log 失敗：{exc}")

    thread = threading.Thread(target=worker, name="afk-log-cleanup", daemon=True)
    thread.start()
    return thread

def _parse_activity_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TAIPEI_TZ)
    return parsed.astimezone(TAIPEI_TZ)

def _taipei_now(now: datetime | None = None) -> datetime:
    current = now or datetime.now(TAIPEI_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=TAIPEI_TZ)
    return current.astimezone(TAIPEI_TZ)

def is_midas_activity_stale(activity: dict, now: datetime | None = None) -> bool:
    updated_at = _parse_activity_time(activity.get("updated_at"))
    if updated_at is None:
        return False
    return (_taipei_now(now) - updated_at).total_seconds() > MIDAS_ACTIVE_STALE_SECONDS

def midas_activity_wait_reason(
    activity: dict,
    now: datetime | None = None,
    *,
    estimated_task_seconds: float | None = None,
    safety_margin_seconds: float = 0,
) -> str | None:
    if activity.get("activity") != MIDAS_ACTIVITY_NAME:
        return None
    if bool(activity.get("active")):
        if is_midas_activity_stale(activity, now):
            return "stale_active"
        return "active"

    wake_at = _parse_activity_time(activity.get("wake_at"))
    if wake_at is None:
        return None
    current = _taipei_now(now)

    if estimated_task_seconds is not None:
        wait_end = wake_at + timedelta(seconds=MIDAS_WAKE_GRACE_SECONDS)
        if current > wait_end:
            return None
        latest_finish = current + timedelta(
            seconds=max(0, estimated_task_seconds) + max(0, safety_margin_seconds)
        )
        if latest_finish > wake_at:
            return "wake_soon"
        return None

    return None

def is_midas_activity_active() -> bool:
    return midas_activity_wait_reason(read_activity_state()) is not None

def wait_for_midas_activity_clearance(
    recovery: UIRecovery | None,
    *,
    notify_enabled: bool,
    estimated_task_seconds: float | None = None,
    safety_margin_seconds: float = MIDAS_TASK_SAFETY_MARGIN_SECONDS,
) -> None:
    notified_reason = None
    while True:
        activity = read_activity_state()
        reason = midas_activity_wait_reason(
            activity,
            estimated_task_seconds=estimated_task_seconds,
            safety_margin_seconds=safety_margin_seconds,
        )
        if reason is None:
            return
        if reason == "stale_active":
            print(
                "⚠️ 偵測到點金手 active lock 已超過 10 分鐘，視為殘留狀態並繼續 AFK。"
                "請確認 AwayFromKeyboard/state/activity.json，必要時把 active 改成 false 或刪除該檔。"
            )
            notify_status(
                "AFK",
                "忽略殘留點金鎖",
                detail="midas_auto active updated_at older than 10 minutes",
                enabled=notify_enabled,
            )
            return

        wake_at = activity.get("wake_at")
        if reason != notified_reason:
            if reason == "active":
                detail = "點金手掛機活動中，每 5 分鐘重新檢查。"
            else:
                detail = f"點金手接近喚醒時間 wake_at={wake_at}，先在主畫面等待。"
            print(f"⏸️  {detail}")
            notify_status("AFK", "等待點金手", detail=detail, enabled=notify_enabled)
            notified_reason = reason

        if recovery is not None:
            recovery.recover_to_main()
        smart_sleep(MIDAS_ACTIVITY_POLL_SECONDS)

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
    parser.add_argument("--log", action="store_true", help="每個 Router 任務各自輸出 UTF-8 log 與 profile 到 log/")
    parser.add_argument("--no-discord", action="store_true", help="關閉 Discord 狀態通知")
    parser.add_argument("--delay", type=str, default=None, help="首次啟動前的額外延遲等待時間 (hh:mm:ss)")
    parser.add_argument("--delay-until-8", "--du8", action="store_true", help="先延遲到下一個上午 08:00:30；可再搭配 --delay 額外等待")
    parser.add_argument("--now", action="store_true", help="忽略 ini 的 start_time，立刻執行")
    parser.add_argument(
        "--no-recover-task-failure",
        dest="recover_task_failure",
        action="store_false",
        help="disable failed-route recovery",
    )
    parser.set_defaults(recover_task_failure=True)
    parser.add_argument("--recovery-bluestacks-boot-wait", type=float, default=180.0, help="seconds to wait after BlueStacks restart during task recovery")
    parser.add_argument("--task-timeout", default=str(DEFAULT_TASK_TIMEOUT_SECONDS), help="seconds or hh:mm:ss before stuck monitor starts")
    parser.add_argument("--task-hard-timeout", default=str(DEFAULT_TASK_HARD_TIMEOUT_SECONDS), help="seconds or hh:mm:ss before the route subprocess is killed")
    parser.add_argument("--stuck-probe-seconds", type=float, default=DEFAULT_STUCK_PROBE_SECONDS, help="static-screen seconds required to classify a route as stuck")
    parser.add_argument("--stuck-probe-interval", type=float, default=DEFAULT_STUCK_PROBE_INTERVAL_SECONDS, help="seconds between stuck monitor screenshots")
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
        cli_task_timeout_seconds = parse_duration_to_seconds(args.task_timeout)
        cli_hard_timeout_seconds = parse_duration_to_seconds(args.task_hard_timeout)
        if cli_task_timeout_seconds is None or cli_hard_timeout_seconds is None:
            raise ValueError("task timeout values cannot be empty")
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
            smart_sleep(delay_seconds)

        wait_for_midas_activity_clearance(recovery, notify_enabled=notify_enabled)

        start_previous_day_log_cleanup(LOG_DIR)

        configured_tasks, date_key, completion_state = load_runtime_task_state()
        clear_stale_failed_this_round_for_new_run(completion_state)

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

        current_account = detect_and_record_current_account(
            controller,
            matcher,
            "afk.loop.detect",
        )
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

        i = 0
        while i < len(account_order):
            account_name = account_order[i]
            replan_requested = False
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
                i += 1
                continue

            print("\n" + "="*50)
            print(f"🚀 開始執行 ({i+1}/{accounts_per_round}): 帳號 【{account_name}】")
            print(f"📌 待執行 route: {', '.join(pending_tasks)}")
            print("="*50 + "\n")
            
            try:
                expected_current_account = current_account
                detected_account = detect_and_record_current_account(
                    controller,
                    matcher,
                    "afk.loop.before_account",
                )
                if (
                    detected_account
                    and expected_current_account
                    and detected_account != expected_current_account
                ):
                    replanned_order = replan_account_order_from_detected(
                        detected_account,
                        completion_state,
                        configured_tasks,
                        force=args.force,
                    )
                    if replanned_order is not None:
                        print(
                            f"[AFK] account drift detected before account loop: "
                            f"expected_current={expected_current_account}, actual={detected_account}; replanning"
                        )
                        notify_status(
                            "AFK",
                            "account drift detected; replanning",
                            account=detected_account,
                            detail=f"expected_current={expected_current_account}",
                            enabled=notify_enabled,
                        )
                        current_account = detected_account
                        account_order = replanned_order
                        accounts_per_round = len(account_order)
                        i = 0
                        continue
                if detected_account:
                    current_account = detected_account

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

                    switch_watchdog = TaskWatchdogConfig(
                        enabled=args.recover_task_failure,
                        task_timeout_seconds=cli_task_timeout_seconds,
                        hard_timeout_seconds=cli_hard_timeout_seconds,
                        stuck_probe_seconds=args.stuck_probe_seconds,
                        stuck_probe_interval_seconds=args.stuck_probe_interval,
                        debug_label=build_action_debug_label(account_name, "switch_account")
                        if args.recover_task_failure
                        else None,
                    )
                    wait_for_midas_activity_clearance(
                        recovery,
                        notify_enabled=notify_enabled,
                        estimated_task_seconds=switch_watchdog.hard_timeout_seconds,
                    )
                    success, switch_stage = switch_account_with_recovery(
                        account_name=account_name,
                        switch_cmd=switch_cmd,
                        recovery=recovery,
                        enabled=args.recover_task_failure,
                        bluestacks_boot_wait_seconds=args.recovery_bluestacks_boot_wait,
                        watchdog=switch_watchdog,
                    )
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
                    verified_account = detect_and_record_current_account(
                        controller,
                        matcher,
                        "afk.loop.switch.verify",
                    )
                    if verified_account != account_name:
                        print(
                            f"\n[AFK] account switch verification failed: "
                            f"target={account_name}, actual={verified_account or 'unknown'}"
                        )
                        replanned_order = replan_account_order_from_detected(
                            verified_account,
                            completion_state,
                            configured_tasks,
                            force=args.force,
                        )
                        if replanned_order is None:
                            notify_status(
                                "AFK",
                                "account switch verification failed",
                                account=account_name,
                                detail=f"actual={verified_account or 'unknown'}",
                                enabled=notify_enabled,
                            )
                            sys.exit(1)
                        notify_status(
                            "AFK",
                            "account switch verification mismatch; replanning",
                            account=verified_account,
                            detail=f"target={account_name}",
                            enabled=notify_enabled,
                        )
                        current_account = verified_account
                        account_order = replanned_order
                        accounts_per_round = len(account_order)
                        i = 0
                        continue
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
                    route_log_file = build_route_log_file(
                        args.log,
                        account_name=account_name,
                        task_name=task_name,
                    )
                    router_argv = build_router_argv(
                        task_name,
                        debug_actions=args.debug_actions,
                        force_subprocess=args.force_subprocess,
                        route_log_file=route_log_file,
                    )
                    try:
                        watchdog = resolve_task_watchdog_config(
                            enabled=args.recover_task_failure,
                            account_name=account_name,
                            task_name=task_name,
                            cli_task_timeout_seconds=cli_task_timeout_seconds,
                            cli_hard_timeout_seconds=cli_hard_timeout_seconds,
                            stuck_probe_seconds=args.stuck_probe_seconds,
                            stuck_probe_interval_seconds=args.stuck_probe_interval,
                            ini_timeout=task_config.get_task_timeout(task_name),
                            ini_hard_timeout=task_config.get_task_hard_timeout(task_name),
                        )
                    except ValueError as e:
                        print(f"??[?航炊] route timeout 設定錯誤: {e}")
                        sys.exit(1)
                    wait_for_midas_activity_clearance(
                        recovery,
                        notify_enabled=notify_enabled,
                        estimated_task_seconds=watchdog.hard_timeout_seconds,
                    )
                    verified_account = detect_and_record_current_account(
                        controller,
                        matcher,
                        "afk.loop.before_task",
                    )
                    if verified_account != account_name:
                        print(
                            f"\n[AFK] account verification failed before task: "
                            f"target={account_name}, actual={verified_account or 'unknown'}, "
                            f"task={task_name}"
                        )
                        replanned_order = replan_account_order_from_detected(
                            verified_account,
                            completion_state,
                            configured_tasks,
                            force=args.force,
                        )
                        if replanned_order is None:
                            notify_status(
                                "AFK",
                                "account verification failed before task",
                                account=account_name,
                                route=task_name,
                                detail=f"actual={verified_account or 'unknown'}",
                                enabled=notify_enabled,
                            )
                            sys.exit(1)
                        notify_status(
                            "AFK",
                            "account drift before task; replanning",
                            account=verified_account,
                            route=task_name,
                            detail=f"target={account_name}",
                            enabled=notify_enabled,
                        )
                        current_account = verified_account
                        account_order = replanned_order
                        accounts_per_round = len(account_order)
                        i = 0
                        replan_requested = True
                        break
                    current_account = account_name
                    task_cmd = [python_exe, str(run_router_script)] + router_argv
                    print("\n" + "-" * 50)
                    print("🛠️ [Debug] 若此 Router 任務卡住，可複製以下指令單獨測試：")
                    print(f">>> {' '.join(task_cmd)}")
                    print("-" * 50 + "\n")
                    
                    returncode, recovery_stage = run_router_task_with_recovery(
                        task_cmd=task_cmd,
                        router_argv=router_argv,
                        force_subprocess=args.force_subprocess,
                        recovery=recovery,
                        enabled=args.recover_task_failure,
                        bluestacks_boot_wait_seconds=args.recovery_bluestacks_boot_wait,
                        watchdog=watchdog,
                    )
                    if returncode != 0:
                        if is_route_exit_after_command_success(returncode):
                            mark_route_completed(completion_state, account_name, task_name)
                            print(
                                "[AFK recovery] task command already succeeded; "
                                "marked route completed even though route exit failed"
                            )
                            notify_status(
                                "AFK",
                                "route exit failed after task success",
                                account=account_name,
                                route=task_name,
                                detail=f"returncode={returncode}; stage={recovery_stage}",
                                enabled=notify_enabled,
                            )
                            sys.exit(1)
                        print(f"\n❌ [錯誤] 帳號 【{account_name}】 的任務 【{task_name}】 回傳了非零錯誤碼 ({returncode})！")
                        print("⚠️ [Fail-Fast] 發生異常，立刻終止整支程式，不切換帳號以保留現場。")
                        notify_status(
                            "AFK",
                            "失敗",
                            account=account_name,
                            route=task_name,
                            detail=f"returncode={returncode}; stage={recovery_stage}",
                            enabled=notify_enabled,
                        )
                        if args.recover_task_failure:
                            mark_route_failed_this_round(
                                completion_state,
                                account_name,
                                task_name,
                                f"returncode={returncode}; stage={recovery_stage}",
                            )
                            print("[AFK recovery] marked failed_this_round and continuing to next route")
                            continue
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
                            
                if replan_requested:
                    continue

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

                i += 1
                    
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
    clear_failed_this_round(completion_state)
    notify_status("AFK", "全部完成", enabled=notify_enabled)

if __name__ == "__main__":
    main()
