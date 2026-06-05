from __future__ import annotations

from src.config import TASK_SPECS
from src.exceptions import MissingAssetError, TaskFailedError
from src.ocr_utils import extract_arena_powers_hash
from src.task_runner import BaseTask


class ArenaTask(BaseTask):
    spec = TASK_SPECS["arena"]
    required_assets = (
        "task_label.png",
        "arena_main_anchor.png",
        "opponent_list_anchor.png",
        "challenge_button.png",
        "refresh_button.png",
        "continue_button.png",
    )
    max_power_k = 7000

    def execute(self) -> str:
        screen = self.context.controller.screenshot()
        powers = extract_arena_powers_hash(screen)
        valid = [item for item in powers if 0 <= item["power_k"] <= self.max_power_k]
        if not valid:
            raise TaskFailedError("No arena opponent under or equal to 7000k was detected")
        raise MissingAssetError(
            "Arena opponent tap mapping is intentionally not finalized yet. "
            "OCR policy is in place; add opponent-row templates before enabling taps."
        )

