"""
src_v2/config.py — src_v2 自己的 config 補充層

合併 src.config.TASK_SPECS（所有 VL daily + independent task）
加上 src_v2 專屬的 task spec（ads、call_of_the_gale）。

所有 src_v2 task 的 spec 查表請 import 這個模組的 TASK_SPECS，
而不是直接 import src.config.TASK_SPECS。
"""
from typing import Dict
from src.config import TaskSpec, ResourcePolicy, TASK_SPECS as _SRC_TASK_SPECS

# src_v2 新增的 task spec（不在 src/config.py 的）
_V2_TASK_SPECS: Dict[str, TaskSpec] = {
    "call_of_the_gale": TaskSpec(
        key="call_of_the_gale",
        display_name="疾風呼喚",
        daily_text="",
        manual_dir="疾風呼喚",
        kind="independent",
        policy=ResourcePolicy(
            allowed_actions=("launch_darts", "upgrade_with_rice_balls", "depart", "skip_animation", "continue_challenge"),
            stop_conditions=("scrolls_exhausted",),
            notes="Independent mini-game. Run until scrolls exhausted.",
        ),
    ),
    "ads": TaskSpec(
        key="ads",
        display_name="看廣告",
        daily_text="",
        manual_dir="看廣告",
        kind="independent",
        policy=ResourcePolicy(
            allowed_actions=("watch_ad", "close_ad", "retry_on_unexpected_screen"),
            stop_conditions=("no_free_ad_button", "max_retries_reached"),
            notes="Cross-game ad-watching infrastructure. Profile-based configuration.",
        ),
    ),
}

# 合併後的完整 TASK_SPECS（src + v2 新增），所有 src_v2 task 查表用這個
TASK_SPECS: Dict[str, TaskSpec] = {**_SRC_TASK_SPECS, **_V2_TASK_SPECS}
