from __future__ import annotations

import json
import os
import queue
import shlex
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
DEFAULT_PYTHON = PROJECT_ROOT / ".venv-codex" / "Scripts" / "python.exe"
DEFAULT_ROUTE = "\u738b\u570b\u91d1\u5eab"
AFK_DAILY_INI_DEFAULT = "(default)"
STATE_FILE = PROJECT_ROOT / "tools" / "launcher_gui_state.json"


COMMANDS = (
    "Ads",
    "Arcane Forge",
    "Capture route",
    "Manual screenshot",
    "Switch account",
    "Run router",
    "AFK Daily",
    "AFK Midas",
    "Custom Python args",
)


@dataclass(frozen=True)
class CommandSpec:
    name: str
    argv: list[str]


class ProcessRunner:
    def __init__(self, output_queue: "queue.Queue[tuple[str, str]]") -> None:
        self.output_queue = output_queue
        self.process: subprocess.Popen[str] | None = None
        self.lock = threading.Lock()

    def is_running(self) -> bool:
        with self.lock:
            return self.process is not None and self.process.poll() is None

    def start(self, argv: list[str]) -> bool:
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return False

            env = os.environ.copy()
            env.setdefault("PYTHONIOENCODING", "utf-8")
            env.setdefault("PYTHONUTF8", "1")
            env.setdefault("PYTHONUNBUFFERED", "1")

            self.process = subprocess.Popen(
                argv,
                cwd=str(PROJECT_ROOT),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
            threading.Thread(target=self._pump_output, daemon=True).start()
            return True

    def send_input(self, text: str) -> bool:
        with self.lock:
            process = self.process
        if process is None or process.poll() is not None or process.stdin is None:
            return False
        try:
            process.stdin.write(text + "\n")
            process.stdin.flush()
        except OSError:
            return False
        return True

    def stop(self) -> None:
        with self.lock:
            process = self.process
        if process is None or process.poll() is not None:
            return
        self.output_queue.put(("line", "\n[launcher] stopping process tree...\n"))
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            process.terminate()

    def _pump_output(self) -> None:
        process = self.process
        if process is None:
            return
        assert process.stdout is not None
        self.output_queue.put(("state", "running"))
        while True:
            chunk = process.stdout.read(1)
            if not chunk:
                break
            self.output_queue.put(("line", chunk))
        returncode = process.wait()
        self.output_queue.put(("line", f"\n[launcher] process exited: {returncode}\n"))
        self.output_queue.put(("state", "idle"))


class CommandSlot(ttk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        index: int,
        python_var: tk.StringVar,
        default_command: str,
    ) -> None:
        super().__init__(parent, padding=(8, 6))
        self.index = index
        self.python_var = python_var
        self.output_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.runner = ProcessRunner(self.output_queue)

        self.command_var = tk.StringVar(value=default_command)
        self.status_var = tk.StringVar(value="Idle")
        self.route_var = tk.StringVar(value=DEFAULT_ROUTE)
        self.tag_var = tk.StringVar(value="001")
        self.route_optional_var = tk.BooleanVar(value=False)
        self.route_lowconf_var = tk.BooleanVar(value=False)
        self.route_swipe_v_var = tk.BooleanVar(value=False)
        self.route_swipe_h_var = tk.BooleanVar(value=False)
        self.route_verify_var = tk.BooleanVar(value=False)
        self.route_verify_next_var = tk.BooleanVar(value=False)
        self.task_var = tk.StringVar(value=DEFAULT_ROUTE)
        self.index_var = tk.StringVar(value="1")
        self.scene_var = tk.StringVar(value="")
        self.no_paint_var = tk.BooleanVar(value=False)
        self.account_var = tk.StringVar(value="next")
        self.debug_var = tk.BooleanVar(value=True)
        self.debug_actions_var = tk.BooleanVar(value=True)
        self.arcane_action_var = tk.StringVar(value="分解")
        self.arcane_target_max_stats_var = tk.StringVar(value="2")
        self.afk_daily_ini_var = tk.StringVar(value=AFK_DAILY_INI_DEFAULT)
        self.delay_var = tk.StringVar(value="")
        self.delay_hour_var = tk.StringVar(value="")
        self.delay_minute_var = tk.StringVar(value="")
        self.delay_second_var = tk.StringVar(value="")
        self.delay_enabled_var = tk.BooleanVar(value=False)
        self.du8_var = tk.BooleanVar(value=False)
        self.midas_task_debug_var = tk.BooleanVar(value=True)
        self.midas_sweep_first_var = tk.BooleanVar(value=False)
        self.two_accounts_var = tk.BooleanVar(value=False)
        self.extra_args_var = tk.StringVar(value="")
        self.stdin_var = tk.StringVar(value="")
        self.follow_output_var = tk.BooleanVar(value=True)

        self.param_frame: ttk.Frame | None = None
        self.output: tk.Text
        self.run_button: ttk.Button
        self.stop_button: ttk.Button

        self._build_ui()
        self._render_params()
        self.after(100, self._drain_output)

    def snapshot_state(self) -> dict[str, object]:
        return {
            "command": self.command_var.get(),
            "route": self.route_var.get(),
            "tag": self.tag_var.get(),
            "route_optional": self.route_optional_var.get(),
            "route_lowconf": self.route_lowconf_var.get(),
            "route_swipe_v": self.route_swipe_v_var.get(),
            "route_swipe_h": self.route_swipe_h_var.get(),
            "route_verify": self.route_verify_var.get(),
            "route_verify_next": self.route_verify_next_var.get(),
            "task": self.task_var.get(),
            "index": self.index_var.get(),
            "scene": self.scene_var.get(),
            "no_paint": self.no_paint_var.get(),
            "account": self.account_var.get(),
            "debug": self.debug_var.get(),
            "debug_actions": self.debug_actions_var.get(),
            "arcane_action": self.arcane_action_var.get(),
            "arcane_target_max_stats": self.arcane_target_max_stats_var.get(),
            "afk_daily_ini": self.afk_daily_ini_var.get(),
            "delay": self._delay_value(),
            "delay_enabled": self.delay_enabled_var.get(),
            "du8": self.du8_var.get(),
            "midas_task_debug": self.midas_task_debug_var.get(),
            "midas_sweep_first": self.midas_sweep_first_var.get(),
            "two_accounts": self.two_accounts_var.get(),
            "extra_args": self.extra_args_var.get(),
            "follow_output": self.follow_output_var.get(),
        }

    def restore_state(self, state: dict[str, object]) -> None:
        string_vars = {
            "route": self.route_var,
            "tag": self.tag_var,
            "task": self.task_var,
            "index": self.index_var,
            "scene": self.scene_var,
            "account": self.account_var,
            "arcane_action": self.arcane_action_var,
            "arcane_target_max_stats": self.arcane_target_max_stats_var,
            "afk_daily_ini": self.afk_daily_ini_var,
            "delay": self.delay_var,
            "extra_args": self.extra_args_var,
        }
        bool_vars = {
            "route_optional": self.route_optional_var,
            "route_lowconf": self.route_lowconf_var,
            "route_swipe_v": self.route_swipe_v_var,
            "route_swipe_h": self.route_swipe_h_var,
            "route_verify": self.route_verify_var,
            "route_verify_next": self.route_verify_next_var,
            "no_paint": self.no_paint_var,
            "debug": self.debug_var,
            "debug_actions": self.debug_actions_var,
            "du8": self.du8_var,
            "delay_enabled": self.delay_enabled_var,
            "midas_task_debug": self.midas_task_debug_var,
            "midas_sweep_first": self.midas_sweep_first_var,
            "two_accounts": self.two_accounts_var,
            "follow_output": self.follow_output_var,
        }
        command = state.get("command")
        if isinstance(command, str) and command in COMMANDS:
            self.command_var.set(command)
        for key, variable in string_vars.items():
            value = state.get(key)
            if isinstance(value, str):
                variable.set(value)
        for key, variable in bool_vars.items():
            value = state.get(key)
            if isinstance(value, bool):
                variable.set(value)
        self._render_params()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1, uniform="slot")
        self.columnconfigure(1, weight=2, uniform="slot")
        self.rowconfigure(0, weight=1)

        command_box = ttk.LabelFrame(self, text=f"Command {self.index}", padding=8)
        command_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        command_box.columnconfigure(0, weight=1)
        command_box.rowconfigure(2, weight=1)

        combo = ttk.Combobox(command_box, textvariable=self.command_var, values=COMMANDS, state="readonly")
        combo.grid(row=0, column=0, sticky="ew")
        combo.bind("<<ComboboxSelected>>", lambda _event: self._render_params())

        self.param_frame = ttk.Frame(command_box)
        self.param_frame.grid(row=1, column=0, sticky="new", pady=(6, 0))

        actions = ttk.Frame(command_box)
        actions.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        actions.columnconfigure(0, weight=1)
        ttk.Label(actions, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.run_button = ttk.Button(actions, text="Run", command=self._run_selected)
        self.run_button.grid(row=0, column=1, padx=(6, 0))
        self.stop_button = ttk.Button(actions, text="Stop", command=self._stop_process, state="disabled")
        self.stop_button.grid(row=0, column=2, padx=(6, 0))
        ttk.Button(actions, text="Clear", command=self._clear_output).grid(row=0, column=3, padx=(6, 0))

        console_box = ttk.LabelFrame(self, text=f"Console {self.index}", padding=6)
        console_box.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        console_box.rowconfigure(0, weight=1)
        console_box.columnconfigure(0, weight=1)
        self.output = tk.Text(console_box, wrap="word", font=("Consolas", 9), undo=False, height=8)
        self.output.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(console_box, orient="vertical", command=self.output.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.output.configure(yscrollcommand=scroll.set)
        stdin_box = ttk.Frame(console_box)
        stdin_box.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        stdin_box.columnconfigure(1, weight=1)
        stdin_box.columnconfigure(2, weight=1)
        ttk.Button(stdin_box, text="Send", command=self._send_stdin).grid(row=0, column=0, padx=(0, 6))
        stdin_entry = ttk.Entry(stdin_box, textvariable=self.stdin_var)
        stdin_entry.grid(row=0, column=1, sticky="ew")
        stdin_entry.bind("<Return>", lambda _event: self._send_stdin())
        ttk.Checkbutton(stdin_box, text="Follow output", variable=self.follow_output_var).grid(row=0, column=3, sticky="e", padx=(12, 0))

    def _render_params(self) -> None:
        assert self.param_frame is not None
        for child in self.param_frame.winfo_children():
            child.destroy()
        self.param_frame.columnconfigure(1, weight=1)

        command = self.command_var.get()
        row = 0
        if command == "Ads":
            ttk.Label(self.param_frame, text="ads2/cli.py run --debug").grid(row=row, column=0, columnspan=2, sticky="w")
            row += 1
            row = self._entry(row, "extra", self.extra_args_var)
        elif command == "Arcane Forge":
            row = self._arcane_forge_params(row)
        elif command == "Capture route":
            row = self._entry(row, "route", self.route_var)
            row = self._entry(row, "tag", self.tag_var)
            row = self._capture_route_suffix_checks(row)
            row = self._entry(row, "extra", self.extra_args_var)
        elif command == "Manual screenshot":
            row = self._entry(row, "task", self.task_var)
            row = self._entry(row, "index", self.index_var)
            row = self._entry(row, "scene", self.scene_var)
            ttk.Checkbutton(self.param_frame, text="no paint", variable=self.no_paint_var).grid(row=row, column=0, columnspan=2, sticky="w")
            row += 1
            row = self._entry(row, "extra", self.extra_args_var)
        elif command == "Switch account":
            ttk.Checkbutton(self.param_frame, text="debug", variable=self.debug_var).grid(row=row, column=0, columnspan=2, sticky="w")
            row += 1
            ttk.Label(self.param_frame, text="account").grid(row=row, column=0, sticky="w", pady=2)
            ttk.Combobox(
                self.param_frame,
                textvariable=self.account_var,
                values=["next", "toggle", "detect", "em3", "311", "tiger", "14"],
            ).grid(row=row, column=1, sticky="ew", pady=2)
            row += 1
            row = self._entry(row, "extra", self.extra_args_var)
        elif command == "Run router":
            ttk.Checkbutton(self.param_frame, text="debug actions", variable=self.debug_actions_var).grid(row=row, column=0, columnspan=2, sticky="w")
            row += 1
            row = self._entry(row, "route", self.route_var)
            row = self._entry(row, "extra", self.extra_args_var)
        elif command == "AFK Daily":
            ttk.Checkbutton(self.param_frame, text="debug actions", variable=self.debug_actions_var).grid(row=row, column=0, columnspan=2, sticky="w")
            row += 1
            ttk.Label(self.param_frame, text="ini").grid(row=row, column=0, sticky="w", pady=2)
            ini_row = ttk.Frame(self.param_frame)
            ini_row.grid(row=row, column=1, sticky="ew", pady=2)
            ini_row.columnconfigure(0, weight=1)
            ttk.Combobox(
                ini_row,
                textvariable=self.afk_daily_ini_var,
                values=self._afk_daily_ini_choices(),
                state="readonly",
            ).grid(row=0, column=0, sticky="ew")
            ttk.Button(ini_row, text="Open", command=self._open_afk_daily_ini).grid(row=0, column=1, padx=(6, 0))
            ttk.Button(
                ini_row,
                text="State",
                command=self._open_afk_daily_current_state,
            ).grid(row=0, column=2, padx=(6, 0))
            row += 1
            row = self._afk_daily_delay_row(row)
            row = self._entry(row, "extra", self.extra_args_var)
        elif command == "AFK Midas":
            ttk.Checkbutton(self.param_frame, text="debug actions", variable=self.debug_actions_var).grid(row=row, column=0, columnspan=2, sticky="w")
            row += 1
            ttk.Checkbutton(self.param_frame, text="sweep all", variable=self.midas_sweep_first_var).grid(row=row, column=0, columnspan=2, sticky="w")
            row += 1
            ttk.Checkbutton(self.param_frame, text="midas task debug", variable=self.midas_task_debug_var).grid(row=row, column=0, columnspan=2, sticky="w")
            row += 1
            ttk.Checkbutton(self.param_frame, text="two accounts", variable=self.two_accounts_var).grid(row=row, column=0, columnspan=2, sticky="w")
            row += 1
            row = self._entry(row, "extra", self.extra_args_var)
        elif command == "Custom Python args":
            row = self._entry(row, "args", self.extra_args_var)

    def _entry(self, row: int, label: str, variable: tk.StringVar) -> int:
        assert self.param_frame is not None
        ttk.Label(self.param_frame, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(self.param_frame, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=2)
        return row + 1

    def _capture_route_suffix_checks(self, row: int) -> int:
        assert self.param_frame is not None
        ttk.Label(self.param_frame, text="suffix").grid(row=row, column=0, sticky="nw", pady=2)
        suffix_box = ttk.Frame(self.param_frame)
        suffix_box.grid(row=row, column=1, sticky="ew", pady=2)
        checks = (
            ("optional", self.route_optional_var),
            ("lowconf", self.route_lowconf_var),
            ("swipeV", self.route_swipe_v_var),
            ("swipeH", self.route_swipe_h_var),
            ("verify", self.route_verify_var),
            ("verifyNext", self.route_verify_next_var),
        )
        for index, (label, variable) in enumerate(checks):
            ttk.Checkbutton(suffix_box, text=label, variable=variable).grid(
                row=index // 3,
                column=index % 3,
                sticky="w",
                padx=(0 if index % 3 == 0 else 8, 0),
            )
        return row + 1

    def _arcane_forge_params(self, row: int) -> int:
        assert self.param_frame is not None
        ttk.Label(self.param_frame, text="action").grid(row=row, column=0, sticky="w", pady=2)
        action_combo = ttk.Combobox(
            self.param_frame,
            textvariable=self.arcane_action_var,
            values=["分解", "升星"],
            state="readonly",
        )
        action_combo.grid(row=row, column=1, sticky="ew", pady=2)
        action_combo.bind("<<ComboboxSelected>>", lambda _event: self._render_params())
        row += 1
        ttk.Checkbutton(self.param_frame, text="debug actions", variable=self.debug_actions_var).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        ttk.Checkbutton(self.param_frame, text="debug", variable=self.debug_var).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        action = self.arcane_action_var.get()
        if action == "升星":
            row = self._entry(row, "target max stats", self.arcane_target_max_stats_var)
        row = self._entry(row, "extra", self.extra_args_var)
        return row

    def _afk_daily_delay_row(self, row: int) -> int:
        assert self.param_frame is not None
        self._sync_delay_parts_from_value()
        ttk.Checkbutton(self.param_frame, text="du8", variable=self.du8_var).grid(row=row, column=0, sticky="w")
        delay_box = ttk.Frame(self.param_frame)
        delay_box.grid(row=row, column=1, sticky="w", pady=2, padx=(12, 0))
        ttk.Checkbutton(delay_box, text="delay", variable=self.delay_enabled_var).grid(row=0, column=0, sticky="w", padx=(0, 6))
        for index, variable in enumerate((self.delay_hour_var, self.delay_minute_var, self.delay_second_var)):
            ttk.Entry(delay_box, textvariable=variable, width=3, justify="center").grid(row=0, column=1 + index * 2)
            if index < 2:
                ttk.Label(delay_box, text=":").grid(row=0, column=2 + index * 2, padx=2)
        return row + 1

    @staticmethod
    def _afk_daily_ini_choices() -> list[str]:
        ini_dir = PROJECT_ROOT / "AwayFromKeyboard"
        names = sorted(path.name for path in ini_dir.glob("*.ini") if path.is_file())
        return [AFK_DAILY_INI_DEFAULT] + names

    def _selected_afk_daily_ini_path(self) -> Path:
        ini_name = self.afk_daily_ini_var.get().strip()
        if not ini_name or ini_name == AFK_DAILY_INI_DEFAULT:
            ini_name = "afk_tasks.ini"
        return PROJECT_ROOT / "AwayFromKeyboard" / ini_name

    def _open_afk_daily_ini(self) -> None:
        path = self._selected_afk_daily_ini_path()
        if not path.exists():
            messagebox.showerror("Missing ini", f"File not found:\n{path}")
            return
        self._open_text_file(path, title="Open ini failed")

    def _open_afk_daily_current_state(self) -> None:
        try:
            from AwayFromKeyboard import afk_daily

            date_key = afk_daily.today_key()
            path = afk_daily.completion_file_for_date(date_key)
            if not path.exists():
                state = afk_daily.load_completion_state(date_key)
                afk_daily.save_completion_state(state)
        except Exception as exc:
            messagebox.showerror("Open state failed", str(exc))
            return
        self._open_text_file(path, title="Open state failed")

    @staticmethod
    def _open_text_file(path: Path, *, title: str) -> None:
        try:
            if os.name == "nt":
                subprocess.Popen(["notepad.exe", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            messagebox.showerror(title, str(exc))

    def _run_selected(self) -> None:
        try:
            spec = self._build_command()
        except ValueError as exc:
            messagebox.showerror("Missing value", str(exc))
            return
        self._start(spec)

    def _build_command(self) -> CommandSpec:
        command = self.command_var.get()
        if command == "Ads":
            return CommandSpec(command, ["ads2/cli.py", "run", "--debug"] + self._split_extra(self.extra_args_var.get()))
        if command == "Arcane Forge":
            action = self.arcane_action_var.get()
            if action == "分解":
                argv = ["arcane_forge/arcane_forge_task.py"]
            elif action == "升星":
                argv = ["arcane_forge/arcane_forge_ascend.py"]
                target_max_stats = self._required(self.arcane_target_max_stats_var, "target max stats")
                if not target_max_stats.isdigit():
                    raise ValueError("target max stats must be a number")
                argv += ["--target-max-stats", target_max_stats]
            else:
                raise ValueError(f"Unknown Arcane Forge action: {action}")
            if self.debug_actions_var.get():
                argv.append("--debug-actions")
            if self.debug_var.get():
                argv.append("--debug")
            argv += self._split_extra(self.extra_args_var.get())
            return CommandSpec(command, argv)
        if command == "Capture route":
            argv = ["AwayFromKeyboard/capture_route.py", "--route", self._required(self.route_var, "route"), "--tag", self._capture_route_tag()]
            argv += self._split_extra(self.extra_args_var.get())
            return CommandSpec(command, argv)
        if command == "Manual screenshot":
            argv = ["-m", "src.manual_screenshots", "--task", self._required(self.task_var, "task")]
            if self.index_var.get().strip():
                argv += ["--index", self.index_var.get().strip()]
            if self.scene_var.get().strip():
                argv += ["--scene", self.scene_var.get().strip()]
            if self.no_paint_var.get():
                argv.append("--no-open-paint")
            argv += self._split_extra(self.extra_args_var.get())
            return CommandSpec(command, argv)
        if command == "Switch account":
            argv = ["switch_account/switch_account.py", self._required(self.account_var, "account")]
            if self.debug_var.get():
                argv.append("--debug")
            argv += self._split_extra(self.extra_args_var.get())
            return CommandSpec(command, argv)
        if command == "Run router":
            argv = ["AwayFromKeyboard/integration_task/run_router.py", self._required(self.route_var, "route")]
            if self.debug_actions_var.get():
                argv.append("--debug-actions")
            argv += self._split_extra(self.extra_args_var.get())
            return CommandSpec(command, argv)
        if command == "AFK Daily":
            argv = ["AwayFromKeyboard/afk_daily.py"]
            if self.debug_actions_var.get():
                argv.append("--debug-actions")
            ini_name = self.afk_daily_ini_var.get().strip()
            if ini_name and ini_name != AFK_DAILY_INI_DEFAULT:
                argv += ["--ini", str(Path("AwayFromKeyboard") / ini_name)]
            if self.du8_var.get():
                argv.append("--du8")
            delay = self._delay_value()
            if self.delay_enabled_var.get():
                argv += ["--delay", delay]
            argv += self._split_extra(self.extra_args_var.get())
            return CommandSpec(command, argv)
        if command == "AFK Midas":
            argv = ["AwayFromKeyboard/afk_midas.py"]
            if self.debug_actions_var.get():
                argv.append("--debug-actions")
            if self.midas_sweep_first_var.get():
                argv.append("--sweep-all")
            if self.midas_task_debug_var.get():
                argv.append("--midas-debug-actions")
            if self.two_accounts_var.get():
                argv.append("--two-accounts")
            argv += self._split_extra(self.extra_args_var.get())
            return CommandSpec(command, argv)
        if command == "Custom Python args":
            argv = self._split_extra(self.extra_args_var.get())
            if not argv:
                raise ValueError("args is required")
            return CommandSpec(command, argv)
        raise ValueError(f"Unknown command: {command}")

    @staticmethod
    def _required(variable: tk.StringVar, label: str) -> str:
        value = variable.get().strip()
        if not value:
            raise ValueError(f"{label} is required")
        return value

    def _capture_route_tag(self) -> str:
        tag = self._required(self.tag_var, "tag")
        selected_suffixes = [
            ("_optional", self.route_optional_var),
            ("_lowconf", self.route_lowconf_var),
            ("_swipeV", self.route_swipe_v_var),
            ("_swipeH", self.route_swipe_h_var),
            ("_verify", self.route_verify_var),
            ("_verifyNext", self.route_verify_next_var),
        ]
        lower_tag = tag.lower()
        for suffix, variable in selected_suffixes:
            if variable.get() and suffix.lower() not in lower_tag:
                tag += suffix
                lower_tag += suffix.lower()
        return tag

    def _sync_delay_parts_from_value(self) -> None:
        text = self.delay_var.get().strip()
        if not text:
            return
        parts = text.split(":")
        if len(parts) != 3:
            return
        for variable, value in zip(
            (self.delay_hour_var, self.delay_minute_var, self.delay_second_var),
            parts,
        ):
            if not variable.get().strip():
                variable.set(value.strip())

    def _delay_value(self) -> str:
        parts = [
            self.delay_hour_var.get().strip(),
            self.delay_minute_var.get().strip(),
            self.delay_second_var.get().strip(),
        ]
        if not any(parts):
            value = "0:0:0" if self.delay_enabled_var.get() else ""
            self.delay_var.set(value)
            return value
        normalized: list[str] = []
        for part in parts:
            if not part:
                normalized.append("0")
                continue
            if not part.isdigit():
                raise ValueError("delay must use numeric HH:MM:SS fields")
            normalized.append(str(int(part)))
        value = ":".join(normalized)
        self.delay_var.set(value)
        return value

    def _start(self, spec: CommandSpec) -> None:
        if self.runner.is_running():
            messagebox.showwarning("Already running", f"Command {self.index} is already running.")
            return
        argv = [self.python_var.get().strip()] + spec.argv
        self._append_line(f"\n$ {' '.join(argv)}\n")
        if not self.runner.start(argv):
            messagebox.showwarning("Already running", f"Command {self.index} is already running.")
            return
        self.status_var.set(f"Running: {spec.name}")
        self.stop_button.configure(state="normal")

    def _stop_process(self) -> None:
        self.runner.stop()

    def _send_stdin(self) -> None:
        text = self.stdin_var.get()
        if not self.runner.send_input(text):
            messagebox.showwarning("No running command", f"Command {self.index} is not waiting for input.")
            return
        self._append_line(f"\n[stdin] {text}\n")
        self.stdin_var.set("")

    def is_running(self) -> bool:
        return self.runner.is_running()

    def stop_running(self) -> None:
        self.runner.stop()

    def _split_extra(self, value: str) -> list[str]:
        value = value.strip()
        if not value:
            return []
        try:
            return [self._strip_outer_quotes(part) for part in shlex.split(value, posix=False)]
        except ValueError as exc:
            messagebox.showerror("Invalid args", str(exc))
            return []

    @staticmethod
    def _strip_outer_quotes(value: str) -> str:
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            return value[1:-1]
        return value

    def _append_line(self, text: str) -> None:
        should_follow = self.follow_output_var.get() and self._console_is_at_bottom()
        self.output.insert("end", text)
        if should_follow:
            self.output.see("end")

    def _console_is_at_bottom(self) -> bool:
        try:
            _first, last = self.output.yview()
        except tk.TclError:
            return True
        return last >= 0.995

    def _clear_output(self) -> None:
        self.output.delete("1.0", "end")

    def _drain_output(self) -> None:
        try:
            while True:
                kind, value = self.output_queue.get_nowait()
                if kind == "line":
                    self._append_line(value)
                elif kind == "state" and value == "idle":
                    self.status_var.set("Idle")
                    self.stop_button.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._drain_output)


class LauncherApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ADB VL Launcher")
        self.geometry("1120x820")
        self.minsize(960, 720)

        self.python_var = tk.StringVar(value=str(DEFAULT_PYTHON if DEFAULT_PYTHON.exists() else Path(sys.executable)))
        self.slots: list[CommandSlot] = []
        self._saved_state = self._load_state()
        saved_geometry = self._saved_state.get("geometry")
        if isinstance(saved_geometry, str) and saved_geometry:
            self.geometry(saved_geometry)
        saved_python = self._saved_state.get("python")
        if isinstance(saved_python, str) and saved_python:
            self.python_var.set(saved_python)
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=(10, 8))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Python").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.python_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(top, text="Open log", command=self._open_log_dir).grid(row=0, column=2)

        body = ttk.Frame(self, padding=(10, 0, 10, 10))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        for row in range(3):
            body.rowconfigure(row, weight=1, uniform="slots")
            default_command = "Ads"
            if row == 1:
                default_command = "AFK Daily"
            elif row == 2:
                default_command = "AFK Midas"
            slot = CommandSlot(body, row + 1, self.python_var, default_command)
            saved_slot = self._saved_slot_state(row)
            if saved_slot is not None:
                slot.restore_state(saved_slot)
            self.slots.append(slot)
            slot.grid(row=row, column=0, sticky="nsew", pady=(0 if row == 0 else 6, 0))

    def _on_close(self) -> None:
        running_slots = [slot for slot in self.slots if slot.is_running()]
        if running_slots:
            if not messagebox.askyesno(
                "Stop running commands?",
                f"{len(running_slots)} command(s) are still running.\nStop them and close the launcher?",
            ):
                return
            for slot in running_slots:
                slot.stop_running()
        self._save_state()
        self.destroy()

    def _load_state(self) -> dict[str, object]:
        try:
            with STATE_FILE.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _saved_slot_state(self, index: int) -> dict[str, object] | None:
        slots = self._saved_state.get("slots")
        if not isinstance(slots, list) or index >= len(slots):
            return None
        slot_state = slots[index]
        return slot_state if isinstance(slot_state, dict) else None

    def _save_state(self) -> None:
        data = {
            "python": self.python_var.get(),
            "geometry": self.geometry(),
            "slots": [slot.snapshot_state() for slot in self.slots],
        }
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with STATE_FILE.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
        except OSError as exc:
            messagebox.showwarning("Save state failed", str(exc))

    def _open_log_dir(self) -> None:
        log_dir = PROJECT_ROOT / "log"
        log_dir.mkdir(exist_ok=True)
        if os.name == "nt":
            os.startfile(log_dir)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(log_dir)])


def main() -> None:
    app = LauncherApp()
    app.mainloop()


if __name__ == "__main__":
    main()
