from __future__ import annotations
from src.adb_controller import DeviceController
from src.vision_matcher import VisionMatcher
from switch_account.switch_account import wait_for_game_entry

def reenter_game(controller: DeviceController, matcher: VisionMatcher) -> bool:
    """
    [Facade] 代理呼叫切帳號模組中已驗證穩定的登入邏輯。
    包含：判斷使用者條款 -> 點擊進入遊戲 -> 等待掛機寶箱。

    此代理模式確保了外部呼叫的語意隔離，並將核心程式碼風險降至最低。
    """
    return wait_for_game_entry(controller, matcher)
