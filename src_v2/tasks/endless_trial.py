"""
endless_trial.py — Endless Trial (Phase 3)
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np

from src.config import TASK_SPECS, TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src_v2.task_runner import BaseTask, TaskSceneAnchor
from src.vision_matcher import MatchResult


class EndlessTrialScene(str, Enum):
    TRIAL_LOBBY = "trial_lobby"
    STAGE_DETAILS = "stage_details"
    STAGE_TEAM_GROUPING = "stage_team_grouping"
    BATTLE_READY = "battle_ready"
    BATTLE_END = "battle_end"
    BATTLE_FAIL = "battle_fail"
    STAGE_DETAILS_POST = "stage_details_post"
    TRIAL_LOBBY_POST = "trial_lobby_post"
    EXIT_CONFIRM = "exit_confirm"


@dataclass(frozen=True)
class EndlessTrialAction:
    name: str
    point: tuple[int, int]


class EndlessTrialTask(BaseTask):
    spec = TASK_SPECS["endless_trial"]
    required_assets = (
        "task_label.png",
        "task_label_wide.png",
        "trial_lobby_anchor.png",
        "trial_lobby_post_anchor.png",
        "stage_popup_anchor.png",
        "stage_details_post_anchor.png",
        "stage_team_grouping_anchor.png",
        "battle_ready_anchor.png",
        "battle_end_anchor.png",
        "battle_fail_anchor.png",
        "exit_confirm_anchor.png",
    )
    task_scene_anchors = (
        TaskSceneAnchor("trial_lobby_anchor.png", threshold=0.82),
        TaskSceneAnchor("trial_lobby_post_anchor.png", threshold=0.82),
        TaskSceneAnchor("stage_popup_anchor.png", threshold=0.82),
        TaskSceneAnchor("stage_details_post_anchor.png", threshold=0.82),
        TaskSceneAnchor("stage_team_grouping_anchor.png", threshold=0.82),
        TaskSceneAnchor("battle_ready_anchor.png", threshold=0.82),
        TaskSceneAnchor("battle_end_anchor.png", threshold=0.82),
        TaskSceneAnchor("battle_fail_anchor.png", threshold=0.82),
        TaskSceneAnchor("exit_confirm_anchor.png", threshold=0.82),
    )

    SCENE_TEMPLATES = {
        EndlessTrialScene.TRIAL_LOBBY: ("trial_lobby_anchor.png", 0.82),
        EndlessTrialScene.STAGE_DETAILS: ("stage_popup_anchor.png", 0.82),
        EndlessTrialScene.STAGE_TEAM_GROUPING: ("stage_team_grouping_anchor.png", 0.82),
        EndlessTrialScene.BATTLE_READY: ("battle_ready_anchor.png", 0.82),
        EndlessTrialScene.BATTLE_END: ("battle_end_anchor.png", 0.82),
        EndlessTrialScene.BATTLE_FAIL: ("battle_fail_anchor.png", 0.82),
        EndlessTrialScene.STAGE_DETAILS_POST: ("stage_details_post_anchor.png", 0.82),
        EndlessTrialScene.TRIAL_LOBBY_POST: ("trial_lobby_post_anchor.png", 0.82),
        EndlessTrialScene.EXIT_CONFIRM: ("exit_confirm_anchor.png", 0.82),
    }

    ENTRY_ACTION = EndlessTrialAction("enter trial tower", (190, 270))
    STAGE_CHALLENGE_ACTION = EndlessTrialAction("challenge stage", (898, 509))
    TEAM_CHALLENGE_ACTION = EndlessTrialAction("confirm team challenge", (690, 412))
    START_COMBAT_ACTION = EndlessTrialAction("start combat", (902, 480))
    CLOSE_WIN_ACTION = EndlessTrialAction("close battle result", (480, 480))
    CLOSE_FAIL_ACTION = EndlessTrialAction("close battle failure", (479, 507))
    BACK_ACTION = EndlessTrialAction("back", (61, 22))
    CONFIRM_EXIT_ACTION = EndlessTrialAction("confirm exit", (589, 401))

    MAX_ACTIONS = 18
    MAX_UNKNOWN_POLLS = 4
    BATTLE_WAIT_SECONDS = 5.0

    def execute(self) -> str:
        battle_finished = False
        battle_failed = False
        in_combat = False
        unknown_count = 0
        actions = []

        for _ in range(self.MAX_ACTIONS):
            screen = self.context.controller.screenshot()
            scene_match = self.detect_route_scene(screen)
            if scene_match is None:
                if in_combat:
                    self._log("Endless Trial combat in progress; waiting for result")
                    self._sleep(TRANSITION_WAIT_SECONDS)
                    continue
                unknown_count += 1
                if unknown_count > self.MAX_UNKNOWN_POLLS:
                    raise TaskFailedError("Endless Trial scene not recognized")
                self._sleep(TRANSITION_WAIT_SECONDS)
                continue

            unknown_count = 0
            scene, match = scene_match
            action = self._action_for_scene(scene, battle_finished=battle_finished, battle_failed=battle_failed)
            self._log(
                f"Endless Trial scene={scene.value} confidence={match.confidence:.3f} action={action.name}"
            )

            self.context.controller.tap(*action.point)
            actions.append(action.name)
            self._sleep(self.BATTLE_WAIT_SECONDS if action == self.START_COMBAT_ACTION else TRANSITION_WAIT_SECONDS)

            if scene == EndlessTrialScene.BATTLE_READY:
                in_combat = True
            elif scene == EndlessTrialScene.BATTLE_END:
                in_combat = False
                battle_finished = True
            elif scene == EndlessTrialScene.BATTLE_FAIL:
                in_combat = False
                battle_failed = True
            elif scene == EndlessTrialScene.TRIAL_LOBBY_POST and (battle_finished or battle_failed):
                outcome = "failed" if battle_failed else "completed"
                return f"endless trial {outcome}; actions: {', '.join(actions)}"

        raise TaskFailedError("Endless Trial exceeded action limit")

    def detect_route_scene(self, screen: np.ndarray) -> Optional[tuple[EndlessTrialScene, MatchResult]]:
        best_scene: Optional[EndlessTrialScene] = None
        best_match: Optional[MatchResult] = None
        for scene, (asset_name, threshold) in self.SCENE_TEMPLATES.items():
            path = self._asset_path(asset_name)
            match = self.context.matcher.match_template(screen, path, threshold=threshold)
            if match is None:
                continue
            if best_match is None or match.confidence > best_match.confidence:
                best_scene = scene
                best_match = match
        if best_scene is None or best_match is None:
            return None
        return best_scene, best_match

    def _action_for_scene(
        self,
        scene: EndlessTrialScene,
        *,
        battle_finished: bool,
        battle_failed: bool,
    ) -> EndlessTrialAction:
        if scene == EndlessTrialScene.TRIAL_LOBBY:
            return self.BACK_ACTION if battle_finished or battle_failed else self.ENTRY_ACTION
        if scene == EndlessTrialScene.TRIAL_LOBBY_POST:
            return self.BACK_ACTION
        if scene in (EndlessTrialScene.STAGE_DETAILS, EndlessTrialScene.STAGE_DETAILS_POST):
            return self.BACK_ACTION if battle_finished or battle_failed else self.STAGE_CHALLENGE_ACTION
        if scene == EndlessTrialScene.STAGE_TEAM_GROUPING:
            return self.TEAM_CHALLENGE_ACTION
        if scene == EndlessTrialScene.BATTLE_READY:
            return self.BACK_ACTION if battle_failed else self.START_COMBAT_ACTION
        if scene == EndlessTrialScene.BATTLE_END:
            return self.CLOSE_WIN_ACTION
        if scene == EndlessTrialScene.BATTLE_FAIL:
            return self.CLOSE_FAIL_ACTION
        if scene == EndlessTrialScene.EXIT_CONFIRM:
            return self.CONFIRM_EXIT_ACTION
        raise TaskFailedError(f"Unhandled Endless Trial scene: {scene.value}")

    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds)
