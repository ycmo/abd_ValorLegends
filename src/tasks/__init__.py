from __future__ import annotations

from typing import Dict, Type

from src.config import TASK_ORDER
from src.task_runner import BaseTask
from src.tasks.arena import ArenaTask
from src.tasks.bounty import BountyTask
from src.tasks.campaign import CampaignTask
from src.tasks.endless_trial import EndlessTrialTask
from src.tasks.guild_dungeon import GuildDungeonTask
from src.tasks.guild_wish import GuildWishTask
from src.tasks.midas import MidasTask
from src.tasks.secret_realm import SecretRealmTask
from src.tasks.summon import SummonTask
from src.tasks.time_travel import TimeTravelTask


TASK_CLASSES: Dict[str, Type[BaseTask]] = {
    "arena": ArenaTask,
    "bounty": BountyTask,
    "campaign": CampaignTask,
    "endless_trial": EndlessTrialTask,
    "guild_dungeon": GuildDungeonTask,
    "guild_wish": GuildWishTask,
    "midas": MidasTask,
    "secret_realm": SecretRealmTask,
    "summon": SummonTask,
    "time_travel": TimeTravelTask,
}


def ordered_task_keys() -> tuple:
    return tuple(key for key in TASK_ORDER if key in TASK_CLASSES)

