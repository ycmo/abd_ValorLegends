import configparser
import os
import shlex
import sys
from pathlib import Path

# 強制設定輸出為 UTF-8，以防在 Windows 終端機顯示中文出錯
sys.stdout.reconfigure(encoding='utf-8')

CONFIG_FILE = Path(__file__).resolve().parent / "afk_tasks.ini"
CONFIG_ENV_VAR = "AFK_TASKS_INI"
TIMEOUT_KEYS = ("timeout", "task_timeout")
HARD_TIMEOUT_KEYS = ("hard_timeout", "task_hard_timeout")
SETTINGS_SECTIONS = ("settings", "設定", "__settings__")
START_TIME_KEYS = ("start_time", "開始時間", "start")

def get_config_file() -> Path:
    override = os.environ.get(CONFIG_ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()
    return CONFIG_FILE

def _get_config() -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.optionxform = str  # 保持大小寫，避免任務名稱被轉小寫
    config_file = get_config_file()
    
    if not config_file.exists():
        # 建立預設設定檔
        config["settings"] = {
            "start_time": ""
        }
        config["點金手"] = {
            "enable": "Y",
            "command": "-m src.main --debug run-current-scene-task midas"
        }
        config["疾風呼喚"] = {
            "enable": "Y",
            "command": "call_of_the_gale/scripts/auto_shoot.py"
        }
        config["看廣告"] = {
            "enable": "N",
            "command": "ads2/cli.py run"
        }
        config["每日任務"] = {
            "enable": "N",
            "command": "-m src.main --debug run-all"
        }
        config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(config_file, "w", encoding="utf-8") as f:
            config.write(f)
        print(f"📄 [提示] 已自動建立任務設定檔: {config_file}")
    else:
        config.read(config_file, encoding="utf-8")
        
    return config

def get_tasks_to_run() -> list[str]:
    config = _get_config()
    tasks_to_run = []
    
    for section in config.sections():
        if section in SETTINGS_SECTIONS:
            continue
        enable_val = config.get(section, "enable", fallback="N").strip().upper()
        if enable_val in ("Y", "O", "1", "TRUE"):
            command_val = config.get(section, "command", fallback="").strip()
            if not command_val:
                print(f"ℹ️ [提示] 任務 '{section}' 已啟用但未設定 command，將以純路由任務執行。")
            tasks_to_run.append(section)
                
    return tasks_to_run

def get_start_time() -> str | None:
    config = _get_config()
    for section in SETTINGS_SECTIONS:
        if not config.has_section(section):
            continue
        for key in START_TIME_KEYS:
            value = config.get(section, key, fallback="").strip()
            if value:
                return value
    return None

def get_command_for_task(task_name: str) -> list[str]:
    config = _get_config()
    if config.has_section(task_name):
        command_val = config.get(task_name, "command", fallback="").strip()
        if command_val:
            # 支援 Windows 環境，shlex.split 處理反斜線時可能會有問題，但在這裡一般指令通常不會有太複雜的反斜線
            return shlex.split(command_val)
    return []

def get_task_timeout(task_name: str) -> str | None:
    config = _get_config()
    if not config.has_section(task_name):
        return None
    for key in TIMEOUT_KEYS:
        value = config.get(task_name, key, fallback="").strip()
        if value:
            return value
    return None

def get_task_hard_timeout(task_name: str) -> str | None:
    config = _get_config()
    if not config.has_section(task_name):
        return None
    for key in HARD_TIMEOUT_KEYS:
        value = config.get(task_name, key, fallback="").strip()
        if value:
            return value
    return None
