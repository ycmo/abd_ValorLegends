from __future__ import annotations

from src.config import TASK_SPECS
from src_v2.task_runner import BaseTask


class CampaignTask(BaseTask):
    spec = TASK_SPECS["campaign"]

    def execute(self) -> str:
        return "campaign stub"
