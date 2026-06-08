from __future__ import annotations

from src.config import TASK_SPECS
from src.exceptions import MissingAssetError
from src.task_runner import BaseTask, TaskSceneAnchor


class BountyTask(BaseTask):
    spec = TASK_SPECS["bounty"]
    required_assets = (
        "task_label.png",
        "bounty_board_anchor.png",
        "dispatch_button.png",
        "refresh_button.png",
    )
    task_scene_anchors = (
        TaskSceneAnchor("bounty_board_anchor.png", threshold=0.82),
    )

    def execute(self) -> str:
        whitelist_dir = self.spec.asset_dir / "whitelist"
        if not whitelist_dir.exists() or not list(whitelist_dir.glob("*.png")):
            raise MissingAssetError(
                "Bounty whitelist is empty. Add resource templates under assets/tasks/bounty/whitelist/."
            )
        return "bounty whitelist framework ready; dispatch logic awaits concrete whitelist rules"
