from __future__ import annotations

from src.config import TASK_SPECS
from src.task_runner import ActionStep, AssetSequenceTask


class GuildWishTask(AssetSequenceTask):
    spec = TASK_SPECS["guild_wish"]
    required_assets = ("task_label.png", "free_wish_button.png")
    steps = (
        ActionStep("free_wish", "free_wish_button.png"),
        ActionStep("confirm_reward", "confirm_button.png", optional=True),
    )

