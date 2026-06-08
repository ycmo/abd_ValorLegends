# Ads2 Changelog

## [2026-06-07] - 無腦大迴圈重構與防卡死優化

### Added
- 新增 `AppRecoveryNeeded` 例外類別，作為處理截圖逾時與外部廣告跳轉的緊急中斷機制。
- 新增 `_safe_screenshot()` 封裝截圖行為，遇到截圖逾時 (`TimeoutExpired`) 時不再崩潰，而是主動拋出 `AppRecoveryNeeded`。
- 獨立出 `recover_from_app_jump(screen, reason)` 復原方法，將「按 Home 鍵 + Monkey 喚醒遊戲」的自癒邏輯集中管理。

### Changed
- 將主迴圈內所有 `self.device.screenshot()` 替換為 `self._safe_screenshot()`。
- 大幅簡化「連續點擊」邏輯：
  - 移除了全域的 `self.click_counts` 狀態管理。
  - 將「免費廣告」、「關閉按鈕」、「獲得道具」的點擊流程統一為：`for i in range(1, 11)` 迴圈（最多 10 次，循環 5 個不同點擊位置）。
  - 在迴圈內每次點擊後直接呼叫 `_safe_screenshot()` 原地比對，若確認按鈕已消失則立即 `break`。
  - 若免費廣告按鈕成功消失，直接進入 15 秒深度休眠 (`self.ad_wait`)；若點滿 10 次仍未消失，則拋出 `AppRecoveryNeeded` 強制自癒。
- 在大迴圈的 `while True:` 內層加上了 `try...except AppRecoveryNeeded`，確保發生任何卡死狀況時，都能立刻中斷所有內層驗證迴圈並乾淨地重啟遊戲畫面。
