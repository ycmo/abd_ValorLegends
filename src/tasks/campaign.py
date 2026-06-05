from __future__ import annotations

from src.config import TASK_SPECS
from src.task_runner import BattleOnceTask


class CampaignTask(BattleOnceTask):
    spec = TASK_SPECS["campaign"]
    win_required = False

