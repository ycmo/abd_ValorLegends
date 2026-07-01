from __future__ import annotations

from src.config import TASK_SPECS
from src_v2.task_runner import BaseTask


class MagicShopTask(BaseTask):
    spec = TASK_SPECS["magic_shop"]

    def execute(self) -> str:
        return "magic shop stub"
