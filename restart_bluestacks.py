from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Optional


PROJECT_DIR = Path(__file__).resolve().parent
CACHE_FILE = PROJECT_DIR / ".bluestacks_cmd.txt"
DEFAULT_COMMAND_LINE = (
    r'"C:\Program Files\BlueStacks_nxt\HD-Player.exe" '
    r'--instance Pie64 --cmd launchApp --package "com.ageofeternity.global"'
)

BLUESTACKS_PROCESS_NAMES = (
    "HD-Player.exe",
    "HD-Agent.exe",
    "HD-Adb.exe",
    "HD-LogRotatorService.exe",
    "HD-OBS.exe",
    "BstkSVC.exe",
    "BlueStacksServices.exe",
)


def find_bluestacks_command_line() -> Optional[str]:
    cmd_line = _find_command_line_with_powershell()
    if cmd_line:
        return cmd_line
    return _find_command_line_with_wmic()


def _find_command_line_with_powershell() -> Optional[str]:
    command = (
        "Get-CimInstance Win32_Process -Filter \"Name = 'HD-Player.exe'\" "
        "| Select-Object -ExpandProperty CommandLine"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return _select_hd_player_command_line(result.stdout.splitlines())


def _find_command_line_with_wmic() -> Optional[str]:
    try:
        result = subprocess.run(
            ["wmic", "process", "where", "name='HD-Player.exe'", "get", "commandline"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return _select_hd_player_command_line(result.stdout.splitlines())


def _select_hd_player_command_line(lines: Iterable[str]) -> Optional[str]:
    for line in lines:
        cleaned = line.strip()
        if cleaned and "HD-Player.exe" in cleaned and cleaned.lower() != "commandline":
            return cleaned
    return None


def load_cached_command_line() -> Optional[str]:
    if not CACHE_FILE.exists():
        return None
    cached = CACHE_FILE.read_text(encoding="utf-8").strip()
    return cached or None


def get_default_command_line() -> Optional[str]:
    executable = Path(r"C:\Program Files\BlueStacks_nxt\HD-Player.exe")
    if not executable.exists():
        return None
    return DEFAULT_COMMAND_LINE


def save_cached_command_line(command_line: str) -> None:
    CACHE_FILE.write_text(command_line + "\n", encoding="utf-8")


def close_bluestacks(*, wait_timeout_seconds: float = 20.0, kill_adb_server: bool = True) -> bool:
    print("[close] 正在完整關閉 BlueStacks...")
    for process_name in BLUESTACKS_PROCESS_NAMES:
        subprocess.run(
            ["taskkill", "/F", "/T", "/IM", process_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    if kill_adb_server:
        subprocess.run(
            ["adb", "kill-server"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    if wait_for_bluestacks_exit(wait_timeout_seconds):
        print("[ok] BlueStacks 程序已關閉。")
        return True

    running = ", ".join(list_running_bluestacks_processes())
    print(f"[warn] 等待逾時，仍偵測到 BlueStacks 程序: {running or 'unknown'}")
    return False


def wait_for_bluestacks_exit(timeout_seconds: float) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not list_running_bluestacks_processes():
            return True
        time.sleep(0.5)
    return not list_running_bluestacks_processes()


def list_running_bluestacks_processes() -> list[str]:
    running: list[str] = []
    for process_name in BLUESTACKS_PROCESS_NAMES:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {process_name}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if process_name.lower() in result.stdout.lower():
            running.append(process_name)
    return running


def start_bluestacks(command_line: str) -> None:
    print("[start] 重新啟動 BlueStacks...")
    subprocess.Popen(command_line, cwd=PROJECT_DIR)


def reset_adb() -> None:
    print("[adb] 重新連線 ADB...")
    for command in (
        ["adb", "kill-server"],
        ["adb", "start-server"],
        ["adb", "connect", "127.0.0.1:5555"],
        ["adb", "devices"],
    ):
        subprocess.run(command, cwd=PROJECT_DIR, check=False)


def restart_bluestacks(*, boot_wait_seconds: float = 120.0, close_only: bool = False) -> int:
    print("[check] 檢查 BlueStacks 狀態...")
    command_line = find_bluestacks_command_line()
    if command_line:
        save_cached_command_line(command_line)
        print("[ok] 取得目前 BlueStacks 啟動參數，已更新紀錄檔。")
    else:
        command_line = load_cached_command_line()
        if command_line:
            print("[info] 偵測不到執行中的 BlueStacks，使用上次紀錄的啟動參數。")
        else:
            command_line = get_default_command_line()
            if command_line:
                save_cached_command_line(command_line)
                print("[info] 偵測不到執行中的 BlueStacks，使用內建 Pie64 遊戲啟動參數。")
        if not command_line and not close_only:
            print("[error] 找不到執行中的 BlueStacks，且沒有歷史紀錄。")
            print("[next] 請先手動啟動一次模擬器，再跑一次這支腳本，讓它記住啟動路徑。")
            return 1

    close_ok = close_bluestacks()
    if close_only:
        return 0 if close_ok else 1
    if not close_ok:
        print("[warn] BlueStacks 未確認完全關閉，仍會嘗試重新啟動。")

    assert command_line is not None
    start_bluestacks(command_line)

    print(f"[wait] 等待 {boot_wait_seconds:.0f} 秒讓模擬器開機...")
    time.sleep(boot_wait_seconds)
    reset_adb()
    print("[ok] 任務完成：BlueStacks 重啟流程已執行完畢。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Close or restart BlueStacks cleanly.")
    parser.add_argument(
        "--close-only",
        action="store_true",
        help="只完整關閉 BlueStacks，不重新啟動。",
    )
    parser.add_argument(
        "--boot-wait",
        type=float,
        default=120.0,
        help="重新啟動後等待幾秒再重置 ADB，預設 120。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return restart_bluestacks(boot_wait_seconds=args.boot_wait, close_only=args.close_only)


if __name__ == "__main__":
    raise SystemExit(main())
