from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import ASSETS_DIR, MANUAL_SCREENSHOTS_DIR, ROOT_DIR
from src.vision_matcher import read_image, write_image
import cv2
import numpy as np


Rect = Tuple[int, int, int, int]


@dataclass(frozen=True)
class CropSpec:
    source: Path
    rect: Rect
    output: Path
    note: str
    text_mask: bool = False


def manual(*parts: str) -> Path:
    return MANUAL_SCREENSHOTS_DIR.joinpath(*parts)


def legacy(*parts: str) -> Path:
    return ROOT_DIR.joinpath("legacy", "20260604_pre_rewrite", *parts)


def asset(*parts: str) -> Path:
    return ASSETS_DIR.joinpath(*parts)


CROPS: Tuple[CropSpec, ...] = (
    # Shared daily-task navigation templates.
    CropSpec(
        manual("點金手", "001_每日任務.png"),
        (106, 5, 116, 35),
        asset("shared", "daily_tasks_title.png"),
        "每日任務 title",
    ),
    CropSpec(
        manual("點金手", "001_每日任務.png"),
        (769, 305, 143, 39),
        asset("shared", "go_button.png"),
        "unannotated blue 前往 button",
    ),
    CropSpec(
        manual("廣告", "001_主畫面.png"),
        (166, 488, 164, 52),
        asset("shared", "main_lobby_anchor.png"),
        "野外 bottom-nav selected anchor",
    ),
    CropSpec(
        manual("廣告", "001_主畫面.png"),
        (902, 20, 58, 68),
        asset("shared", "daily_tasks_entry.png"),
        "main-screen 任務 entry",
    ),
    CropSpec(
        manual("廣告", "002_王國事件.png"),
        (23, 4, 56, 36),
        asset("shared", "back_button.png"),
        "top-left in-game back button",
    ),
    # Daily-task row labels. These crop only the text, avoiding colored annotation boxes.
    CropSpec(
        manual("競技場", "001_每日任務.png"),
        (228, 333, 205, 22),
        asset("tasks", "arena", "task_label.png"),
        "普通競技場挑戰2次",
        True,
    ),
    CropSpec(
        manual("懸賞委託", "001_每日任務.png"),
        (228, 379, 190, 22),
        asset("tasks", "bounty", "task_label.png"),
        "接取2個懸賞委託",
        True,
    ),
    CropSpec(
        manual("戰役關卡", "001_每日任務.png"),
        (228, 249, 190, 22),
        asset("tasks", "campaign", "task_label.png"),
        "挑戰1次戰役關卡",
        True,
    ),
    CropSpec(
        manual("無盡試煉", "001_每日任務.png"),
        (228, 300, 190, 22),
        asset("tasks", "endless_trial", "task_label.png"),
        "挑戰1次無盡試煉",
        True,
    ),
    CropSpec(
        manual("公會副本", "001_每日任務.png"),
        (228, 260, 245, 22),
        asset("tasks", "guild_dungeon", "task_label.png"),
        "成功通關2次公會副本挑戰",
        True,
    ),
    CropSpec(
        manual("公會祈願", "001_每日任務.png"),
        (228, 406, 190, 22),
        asset("tasks", "guild_wish", "task_label.png"),
        "進行1次公會祈願",
        True,
    ),
    CropSpec(
        manual("點金手", "001_每日任務.png"),
        (282, 376, 48, 16),
        asset("tasks", "midas", "task_label.png"),
        "點金手",
        True,
    ),
    CropSpec(
        manual("秘境副本", "001_每日任務.png"),
        (228, 315, 255, 22),
        asset("tasks", "secret_realm", "task_label.png"),
        "挑戰/掃蕩任意秘境副本3次",
        True,
    ),
    CropSpec(
        manual("高級召喚", "001_每日任務.png"),
        (228, 271, 240, 22),
        asset("tasks", "summon", "task_label.png"),
        "完成1次高級契約召喚",
        True,
    ),
    CropSpec(
        manual("時間旅行", "001_每日任務.png"),
        (228, 358, 190, 22),
        asset("tasks", "time_travel", "task_label.png"),
        "完成1次時間旅行",
        True,
    ),
    # Arena task action templates. Crops avoid red manual annotation boxes.
    CropSpec(
        manual("競技場", "002_選擇挑戰.png"),
        (800, 10, 80, 80),
        asset("tasks", "arena", "arena_main_anchor.png"),
        "競技場 main page shop/top-right anchor",
    ),
    CropSpec(
        manual("競技場", "003_選擇對手.png"),
        (800, 10, 80, 80),
        asset("tasks", "arena", "opponent_list_anchor.png"),
        "競技場 multi-challenge opponent dialog close anchor",
    ),
    CropSpec(
        manual("競技場", "002_選擇挑戰.png"),
        (480, 486, 142, 31),
        asset("tasks", "arena", "multi_challenge_button.png"),
        "競技場 多人挑戰 button interior",
    ),
    CropSpec(
        manual("競技場", "003_選擇對手.png"),
        (820, 440, 35, 35),
        asset("tasks", "arena", "challenge_button.png"),
        "競技場 bottom-right green challenge button background",
    ),
    CropSpec(
        manual("競技場", "004_點擊繼續.png"),
        (450, 506, 63, 18),
        asset("tasks", "arena", "continue_button.png"),
        "競技場 點擊繼續 button interior",
    ),
    CropSpec(
        manual("競技場", "005_退出競技場.png"),
        (23, 12, 47, 50),
        asset("tasks", "arena", "arena_back_button.png"),
        "競技場 top-left back arrow interior",
    ),
    # Summon task action templates.
    CropSpec(
        manual("高級召喚", "002_高級召喚.png"),
        (104, 354, 88, 23),
        asset("tasks", "summon", "advanced_contract_label.png"),
        "高級召喚 selected contract label",
    ),
    CropSpec(
        manual("高級召喚", "002_高級召喚.png"),
        (56, 401, 168, 39),
        asset("tasks", "summon", "free_summon_button.png"),
        "高級召喚 free button",
    ),
    CropSpec(
        manual("高級召喚", "003_按確定.png"),
        (548, 445, 135, 31),
        asset("tasks", "summon", "confirm_button.png"),
        "summon result confirm button interior",
    ),
    CropSpec(
        manual("高級召喚", "004_按離開.png"),
        (38, 23, 36, 33),
        asset("tasks", "summon", "leave_button.png"),
        "summon screen back arrow",
    ),
    # Secret Realm task action templates. Crops avoid user-added red/green annotation boxes.
    CropSpec(
        manual("秘境副本", "002_秘境副本選單.png"),
        (49, 269, 112, 47),
        asset("tasks", "secret_realm", "lost_forest_tab.png"),
        "unselected 迷失森林 tab interior",
    ),
    CropSpec(
        manual("秘境副本", "003_購買迷失森林.png"),
        (43, 256, 153, 68),
        asset("tasks", "secret_realm", "lost_forest_selected_tab.png"),
        "selected 迷失森林 tab",
    ),
    CropSpec(
        manual("秘境副本", "005_掃蕩全部.png"),
        (321, 59, 20, 20),
        asset("tasks", "secret_realm", "realm_attempt_entry_plus_button.png"),
        "top 副本次數 plus button",
    ),
    CropSpec(
        manual("秘境副本", "004_購買2次.png"),
        (434, 90, 93, 24),
        asset("tasks", "secret_realm", "purchase_dialog_title.png"),
        "副本次數 dialog title",
    ),
    CropSpec(
        manual("秘境副本", "004_購買2次.png"),
        (384, 166, 192, 28),
        asset("tasks", "secret_realm", "daily_purchase_count_5_5.png"),
        "每日購買次數 5/5",
    ),
    CropSpec(
        manual("秘境副本", "004_購買2次.png"),
        (588, 274, 25, 27),
        asset("tasks", "secret_realm", "purchase_quantity_plus_button.png"),
        "purchase dialog plus button interior",
    ),
    CropSpec(
        manual("秘境副本", "004_購買2次.png"),
        (405, 272, 151, 32),
        asset("tasks", "secret_realm", "purchase_quantity_two.png"),
        "purchase dialog quantity set to 2",
    ),
    CropSpec(
        manual("秘境副本", "004_購買2次.png"),
        (409, 407, 143, 36),
        asset("tasks", "secret_realm", "purchase_confirm_button.png"),
        "purchase confirm button interior",
    ),
    CropSpec(
        manual("秘境副本", "003_購買迷失森林.png"),
        (852, 428, 91, 92),
        asset("tasks", "secret_realm", "sweep_all_button.png"),
        "掃蕩全部 button",
    ),
    CropSpec(
        manual("秘境副本", "005_掃蕩全部.png"),
        (8, 5, 34, 30),
        asset("tasks", "secret_realm", "secret_realm_back_button.png"),
        "Secret Realm top-left back arrow",
    ),
    # Time Travel task action templates. Crops use the interior of annotated buttons.
    CropSpec(
        manual("時間旅行", "002_時間旅行.png"),
        (606, 102, 141, 36),
        asset("tasks", "time_travel", "time_travel_title.png"),
        "時間旅行 dialog title",
    ),
    CropSpec(
        manual("時間旅行", "002_時間旅行.png"),
        (681, 406, 137, 28),
        asset("tasks", "time_travel", "free_button.png"),
        "時間旅行 free button interior",
    ),
    CropSpec(
        manual("時間旅行", "002_時間旅行50鑽.png"),
        (725, 408, 57, 25),
        asset("tasks", "time_travel", "gem_50_button.png"),
        "時間旅行 50 gem price text",
    ),
    CropSpec(
        manual("時間旅行", "004_時間旅行100鑽.png"),
        (672, 405, 148, 29),
        asset("tasks", "time_travel", "gem_100_button.png"),
        "時間旅行 100 gem button interior",
    ),
    CropSpec(
        manual("時間旅行", "002_時間旅行50鑽.png"),
        (503, 405, 144, 29),
        asset("tasks", "time_travel", "cancel_button.png"),
        "時間旅行 cancel button interior",
    ),
    CropSpec(
        manual("時間旅行", "003_獲得道具.png"),
        (396, 121, 170, 44),
        asset("tasks", "time_travel", "reward_title.png"),
        "時間旅行 reward overlay title",
    ),
    # Midas task action templates. Some active button states are only available in legacy live captures.
    CropSpec(
        manual("點金手", "002_點金手.png"),
        (431, 67, 97, 26),
        asset("tasks", "midas", "midas_title.png"),
        "點金手 dialog title",
    ),
    CropSpec(
        legacy("experiments", "midas_route", "debug", "step_20260604_063558_002_midas.png"),
        (185, 428, 140, 36),
        asset("tasks", "midas", "free_button.png"),
        "active 點金手 free button",
    ),
    CropSpec(
        legacy("experiments", "midas_route", "debug", "step_20260604_063558_002_midas.png"),
        (398, 428, 138, 36),
        asset("tasks", "midas", "gem_20_button.png"),
        "active 點金手 20 gem button",
    ),
    CropSpec(
        legacy("experiments", "midas_route", "debug", "step_20260604_063558_002_midas.png"),
        (609, 428, 139, 36),
        asset("tasks", "midas", "gem_50_button.png"),
        "active 點金手 50 gem button",
    ),
    CropSpec(
        legacy("experiments", "midas_route", "debug", "step_20260604_063558_002_midas.png"),
        (769, 65, 27, 28),
        asset("tasks", "midas", "midas_close_button.png"),
        "點金手 close button",
    ),
    CropSpec(
        legacy("experiments", "midas_route", "debug", "step_20260604_063602_003_midas_reward.png"),
        (407, 135, 146, 33),
        asset("tasks", "midas", "reward_title.png"),
        "點金手 reward overlay title",
    ),
)


def crop_one(spec: CropSpec) -> Path:
    if not spec.source.exists():
        raise FileNotFoundError(spec.source)
    image = read_image(spec.source)
    x, y, w, h = spec.rect
    cropped = image[y : y + h, x : x + w]
    if cropped.size == 0:
        raise ValueError(f"empty crop for {spec.output}: {spec.rect}")
    if spec.text_mask:
        cropped = with_text_alpha(cropped)
    return write_image(spec.output, cropped)


def with_text_alpha(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    alpha = np.where(gray > 115, 255, 0).astype("uint8")
    rgba = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = alpha
    return rgba


def build_all(crops: Iterable[CropSpec] = CROPS) -> None:
    for spec in crops:
        out = crop_one(spec)
        print(f"{out.relative_to(ASSETS_DIR.parent)} <- {spec.note}")


def main() -> int:
    build_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
