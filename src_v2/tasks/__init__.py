"""
tasks/__init__.py — task 登記表

TASK_CLASSES：task_key → Task class 的映射
  已移植：guild_wish, secret_realm, summon, time_travel, midas, endless_trial, arena, guild_dungeon, bounty, campaign, magic_shop
  其餘 task 待後續 Phase 陸續移入。

啟動時驗證：
  TASK_CLASSES 的 key 集合必須是 src_v2.config.TASK_SPECS 的子集（包含 src + v2 專屬 task），
  否則 raise AssertionError（防呆）。
  ads 是跨遊戲廣告基礎設施，不進 TASK_SPECS 驗證範圍，獨立 bypass。
"""
from __future__ import annotations

from typing import Dict, Type

from src_v2.config import TASK_SPECS as _ALL_TASK_SPECS
from src_v2.task_runner import BaseTask
from src_v2.tasks.guild_wish import GuildWishTask

from src_v2.tasks.secret_realm import SecretRealmTask
from src_v2.tasks.summon import SummonTask
from src_v2.tasks.time_travel import TimeTravelTask
from src_v2.tasks.midas import MidasTask
from src_v2.tasks.endless_trial import EndlessTrialTask
from src_v2.tasks.arena import ArenaTask
from src_v2.tasks.guild_dungeon import GuildDungeonTask
from src_v2.tasks.bounty import BountyTask
from src_v2.tasks.campaign import CampaignTask
from src_v2.tasks.magic_shop import MagicShopTask
from src_v2.tasks.hero_contest import HeroContestTask
from src_v2.tasks.abyss import AbyssTask
from src_v2.tasks.call_of_the_gale import CallOfTheGaleTask

TASK_CLASSES: Dict[str, Type[BaseTask]] = {
    "guild_wish": GuildWishTask,
    "secret_realm": SecretRealmTask,
    "summon": SummonTask,
    "time_travel": TimeTravelTask,
    "midas": MidasTask,
    "endless_trial": EndlessTrialTask,
    "arena": ArenaTask,
    "guild_dungeon": GuildDungeonTask,
    "bounty": BountyTask,
    "campaign": CampaignTask,
    "magic_shop": MagicShopTask,
    "hero_contest": HeroContestTask,
    "abyss": AbyssTask,
    "call_of_the_gale": CallOfTheGaleTask,
}

# 防呆：確認所有 key 都是合法的 task_key
# ads 是跨遊戲基礎設施，不在 VL TASK_SPECS，單獨 bypass
_vl_task_keys = {k for k in TASK_CLASSES if k != "ads"}
_invalid = _vl_task_keys - set(_ALL_TASK_SPECS)
assert not _invalid, f"TASK_CLASSES contains task keys not in TASK_SPECS: {_invalid}"
