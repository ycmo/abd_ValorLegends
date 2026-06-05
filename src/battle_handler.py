from __future__ import annotations

import time
from enum import Enum
from pathlib import Path
from typing import Optional

from src.adb_controller import DeviceController
from src.config import BATTLE_POLL_SECONDS, SHARED_ASSETS_DIR, TRANSITION_WAIT_SECONDS
from src.exceptions import MissingAssetError, TaskFailedError
from src.scene_detector import Scene, SceneDetector
from src.vision_matcher import VisionMatcher


class BattleResult(str, Enum):
    WIN = "win"
    LOSS = "loss"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"


class BattleHandler:
    def __init__(
        self,
        controller: DeviceController,
        matcher: VisionMatcher,
        detector: SceneDetector,
    ):
        self.controller = controller
        self.matcher = matcher
        self.detector = detector

    def tap_challenge(self, task_asset_dir: Path) -> None:
        candidates = [
            task_asset_dir / "challenge_button.png",
            SHARED_ASSETS_DIR / "challenge_button.png",
        ]
        screen = self.controller.screenshot()
        match = self.matcher.match_any(screen, candidates, threshold=0.80)
        if match is None:
            raise MissingAssetError(
                "Cannot find challenge button. Expected task challenge_button.png or shared challenge_button.png."
            )
        self.controller.tap(*match.center)
        time.sleep(TRANSITION_WAIT_SECONDS)

    def wait_for_result(self, timeout_seconds: float = 150.0) -> BattleResult:
        deadline = time.time() + timeout_seconds
        win_anchor = SHARED_ASSETS_DIR / "battle_victory_anchor.png"
        loss_anchor = SHARED_ASSETS_DIR / "battle_defeat_anchor.png"

        while time.time() < deadline:
            screen = self.controller.screenshot()
            if win_anchor.exists() and self.matcher.match_template(screen, win_anchor, threshold=0.80):
                return BattleResult.WIN
            if loss_anchor.exists() and self.matcher.match_template(screen, loss_anchor, threshold=0.80):
                return BattleResult.LOSS
            if self.detector.detect(screen).scene == Scene.BATTLE_RESULT:
                return BattleResult.UNKNOWN
            time.sleep(BATTLE_POLL_SECONDS)
        return BattleResult.TIMEOUT

    def dismiss_result(self) -> None:
        screen = self.controller.screenshot()
        height, width = screen.shape[:2]
        self.controller.tap(width // 2, int(height * 0.82))
        time.sleep(TRANSITION_WAIT_SECONDS)
        self.controller.tap(width // 2, int(height * 0.82))
        time.sleep(TRANSITION_WAIT_SECONDS)

    def confirm_exit_abandon(self) -> None:
        yes_button = SHARED_ASSETS_DIR / "exit_yes_button.png"
        if not yes_button.exists():
            raise MissingAssetError(f"Missing exit confirmation yes button template: {yes_button}")
        screen = self.controller.screenshot()
        match = self.matcher.match_template(screen, yes_button, threshold=0.80)
        if match is None:
            raise TaskFailedError("Exit confirmation was expected but yes button was not found")
        self.controller.tap(*match.center)
        time.sleep(TRANSITION_WAIT_SECONDS)

