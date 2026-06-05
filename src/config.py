from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Tuple


ROOT_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT_DIR / "assets"
SHARED_ASSETS_DIR = ASSETS_DIR / "shared"
TASK_ASSETS_DIR = ASSETS_DIR / "tasks"
RAW_CAPTURES_DIR = ASSETS_DIR / "raw_captures"
CAPTURES_DIR = ROOT_DIR / "captures"
MANUAL_SCREENSHOTS_DIR = ROOT_DIR / "manual_screenshots"

DEFAULT_SERIAL = os.environ.get("VL_ADB_SERIAL", "emulator-5554")
EXPECTED_SCREEN_SIZE: Tuple[int, int] = (960, 540)

MATCH_THRESHOLD = 0.82
TASK_LABEL_THRESHOLD = 0.78
GO_BUTTON_THRESHOLD = 0.80
SCENE_THRESHOLD = 0.82

SCREENSHOT_INTERVAL_SECONDS = 1.5
TRANSITION_WAIT_SECONDS = 2.0
BATTLE_POLL_SECONDS = 3.0
TAP_COOLDOWN_SECONDS = 1.0


@dataclass(frozen=True)
class ResourcePolicy:
    allowed_actions: Tuple[str, ...] = ()
    stop_conditions: Tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class TaskSpec:
    key: str
    display_name: str
    manual_dir: str
    kind: str
    policy: ResourcePolicy = field(default_factory=ResourcePolicy)

    @property
    def asset_dir(self) -> Path:
        return TASK_ASSETS_DIR / self.key

    @property
    def task_label_asset(self) -> Path:
        return self.asset_dir / "task_label.png"


TASK_SPECS: Dict[str, TaskSpec] = {
    "arena": TaskSpec(
        key="arena",
        display_name="競技場",
        manual_dir="競技場",
        kind="battle",
        policy=ResourcePolicy(
            allowed_actions=("challenge_opponents_under_7000k",),
            stop_conditions=("ocr_uncertain", "all_opponents_over_7000k"),
            notes="Arena must avoid opponents above 7000k and keep fighting until at least 8 opponents are accumulated.",
        ),
    ),
    "bounty": TaskSpec(
        key="bounty",
        display_name="懸賞委託",
        manual_dir="懸賞委託",
        kind="dispatch",
        policy=ResourcePolicy(
            allowed_actions=("accept_whitelist_only", "free_refresh_when_all_blacklist_or_below_4_star"),
            stop_conditions=("no_whitelist_match", "paid_refresh_required", "uncertain_resource"),
            notes="Whitelist first. If unsure, stop and let the user add rules.",
        ),
    ),
    "campaign": TaskSpec(
        key="campaign",
        display_name="戰役關卡",
        manual_dir="戰役關卡",
        kind="battle",
        policy=ResourcePolicy(
            allowed_actions=("fight_once",),
            stop_conditions=("cannot_start_battle",),
            notes="Win is not required for daily-task completion.",
        ),
    ),
    "endless_trial": TaskSpec(
        key="endless_trial",
        display_name="無盡試煉",
        manual_dir="無盡試煉",
        kind="battle",
        policy=ResourcePolicy(
            allowed_actions=("fight_first_team_once", "confirm_abandon_on_exit"),
            stop_conditions=("cannot_start_battle",),
            notes="Every 5 stages may show multi-team UI. Fight first team once, then exit.",
        ),
    ),
    "guild_dungeon": TaskSpec(
        key="guild_dungeon",
        display_name="公會副本",
        manual_dir="公會副本",
        kind="battle",
        policy=ResourcePolicy(
            allowed_actions=("fight_once", "retry_once_on_loss"),
            stop_conditions=("loss_after_retry", "not_in_guild"),
            notes="Guild dungeon should win; current expectation is that it usually wins.",
        ),
    ),
    "guild_wish": TaskSpec(
        key="guild_wish",
        display_name="公會祈願",
        manual_dir="公會祈願",
        kind="collect",
        policy=ResourcePolicy(
            allowed_actions=("free_wish",),
            stop_conditions=("paid_wish_required",),
            notes="Do not tap 100/200 gem wishes.",
        ),
    ),
    "midas": TaskSpec(
        key="midas",
        display_name="點金手",
        manual_dir="點金手",
        kind="collect",
        policy=ResourcePolicy(
            allowed_actions=("free", "gem_20", "gem_50"),
            stop_conditions=("next_paid_tier_after_50_gems",),
            notes="Tap free, 20 gem, and 50 gem Midas only.",
        ),
    ),
    "secret_realm": TaskSpec(
        key="secret_realm",
        display_name="秘境副本",
        manual_dir="秘境副本",
        kind="collect",
        policy=ResourcePolicy(
            allowed_actions=("buy_lost_forest_twice", "sweep_all"),
            stop_conditions=("additional_purchase_required", "wrong_realm"),
            notes="Buy Lost Forest two times by pressing + once, then sweep all.",
        ),
    ),
    "summon": TaskSpec(
        key="summon",
        display_name="高級召喚",
        manual_dir="高級召喚",
        kind="collect",
        policy=ResourcePolicy(
            allowed_actions=("free_summon",),
            stop_conditions=("ticket_or_gem_summon_required",),
            notes="Free summon only.",
        ),
    ),
    "time_travel": TaskSpec(
        key="time_travel",
        display_name="時間旅行",
        manual_dir="時間旅行",
        kind="collect",
        policy=ResourcePolicy(
            allowed_actions=("free", "gem_50"),
            stop_conditions=("gem_100_tier",),
            notes="Tap free and 50 gem time travel only. Stop before 100 gem.",
        ),
    ),
}

TASK_ORDER: Tuple[str, ...] = tuple(sorted(TASK_SPECS))
