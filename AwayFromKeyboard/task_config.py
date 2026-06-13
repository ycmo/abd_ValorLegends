import configparser
import shlex
import sys
from pathlib import Path

# 強制設定輸出為 UTF-8，以防在 Windows 終端機顯示中文出錯
sys.stdout.reconfigure(encoding='utf-8')

CONFIG_FILE = Path(__file__).resolve().parent / "afk_tasks.ini"

def _get_config() -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.optionxform = str  # 保持大小寫，避免任務名稱被轉小寫
    
    if not CONFIG_FILE.exists():
        # 建立預設設定檔
        config["點金手"] = {
            "enable": "Y",
            "command": "-m src.main --debug run-task midas"
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
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            config.write(f)
        print(f"📄 [提示] 已自動建立任務設定檔: {CONFIG_FILE.name}")
    else:
        config.read(CONFIG_FILE, encoding="utf-8")
        
    return config

def get_tasks_to_run() -> list[str]:
    config = _get_config()
    tasks_to_run = []
    
    for section in config.sections():
        enable_val = config.get(section, "enable", fallback="N").strip().upper()
        if enable_val in ("Y", "O", "1", "TRUE"):
            command_val = config.get(section, "command", fallback="").strip()
            if not command_val:
                print(f"⚠️ [警告] 任務 '{section}' 已啟用但未設定 command，將予以略過。")
            else:
                tasks_to_run.append(section)
                
    return tasks_to_run

def get_command_for_task(task_name: str) -> list[str]:
    config = _get_config()
    if config.has_section(task_name):
        command_val = config.get(task_name, "command", fallback="").strip()
        if command_val:
            # 支援 Windows 環境，shlex.split 處理反斜線時可能會有問題，但在這裡一般指令通常不會有太複雜的反斜線
            return shlex.split(command_val)
    return []
