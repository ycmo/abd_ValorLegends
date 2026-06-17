"""
tasks/__init__.py — task 登記表

TASK_CLASSES：task_key → Task class 的映射
  已移植：guild_wish、secret_realm
  其餘 task 待後續 Phase 陸續移入。

啟動時驗證：
  TASK_CLASSES 的 key 集合必須是 src.config.TASK_ORDER 的子集，
  否則 raise AssertionError（防呆）。
"""
from __future__ import annotations

from typing import Dict, Type

from src.config import TASK_ORDER
from src_v2.task_runner import BaseTask
from src_v2.tasks.guild_wish import GuildWishTask

from src_v2.tasks.secret_realm import SecretRealmTask
from src_v2.tasks.summon import SummonTask
from src_v2.tasks.time_travel import TimeTravelTask
from src_v2.tasks.midas import MidasTask
from src_v2.tasks.endless_trial import EndlessTrialTask
from src_v2.tasks.arena import ArenaTask

TASK_CLASSES: Dict[str, Type[BaseTask]] = {
    "guild_wish": GuildWishTask,
    "secret_realm": SecretRealmTask,
    "summon": SummonTask,
    "time_travel": TimeTravelTask,
    "midas": MidasTask,
    "endless_trial": EndlessTrialTask,
    "arena": ArenaTask,
    # Phase 3: "bounty", "campaign", "endless_trial", "guild_dungeon", "magic_shop"
}

# 防呆：確認所有 key 都是合法的 task_key
_invalid = set(TASK_CLASSES) - set(TASK_ORDER)
assert not _invalid, f"TASK_CLASSES contains unknown task keys: {_invalid}"
