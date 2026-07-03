import sys
import time
from pathlib import Path

_MODULE_LOAD_STARTED = time.perf_counter()

# 加入當下目錄與父目錄以利載入模組
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))
parent_dir = current_dir.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from router import RouteNavigator
import subprocess
import task_config
import os
import argparse
from contextlib import contextmanager
from src.account_state import warn_if_midas_activity_active
from src.stdio_utils import configure_utf8_stdio

configure_utf8_stdio()


class _TeeStream:
    def __init__(self, console_stream, log_stream):
        self._console_stream = console_stream
        self._log_stream = log_stream
        self.encoding = getattr(console_stream, "encoding", "utf-8")

    def write(self, text):
        self._console_stream.write(text)
        self._log_stream.write(text)
        if "\n" in text:
            self.flush()
        return len(text)

    def flush(self):
        self._console_stream.flush()
        self._log_stream.flush()

    def isatty(self):
        return self._console_stream.isatty()


@contextmanager
def _tee_output(log_file: str | None):
    if not log_file:
        yield
        return

    path = Path(log_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    with path.open("w", encoding="utf-8", newline="") as log_stream:
        sys.stdout = _TeeStream(original_stdout, log_stream)
        sys.stderr = _TeeStream(original_stderr, log_stream)
        try:
            print(f"[Router] log_file={path}")
            yield
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr


def _profile_log_file_for_route_log(log_file: str | None) -> str | None:
    if not log_file:
        return None
    path = Path(log_file).expanduser()
    return str(path.with_name(f"{path.stem}.profile.txt"))


def _is_src_main_command(cmd_args: list[str]) -> bool:
    return len(cmd_args) >= 2 and cmd_args[0] == "-m" and cmd_args[1] == "src.main"


def _has_cli_option(args: list[str], option: str) -> bool:
    prefix = option + "="
    return any(arg == option or arg.startswith(prefix) for arg in args)


def _prepare_src_main_argv(
    cmd_args: list[str],
    *,
    selected_serial: str | None,
    debug_actions: bool,
) -> list[str]:
    argv = list(cmd_args[2:])
    if selected_serial and not _has_cli_option(argv, "--serial"):
        argv = ["--serial", selected_serial] + argv
    if debug_actions and not _has_cli_option(argv, "--debug-actions"):
        argv = ["--debug-actions"] + argv
    return argv


@contextmanager
def _temporary_env(updates: dict[str, str]):
    previous = {key: os.environ.get(key) for key in updates}
    try:
        os.environ.update(updates)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _python_utf8_env() -> dict[str, str]:
    return {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
    }


def _run_src_main_in_process(argv: list[str], *, project_root: Path, env_updates: dict[str, str]) -> int:
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    try:
        with _temporary_env(env_updates):
            from src import main as src_main

            return int(src_main.main(argv) or 0)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        try:
            return int(code)
        except (TypeError, ValueError):
            return 1


def _run_subprocess_streamed(full_cmd: list[str], *, project_root: Path, env: dict[str, str]) -> int:
    process = subprocess.Popen(
        full_cmd,
        cwd=str(project_root),
        env=env,
        bufsize=1,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
    return int(process.wait())


def run_configured_command(
    cmd_args: list[str],
    *,
    project_root: Path,
    python_exe: str,
    selected_serial: str | None,
    route_debug_label: str,
    debug_actions: bool,
    force_subprocess: bool,
    profile_log_file: str | None = None,
) -> int:
    full_cmd = [python_exe] + cmd_args
    print("\n" + "=" * 60)
    print("🛠️ [Debug] 若腳本卡住，可手動在終端機貼上以下指令重新執行：")
    print(f">>> {' '.join(full_cmd)}")
    print("=" * 60)

    env_updates: dict[str, str] = _python_utf8_env()
    if debug_actions:
        env_updates["VL_DEBUG_ACTIONS"] = "1"
        env_updates.setdefault("VL_ACTION_DEBUG_LABEL", route_debug_label)
    if selected_serial:
        env_updates["VL_ADB_SERIAL"] = selected_serial
        print(f"[Router] 使用 ADB serial: {selected_serial}")
    if profile_log_file:
        env_updates["VL_PROFILE_LOG_FILE"] = profile_log_file
        print(f"[Router] profile_log_file={profile_log_file}")

    if _is_src_main_command(cmd_args) and not force_subprocess:
        argv = _prepare_src_main_argv(
            cmd_args,
            selected_serial=selected_serial,
            debug_actions=debug_actions,
        )
        print("[Router] 執行模式: in-process src.main")
        print("=" * 60 + "\n")
        return _run_src_main_in_process(argv, project_root=project_root, env_updates=env_updates)

    if force_subprocess and _is_src_main_command(cmd_args):
        print("[Router] 執行模式: subprocess (--force-subprocess)")
    else:
        print("[Router] 執行模式: subprocess")
    print("=" * 60 + "\n")

    child_env = os.environ.copy()
    child_env.update(env_updates)
    return _run_subprocess_streamed(full_cmd, project_root=project_root, env=child_env)

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AFK route runner")
    parser.add_argument("route_name", nargs="?", default="點金手", help="要執行的路由任務名稱")
    parser.add_argument(
        "--debug-actions",
        action="store_true",
        help="儲存非錯誤 optional miss 與子程序 action debug 截圖",
    )
    parser.add_argument(
        "--force-subprocess",
        action="store_true",
        help="強制使用舊的 subprocess 執行模式，不使用 in-process src.main",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="將 Router 與子任務輸出同步寫入 UTF-8 log 檔案",
    )
    return parser


def _run(args) -> None:
    profile_log_file = _profile_log_file_for_route_log(args.log_file)
    if profile_log_file:
        print(
            f"[perf pid={os.getpid()}] run_router imports_ready "
            f"elapsed={time.perf_counter() - _MODULE_LOAD_STARTED:.3f}s",
            flush=True,
        )
    route_name = args.route_name
        
    print(f"🚀 開始執行路由任務：{route_name}")
    print("-" * 40)
    
    try:
        route_debug_label = f"route_{route_name}"
        navigator = RouteNavigator(
            route_name=route_name,
            debug_actions=args.debug_actions,
            debug_label=route_debug_label,
        )
        print(f"[Router] 開始執行進場路由...")
        navigator.execute_route(phase="enter")
        print("-" * 40)
        print(f"✅ [成功] 路由任務 '{route_name}' 進場導航完畢！準備執行對應指令...")
        
        # 尋找對應指令並執行
        cmd_args = task_config.get_command_for_task(route_name)
        if cmd_args:
            project_root = current_dir.parent.parent
            python_exe = sys.executable
            
            # 加上 try-except 捕捉 subprocess 可能的系統級崩潰
            script_failed = False
            try:
                selected_serial = getattr(navigator.controller, "serial", None)
                returncode = run_configured_command(
                    cmd_args,
                    project_root=project_root,
                    python_exe=python_exe,
                    selected_serial=selected_serial,
                    route_debug_label=route_debug_label,
                    debug_actions=args.debug_actions,
                    force_subprocess=args.force_subprocess,
                    profile_log_file=profile_log_file,
                )
                if returncode != 0:
                    print(f"⚠️ [警告] 外部指令執行結束，但回傳錯誤碼 (returncode={returncode})")
                    script_failed = True
                else:
                    print(f"✅ [成功] 外部腳本執行完畢！")
            except Exception as e:
                print(f"❌ [錯誤] 執行外部指令時發生崩潰: {e}")
                script_failed = True
                
            print(f"\n[Router] 外部腳本執行完畢，檢查是否有離場路由...")
            navigator.execute_route(phase="exit")
            print(f"✅ [成功] 離場路由執行完畢！")
            

            
            if script_failed:
                print("❌ [錯誤] 由於外部腳本執行失敗，結束路由任務並拋出錯誤碼以觸發 Fail-Fast。")
                sys.exit(1)
        else:
            print(f"ℹ️ [提示] 找不到 '{route_name}' 對應的外部指令配置，改以純路由任務執行。")
            print(f"\n[Router] 純路由任務完成，檢查是否有離場路由...")
            navigator.execute_route(phase="exit")
            print(f"✅ [成功] 離場路由執行完畢！")
            
    except ImportError as e:
        print(f"❌ [錯誤] 無法載入必要的模組 (ImportError): {e}")
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"❌ [錯誤] 找不到目錄或檔案: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"❌ [錯誤] 圖片解析失敗: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ [錯誤] 發生未預期的例外狀況: {e}")
        sys.exit(1)

def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    warn_if_midas_activity_active(process_name=f"run_router {args.route_name}")
    with _tee_output(args.log_file):
        _run(args)

if __name__ == "__main__":
    main()
