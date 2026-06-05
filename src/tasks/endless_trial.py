from __future__ import annotations

from src.config import TASK_SPECS
from src.task_runner import BattleOnceTask


class EndlessTrialTask(BattleOnceTask):
    spec = TASK_SPECS["endless_trial"]
    required_assets = (
        "task_label.png",
        "challenge_button.png",
        "trial_lobby_anchor.png",
        "stage_popup_anchor.png",
    )
    win_required = False

    def execute(self) -> str:
        message = super().execute()
        # Multi-team exit confirmation is route-specific and must use exit_yes_button.png.
        return message

