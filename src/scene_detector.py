from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional, Tuple

import numpy as np

from src.config import SCENE_THRESHOLD, SHARED_ASSETS_DIR
from src.vision_matcher import MatchResult, Roi, VisionMatcher


class Scene(str, Enum):
    UNKNOWN = "unknown"
    LOADING = "loading"
    MAIN = "main"
    DAILY_TASKS = "daily_tasks"
    BATTLE_PREP = "battle_prep"
    IN_BATTLE = "in_battle"
    BATTLE_RESULT = "battle_result"
    EXIT_CONFIRM = "exit_confirm"
    DIALOG = "dialog"


@dataclass(frozen=True)
class SceneAnchor:
    scene: Scene
    path: Path
    threshold: float = SCENE_THRESHOLD
    roi: Optional[Roi] = None


@dataclass(frozen=True)
class SceneDetection:
    scene: Scene
    confidence: float = 0.0
    match: Optional[MatchResult] = None
    reason: str = ""


DEFAULT_ANCHORS: Tuple[SceneAnchor, ...] = (
    SceneAnchor(Scene.DAILY_TASKS, SHARED_ASSETS_DIR / "daily_tasks_title.png"),
    SceneAnchor(Scene.MAIN, SHARED_ASSETS_DIR / "main_lobby_anchor.png"),
    SceneAnchor(Scene.LOADING, SHARED_ASSETS_DIR / "loading_anchor.png", threshold=0.78),
    SceneAnchor(Scene.BATTLE_PREP, SHARED_ASSETS_DIR / "challenge_button.png", threshold=0.80),
    SceneAnchor(Scene.BATTLE_RESULT, SHARED_ASSETS_DIR / "battle_victory_anchor.png", threshold=0.80),
    SceneAnchor(Scene.BATTLE_RESULT, SHARED_ASSETS_DIR / "battle_defeat_anchor.png", threshold=0.80),
    SceneAnchor(Scene.EXIT_CONFIRM, SHARED_ASSETS_DIR / "exit_confirm_anchor.png", threshold=0.80),
    SceneAnchor(Scene.DIALOG, SHARED_ASSETS_DIR / "dialog_close_button.png", threshold=0.84),
)


class SceneDetector:
    def __init__(
        self,
        matcher: VisionMatcher,
        anchors: Iterable[SceneAnchor] = DEFAULT_ANCHORS,
    ):
        self.matcher = matcher
        self.anchors = tuple(anchors)

    def detect(self, screen: np.ndarray) -> SceneDetection:
        best: Optional[SceneDetection] = None
        usable_anchor_count = 0
        for anchor in self.anchors:
            if not anchor.path.exists():
                continue
            usable_anchor_count += 1
            match = self.matcher.match_template(
                screen,
                anchor.path,
                threshold=anchor.threshold,
                roi=anchor.roi,
            )
            if match is None:
                continue
            detection = SceneDetection(anchor.scene, match.confidence, match)
            if best is None or detection.confidence > best.confidence:
                best = detection

        if best is not None:
            return best
        if usable_anchor_count == 0:
            return SceneDetection(Scene.UNKNOWN, reason="no scene anchors available")
        return SceneDetection(Scene.UNKNOWN, reason="no scene anchor matched")

    def is_scene(self, screen: np.ndarray, scene: Scene) -> bool:
        return self.detect(screen).scene == scene

