from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.config import ROOT_DIR


TAIPEI_TZ = timezone(timedelta(hours=8), name="Asia/Taipei")
DEFAULT_ACCOUNT_STATE_FILE = ROOT_DIR / "AwayFromKeyboard" / "state" / "current_account.json"
DEFAULT_ACTIVITY_STATE_FILE = ROOT_DIR / "AwayFromKeyboard" / "state" / "activity.json"
MIDAS_ACTIVITY_NAME = "midas_auto"


def write_current_account(
    account: str,
    *,
    source: str,
    path: Path = DEFAULT_ACCOUNT_STATE_FILE,
    now: Optional[datetime] = None,
) -> Path:
    normalized = str(account).strip()
    if not normalized:
        raise ValueError("account must not be empty")
    timestamp = (now or datetime.now(TAIPEI_TZ)).astimezone(TAIPEI_TZ)
    data = {
        "account": normalized,
        "source": str(source),
        "updated_at": timestamp.isoformat(timespec="seconds"),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(path)
    return path


def read_current_account(
    *,
    default: str = "default",
    path: Path = DEFAULT_ACCOUNT_STATE_FILE,
    max_age_seconds: Optional[float] = None,
    now: Optional[datetime] = None,
) -> str:
    path = Path(path)
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    account = data.get("account") if isinstance(data, dict) else None
    if not account:
        return default
    if max_age_seconds is not None and _is_stale(data.get("updated_at"), max_age_seconds, now=now):
        return default
    return str(account)


def write_activity_state(
    activity: str,
    *,
    active: bool,
    source: str,
    path: Path = DEFAULT_ACTIVITY_STATE_FILE,
    now: Optional[datetime] = None,
    extra: Optional[dict] = None,
) -> Path:
    normalized = str(activity).strip()
    if not normalized:
        raise ValueError("activity must not be empty")
    timestamp = (now or datetime.now(TAIPEI_TZ)).astimezone(TAIPEI_TZ)
    data = {
        "activity": normalized,
        "active": bool(active),
        "source": str(source),
        "updated_at": timestamp.isoformat(timespec="seconds"),
    }
    if extra:
        data.update(extra)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(path)
    return path


def clear_activity_state(
    activity: str,
    *,
    source: str,
    path: Path = DEFAULT_ACTIVITY_STATE_FILE,
    now: Optional[datetime] = None,
    extra: Optional[dict] = None,
) -> Path:
    return write_activity_state(activity, active=False, source=source, path=path, now=now, extra=extra)


def read_activity_state(
    *,
    path: Path = DEFAULT_ACTIVITY_STATE_FILE,
    max_age_seconds: Optional[float] = None,
    now: Optional[datetime] = None,
) -> dict:
    path = Path(path)
    if not path.exists():
        return {"active": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"active": False}
    if not isinstance(data, dict):
        return {"active": False}
    if max_age_seconds is not None and _is_stale(data.get("updated_at"), max_age_seconds, now=now):
        return {"active": False}
    return data


def warn_if_midas_activity_active(
    *,
    process_name: str,
    path: Path = DEFAULT_ACTIVITY_STATE_FILE,
) -> bool:
    activity = read_activity_state(path=path)
    if activity.get("activity") != MIDAS_ACTIVITY_NAME or not bool(activity.get("active")):
        return False

    print(
        "\n"
        "[警告] 偵測到點金手掛機狀態仍是活動中，但目前有其他小程序正在執行。\n"
        f"  process: {process_name}\n"
        f"  state 檔案: {Path(path)}\n"
        f"  source: {activity.get('source', 'unknown')}\n"
        f"  updated_at: {activity.get('updated_at', 'unknown')}\n"
        "  這通常表示 afk_midas.py 正在跑點金，或前一次被強制關閉後沒有正常清除狀態。\n"
        "  本程序不會暫停，會繼續執行；如果你確認點金已經停止，請到上面的 state 檔案把 active 改成 false，"
        "或刪除該檔案。\n",
        file=sys.stderr,
    )
    return True


def _is_stale(updated_at: object, max_age_seconds: float, *, now: Optional[datetime] = None) -> bool:
    if not isinstance(updated_at, str):
        return True
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=TAIPEI_TZ)
    current = (now or datetime.now(TAIPEI_TZ)).astimezone(TAIPEI_TZ)
    return (current - updated.astimezone(TAIPEI_TZ)).total_seconds() > max_age_seconds
