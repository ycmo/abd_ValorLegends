from __future__ import annotations

from src.config import TASK_SPECS
from src.task_runner import BattleOnceTask


class GuildDungeonTask(BattleOnceTask):
    spec = TASK_SPECS["guild_dungeon"]
    required_assets = (
        "task_label.png",
        "dungeon_map_anchor.png",
        "challenge_button.png",
    )
    win_required = True

