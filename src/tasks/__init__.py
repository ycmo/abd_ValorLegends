from __future__ import annotations

from typing import Dict, Type

from src.config import TASK_ORDER
from src.task_runner import BaseTask
from src.tasks.abyss import AbyssTask
from src.tasks.advanced_arena import AdvancedArenaTask
from src.tasks.arena import ArenaTask
from src.tasks.bounty import BountyTask
from src.tasks.campaign import CampaignTask
from src.tasks.endless_trial import EndlessTrialTask
from src.tasks.equipment_enhance import EquipmentEnhanceTask
from src.tasks.guild_dungeon import GuildDungeonTask
from src.tasks.guild_wish import GuildWishTask
from src.tasks.hero_contest import HeroContestTask
from src.tasks.hero_reroll_loop import HeroRerollLoopTask
from src.tasks.kingdom_vault import KingdomVaultTask
from src.tasks.magic_shop import MagicShopTask
from src.tasks.midas import MidasTask
from src.tasks.secret_realm import SecretRealmTask
from src.tasks.summon import SummonTask
from src.tasks.time_travel import TimeTravelTask
from src.tasks.wild_treasure import WildTreasureTask


TASK_CLASSES: Dict[str, Type[BaseTask]] = {
    "abyss": AbyssTask,
    "advanced_arena": AdvancedArenaTask,
    "arena": ArenaTask,
    "bounty": BountyTask,
    "campaign": CampaignTask,
    "endless_trial": EndlessTrialTask,
    "equipment_enhance": EquipmentEnhanceTask,
    "guild_dungeon": GuildDungeonTask,
    "guild_wish": GuildWishTask,
    "hero_contest": HeroContestTask,
    "hero_reroll_loop": HeroRerollLoopTask,
    "kingdom_vault": KingdomVaultTask,
    "magic_shop": MagicShopTask,
    "midas": MidasTask,
    "secret_realm": SecretRealmTask,
    "summon": SummonTask,
    "time_travel": TimeTravelTask,
    "wild_treasure": WildTreasureTask,
}


def ordered_task_keys() -> tuple:
    return tuple(key for key in TASK_ORDER if key in TASK_CLASSES)
