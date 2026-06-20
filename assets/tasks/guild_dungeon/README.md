# guild_dungeon

公會副本是獨立邏輯較多的戰鬥任務，已接入 `run-all`。

## Assets

Required/current assets:

```text
task_label.png
task_label_wide.png
map_title_anchor.png
sword_node_anchor.png
flag_node_anchor.png
remaining_attempt_anchor.png
bonus_reward_anchor.png
bonus_reward_anchor_alt.png
challenge_button.png
outpost_close_button.png
continue_button.png
back_button.png
remaining_attempts_zero_anchor.png
```

Manual reference screenshots:

```text
manual_screenshots/公會副本/
```

## Requirements

1. 從公會副本地圖開始操作。
2. 地圖可以左右滑動；搜尋方向先往右，手勢是從右往左滑。
3. 優先選「兩把劍」普通據點；如果沒有兩把劍據點，才選「旗幟」據點。
4. 進入據點後是三個敵人畫面。
5. 優先選有「剩餘挑戰」的敵人；這等同於有 20% 額外獎勵。
6. 挑戰按鈕在上，「剩餘挑戰」說明在下；三個敵人位置固定，ROI 可以維持小範圍。
7. 如果據點內沒有剩餘挑戰，要按右上 X 回地圖，再找下一個據點。
8. 每天目標是打兩場。
9. 戰鬥通常會贏；如果失敗，先同一據點無腦再打。
10. 同一流程失敗三次後報錯，停止任務。
11. 地圖不大，往右滑一大下應該就能看完。

## Current Implementation

目前 `GuildDungeonTask` 已支援地圖/據點 probe：

```powershell
python.exe -m src.main --debug --debug-actions probe-guild-dungeon-target
```

目前行為：

1. 在目前公會副本地圖上搜尋 `sword_node_anchor.png`。
2. 找不到 sword 時 fallback 到 `flag_node_anchor.png`。
3. 找到據點後點入。
4. 在據點內找 `remaining_attempt_anchor.png`。
5. 找到剩餘挑戰後，選同欄上方的 `challenge_button.png`。
6. 若沒有剩餘挑戰，使用 `outpost_close_button.png` 或固定 X 位置關閉據點，回地圖繼續找。

已測過的 probe 範例：

```text
guild dungeon target selected: node=sword node_confidence=0.981 challenge_confidence=1.000
```

## Run-All

`config/run_all_tasks.jsonc` 已啟用 `guild_dungeon`。目前會完成兩場、等待戰鬥結果、按繼續，並在流程失敗時最多重試三次，最後安全返回每日任務。

公會副本的戰鬥準備畫面暫時共用 `assets/tasks/endless_trial/battle_ready_anchor.png`；缺少時會在執行前回報 `needs_assets`。
