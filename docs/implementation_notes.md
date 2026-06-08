# Implementation Notes

> Last updated: 2026-06-06

This file records concrete findings from live ADB tests. The higher-level project direction remains in `docs/project_analysis.v1.md`.

Open requirement questions should be appended to `docs/requirements_QA.md`.

## Environment

- Current working ADB serial is `emulator-5554`.
- `127.0.0.1:5555` is not required. If it becomes available later, use `--serial 127.0.0.1:5555` or `VL_ADB_SERIAL`.
- BlueStacks screenshot size is confirmed as `960x540`.
- Density is confirmed as `240`.
- Project-local runtime is `.venv-codex/`; the older `.venv/` points to a missing Python and should not be used.
- `.venv-codex/` has `opencv-python`, `numpy`, `easyocr`, and `torch` installed.

Useful checks:

```powershell
.\.venv-codex\Scripts\python.exe -m src.main check-device
.\.venv-codex\Scripts\python.exe -m src.main detect-scene
```

## Navigation Findings

- Top-right `任務` can be clicked from main-like screens to enter daily tasks.
- `go-daily` is based on that top-right `任務` entry and works with current `emulator-5554`.
- On 2026-06-05 after game restart, the known main screen was not detected and old `daily_tasks_entry.png` matched the top-right `任務` entry at only `0.5235`. User marked the correct icon in `captures/issue_go_daily_main_anchor_miss.png`; `daily_tasks_entry_alt.png` was cropped from the unmarked `captures/after_game_restart_waiting.png` and matched that screen at `1.0000`.
- `Navigator` now matches all `assets/shared/daily_tasks_entry*.png` templates inside a top-right ROI `(840, 0, 120, 120)` instead of relying on a single full-screen template.
- Live `go-daily` retest after adding the alt template succeeded and reached Daily Tasks. Screenshot: `captures/after_go_daily_alt_template.png`.
- Daily task list must be treated as scrollable and order-unstable.
- Finder now scrolls to the top first, then scans downward.
- Scroll gestures should stay in the list text area around `x=360`, avoiding right-side buttons and the bottom floating `一鍵領取` button.
- The right-side `前往` search ROI should stay in the right side of the same row, not the whole row.
- The same-row `前往` ROI was widened to the right-side area centered around the label row. The earlier narrow ROI caused false negatives for ready rows.
- Daily-task scrolling now compares screenshots/fingerprints after swipes so it can stop at top/bottom boundaries instead of blindly swiping.
- If a task row is too close to the bottom edge, the visible `前往` button may only partially match, e.g. Arena bottom-row live screenshot matched at only `0.6744`. Finder now treats bottom-edge rows as not safely classifiable instead of `done_or_claimable`.
- `probe-current-task <task>` only inspects the current Daily Tasks screen. `run-current-task <task>` does not reset the list to the top, but it may use the shared small fixed nudge when a target row is near the viewport edge. Use them after the user manually positions a target row on screen.
- Shared task-opening rule: `run-task` now inspects the current Daily Tasks screen first. If the target row is already ready, it taps that same-row `前往` without resetting or scrolling. Only when the current screen misses does it use the common reset-to-top and scan-down finder.
- Shared edge-row rule: bottom-edge rows are handled inside `DailyTaskFinder` for every task. If the same-row `前往` button is fully detected, the row is runnable even near the bottom edge. If the label is near the edge but `前往` is not safely detected, `run-current-task` can use a small fixed nudge/swipe and re-recognize instead of stopping immediately.
- Shared task-continuation rule: every task should support the same high-level model. `run-task <task>` first checks whether the current screen already belongs to the target task scene; if yes, it continues from that scene. If not, it enters through Daily Tasks. Use `run-current-scene-task <task>` during debug when the user has already positioned the game inside a task feature screen/dialog.
- Current-scene detection is task-specific and conservative. It uses explicit anchors such as Time Travel title, Midas title/reward, Guild Wish title, Advanced Contract OCR/template, Arena main/opponent-list anchors, or Secret Realm Lost Forest tabs. If a task lacks reliable anchors/assets, the route must stop instead of guessing.
- After `probe-task` finds a ready row, the next command should preserve that context; avoid re-scrolling away from a visible ready row. If in doubt, use `run-current-task`.
- During debug/live searching, every swipe should be reviewable via before/after screenshots. Use `--debug-actions` whenever testing task discovery or execution.
- For a future Daily Tasks OCR fallback, use full canonical task names stored in `TaskSpec.daily_text`, e.g. `成功通關2次公會副本挑戰`, instead of short task names like `公會副本`. OCR should only help find/classify a row; the actual tap still needs a verified same-row `前往`.

Important safety rule:

- Do not use Android Back as a generic recovery action from unknown screens.
- Some screens can show `你確定要退出遊戲嗎？` if the wrong back action is used.
- Route-specific return logic is required before enabling `run-all`.
- Golden rule for uncertainty or live/development problems: stop, take a screenshot, ask the user, open the screenshot in Paint, and wait.
- Normal automation should run as action -> screenshot -> recognition -> next action. Coordinates are reference points to compare expected ranges/ROIs; screenshot recognition decides whether to continue.
- Prefer correctness over speed. Longer waits between live actions are acceptable when they make recognition safer.
- On 2026-06-05, `adb shell input keyevent 0` took about 9.26 seconds and a summon-page tap exceeded the older 15-second timeout. `ADB_INPUT_TIMEOUT_SECONDS` is therefore longer than normal shell timeouts.
- Page/state recognition can use OCR as a fallback when template anchors are not enough. For stylized Chinese UI text, use fixed ROIs and fuzzy keyword checks because exact OCR text is unreliable.
- Reward overlays with `獲得道具` use the shared `BaseTask.dismiss_reward_overlay_by_blank_taps()` flow: tap a blank/outside area, then verify the expected underlying task screen. This is shared task behavior, not per-route special handling.
- During debug-stage live runs, enable persisted screenshots with `--debug-actions` or `VL_DEBUG_ACTIONS=1`. The controller saves every recognition screenshot plus before/after screenshots for every `tap`, `swipe`, and `keyevent` under a per-run subdirectory in `captures/action_debug/`.
- For swipes, constrain the unused axis when possible: vertical scrolling should lock x, and horizontal scrolling should lock y.

## Template Findings

- `manual_screenshots/` is the user-provided source of truth.
- `tools/build_initial_assets.py` generates the first batch of formal templates into `assets/`.
- Initial shared templates:
  - `assets/shared/daily_tasks_title.png`
  - `assets/shared/go_button.png`
  - `assets/shared/main_lobby_anchor.png`
  - `assets/shared/daily_tasks_entry.png`
  - `assets/shared/daily_tasks_entry_alt.png`
  - `assets/shared/back_button.png`
- Initial task label templates exist for all 10 task keys under `assets/tasks/<task_key>/task_label.png`.

Text template matching:

- Short Chinese labels with dark background were too easy to mis-match.
- Task labels are now cropped as alpha-masked text templates.
- For alpha templates, `TM_CCOEFF_NORMED` is safer than `TM_CCORR_NORMED`.
- Finder restricts task-label matching to the daily-task list area to avoid matching top-bar resource text.

## Probe Snapshot

Snapshot from live probing on 2026-06-04. This is daily-state dependent, not a permanent rule.

- `ready`: `bounty`, `guild_dungeon`, `secret_realm`, `summon`
- `done_or_claimable`: `arena`, `campaign`, `endless_trial`, `guild_wish`, `midas`, `time_travel`

Meaning:

- `ready`: task label found and same-row `前往` found.
- `done_or_claimable`: task label found but same-row `前往` not found.
- `not_found`: label not found after scanning the daily-task list.

## Summon Findings

- Summon policy: free summon only. Do not tap ticket or gem summon buttons.
- `assets/tasks/summon/advanced_contract_label.png`, `free_summon_button.png`, `confirm_button.png`, and `leave_button.png` were generated from manual screenshots.
- A live `run-task summon` consumed only the free summon. It did not tap tickets or gems.
- After free summon, reward overlays can appear and may need dismissal.
- User confirmed: the top-left in-game arrow is previous-page navigation and has no confirmation dialog.
- Summon is now implemented as route-specific logic:
  1. Confirm advanced-contract page.
  2. Tap only free summon.
  3. Tap only the blue result confirm button.
  4. Tap the Summon top-left in-game arrow.
  5. Confirm Daily Tasks or navigate there from a main-like screen.

Do not re-enable generic unknown-screen Back for this.

- Live test on 2026-06-05 completed the free summon and returned to Daily Tasks.
- During the live test, the first `confirm_button.png` crop failed to match the real result screen. It was recropped to the interior of the blue `確定` button and matched the live screenshot at `(615, 460)` with confidence `1.000`.
- After tapping result `確定`, Summon showed a second `獲得道具` overlay. The route now dismisses post-confirm overlays by tapping blank area up to two times, then requires the summon page to be visible.
- After the live test, `probe-task summon` returned `done_or_claimable`.
- Retest on 2026-06-05 showed the page was actually loading into Advanced Contract, but the old 8-second page wait could fail on a black/loading screen. Summon page wait is longer now.
- Local Chinese EasyOCR model exists at `C:\Users\USER\.EasyOCR\model\chinese.pth`. On the live Summon label ROI, EasyOCR read `高級契約` as `高紐契約`, so Summon uses OCR only as fuzzy page fallback after template matching.
- Later retest on 2026-06-05 reached the Summon background after tapping Daily Tasks `前往`, but the full UI never appeared within the longer wait. User confirmed the game had frozen/crashed. Screenshot: `captures/issue_summon_retest_after_ocr_fallback_failed.png`. This should be handled as an app freeze/retry-later condition, not as a page-recognition failure.
- During another Summon retest, user noted the free button/logo flickers. The live free-button matches were `0.8728`, `0.8787`, `0.8976`, and `0.9996` depending on animation frame. The route now uses `FREE_BUTTON_THRESHOLD = 0.80` inside the fixed left free-button ROI.
- Retest from the already-open Advanced Contract page after relaxing the threshold completed successfully: free summon was used, result confirmation handled, and the route returned to Daily Tasks. Screenshot: `captures/after_summon_threshold_relax_retest.png`.
- Later live run on 2026-06-06 completed the free summon, but return-to-Daily failed. Debug screenshots showed the left arrow was tapped while a post-confirm `獲得道具` overlay was still visible, so that tap cleared the overlay instead of leaving the Summon page. Screenshot: `captures/issue_summon_return_failed_20260606.png`.
- Summon now always sends a blank tap during post-confirm reward handling before verifying the page, and return-to-Daily can tap the in-game left arrow up to two times if the first tap only clears an overlay. Offline tests after this fix passed 40 tests. Live retest of this exact fixed return path is pending for the next available free summon.

## Secret Realm Findings

- User confirmed the safe policy: buy Lost Forest attempts first, then tap `掃蕩全部`.
- If purchase count, price, remaining purchase state, or realm selection is not clearly expected, stop instead of guessing.
- Secret Realm now has dedicated templates:
  - `lost_forest_tab.png`
  - `lost_forest_selected_tab.png`
  - `realm_attempt_entry_plus_button.png`
  - `purchase_dialog_title.png`
  - `daily_purchase_count_5_5.png`
  - `purchase_quantity_plus_button.png`
  - `purchase_quantity_two.png`
  - `purchase_confirm_button.png`
  - `sweep_all_button.png`
  - `secret_realm_back_button.png`
- The shared `assets/shared/back_button.png` did not match the live Secret Realm back arrow. A task-specific Secret Realm back template was added and matched the live screen at `(25, 20)` with confidence `0.999`.
- `Navigator.return_to_daily_tasks_from_known_route()` now accepts an optional task-specific `back_asset`.
- Live return test on 2026-06-05: started from Secret Realm screen, returned safely to Daily Tasks using the Secret Realm back template.
- Live probe after return on 2026-06-05: `probe-task secret_realm` returned `done_or_claimable`, so no purchase/sweep was executed.
- Full live test on 2026-06-05 completed: opened Secret Realm from Daily Tasks, selected/confirmed Lost Forest purchase flow, tapped `掃蕩全部`, returned to Daily Tasks, and `probe-task secret_realm` returned `done_or_claimable`.
- Retest on 2026-06-05 completed again from Daily Tasks: bought Lost Forest twice, tapped `掃蕩全部`, and returned to Daily Tasks. Screenshot: `captures/after_secret_realm_retest.png`.
- Live round on 2026-06-06 completed again and returned to Daily Tasks. Screenshot: `captures/after_secret_realm_20260606.png`.

## Time Travel Findings

- User confirmed the safe policy: tap `免費`, close reward overlay, then keep tapping every tier that still costs `50` gems. Stop before `100` gems or any unknown/non-50 price, close the dialog, and return to Daily Tasks.
- Do not tap the `100` gem tier.
- Time Travel is a modal dialog over the previous screen, not a full feature page.
- Dedicated templates now exist under `assets/tasks/time_travel/`:
  - `time_travel_title.png`
  - `free_button.png`
  - `gem_50_button.png`
  - `gem_100_button.png`
  - `cancel_button.png`
  - `reward_title.png`
- Offline template audit showed `50` and `100` gem buttons are visually similar. The route therefore reads the paid-tier cost with EasyOCR over a fixed cost ROI, with high-confidence template matching as fallback.
- Time Travel now detects dialog presence and paid-tier price from the same screenshot to avoid reading a stale/changed screen. If the dialog is gone after at least one 50-gem tap, the loop treats that as a finished state.
- Live test on 2026-06-05 reached the Time Travel dialog from Daily Tasks. The route completed the free action and dismissed the first reward overlay.
- The old `gem_50_button.png` crop failed on the live 360-minute reward version. Screenshot: `captures/time_travel_50_missing.png`; it was opened in Paint for user marking.
- `gem_50_button.png` was recropped to the `50` price text. Offline match against `captures/time_travel_50_missing.png` reached confidence `1.000` around `(753, 420)`.
- Retest on 2026-06-05 only tapped one 50-gem tier, then the user noticed a second 50-gem tier remained. Debug screenshots show the next Time Travel dialog still displayed cost `50` at `captures/action_debug/20260605_215250_1188/000022_20260605_215318_screen.png`; do not treat that run as a complete Time Travel validation.
- Offline fix after that retest passed 27 tests. The updated all-50 loop still needs live retesting when the user is ready.
- Time Travel now has a current-scene state machine. If the current dialog already shows a 50-gem tier, it skips free-button lookup and continues tapping all 50-gem tiers until 100/unknown cost. If the free button is visible, it taps free first, dismisses the reward overlay, then continues the same 50-gem loop.
- Offline tests after current-scene support passed 32 tests.
- Live retest on 2026-06-06 completed from Daily Tasks and returned to Daily Tasks. It tapped free and `2x 50-gem`, confirming the previous missing-second-50 bug is fixed. Screenshot: `captures/after_time_travel_20260606.png`.

## Midas Findings

- User confirmed Midas can use all remaining attempts in the allowed `免費`, `20` gem, and `50` gem tiers.
- Q010 in `docs/requirements_QA.md` is answered: exhaust all remaining allowed attempts until those buttons are gray/not active.
- Current implementation repeatedly taps the first active allowed button from left to right, with a hard tap limit to avoid loops.
- Midas is a modal dialog over the previous screen. Closing the top-right X should reveal Daily Tasks when opened from Daily Tasks.
- Current `manual_screenshots/點金手/002_點金手.png` only shows a partially used state where free/20 are already gray and 50 is still active.
- Active Midas button templates were therefore generated from legacy live captures under `legacy/20260604_pre_rewrite/experiments/midas_route/debug/`.
- Dedicated templates now exist under `assets/tasks/midas/`:
  - `midas_title.png`
  - `free_button.png`
  - `gem_20_button.png`
  - `gem_50_button.png`
  - `midas_close_button.png`
  - `reward_title.png`
- Offline template audit showed disabled free still matches the active free template at about `0.794`; active buttons match at `1.000`. Midas uses an active-button threshold of `0.92`.
- Reward overlay must be handled before checking buttons because dimmed active 20/50 buttons can still match behind the overlay.
- Live test on 2026-06-05 completed from Daily Tasks and returned to Daily Tasks.
- Live tap sequence was: `free`, `20-gem`, `20-gem`, `20-gem`, `50-gem`, `50-gem`, `50-gem`.
- Post-run screenshot: `captures/after_midas_live_test.png`.
- Post-run `probe-task midas` returned `done_or_claimable`.
- Retest on 2026-06-05: `probe-task midas` returned `done_or_claimable`, so the route was not executed.
- Current-scene live test on 2026-06-06 started from an already-open Midas dialog and returned to Daily Tasks. Tap sequence was: `free`, `20-gem`, `20-gem`, `20-gem`, `50-gem`, `50-gem`, `50-gem`, `50-gem`. Screenshot: `captures/after_midas_current_scene_20260606.png`.

## Arena Findings

- User confirmed in Q011: ignore the Daily Tasks count of 2; Arena should keep fighting until accumulated opponents reach at least 8. Exceeding 8 is acceptable.
- Arena policy remains: cancel/avoid opponents above `7000k`.
- The legacy `arena_route` flow is the correct starting point: open `多人挑戰`, OCR 8 opponent power values, uncheck over-7000k checked opponents, then start the challenge.
- The legacy unsafe unknown-screen fallback is not allowed in the new route. Do not tap top-left Back just because a screen is unknown.
- New formal Arena templates:
  - `arena_main_anchor.png`
  - `opponent_list_anchor.png`
  - `multi_challenge_button.png`
  - `challenge_button.png`
  - `continue_button.png`
  - `arena_back_button.png`
- The hash OCR path is not safe enough for live Arena decisions. On the manual opponent-list screenshot, it misread high-power values such as `9733k` and `8127k`.
- Arena now uses EasyOCR with fixed ROIs and filters out far-right score text that EasyOCR can also detect.
- Offline real EasyOCR audit on `manual_screenshots/競技場/003_選擇對手.png` detected the high-power opponents `9733k`, `8127k`, and `7531k` correctly.
- Safety stops: missing/low-confidence OCR, uncertain checkbox state, no checked safe opponents after filtering, failed verification after unchecking an over-7000k opponent, missing continue button, or failure to return to Daily Tasks.
- Arena OCR confidence policy: normal minimum confidence is `0.70`. Values `<=1000k` are accepted at confidence `>=0.60` after live EasyOCR read a user-confirmed `252k` at confidence `0.6005`. Values `>7000k` are also accepted at confidence `>=0.60` for conservative unchecking. Low-confidence mid/safe values still stop.
- Live test on 2026-06-05:
  - Initial `probe-task arena` failed because auto-scanning moved the list and the row was not visible; user repositioned the list.
  - `probe-current-task arena` found the visible row at `label_center=(330, 349)`, `go_center=(840, 358)`.
  - `run-current-task arena` completed successfully: `Arena fights: 9 across 2 round(s)`.
  - Post-run scene detection was `daily_tasks`; post-run screenshot is `captures/after_arena_live_test.png`.
- Retest on 2026-06-05 completed from Daily Tasks: `Arena fights: 11 across 3 round(s)`, then returned to Daily Tasks. Screenshot: `captures/after_arena_retest.png`.
- Live test on 2026-06-06 stopped on the opponent list before fighting because row 3 / col 1 read `252k` at confidence `0.601`. Screenshot: `captures/issue_arena_ocr_uncertain_20260606.png`; user confirmed `252k` was correct. Offline fix passed 38 tests; live continuation is pending.
- Live continuation on 2026-06-06 after the low-power OCR exception completed successfully: `Arena fights: 8 across 2 round(s)`, then returned to Daily Tasks. Screenshot: `captures/after_arena_continue_20260606.png`.
- A later 2026-06-06 live run stopped on row 3 / col 2 reading `8130k` at confidence `0.634`; user confirmed visible over-7000k opponents to remove were `8092k`, `10275k`, and `8130k`. The OCR policy now accepts over-7000k values at confidence `>=0.60` for unchecking.
- Live continuation on 2026-06-06 after that high-power OCR policy update completed successfully: `Arena fights: 9 across 2 round(s)`, then returned to Daily Tasks. Screenshot: `captures/after_arena_8130_fix_20260606.png`.

## Guild Wish Findings

- User confirmed in `docs/project_analysis.v1.md`: Guild Wish should only tap the free wish and must not tap 100/200 gem wishes.
- The legacy `guild_wish_route` flow was simple: open Guild Wish, tap free, then close the dialog with the top-right X.
- New formal Guild Wish templates:
  - `guild_wish_title.png`
  - `ordinary_wish_label.png`
  - `free_wish_button.png`
  - `close_button.png`
- The new route is conservative:
  1. Requires the Guild Wish dialog title.
  2. Requires the left `普通祈願` card.
  3. Taps only the left free button ROI.
  4. Requires the dialog is still visible, then closes with X.
- If a reward overlay or unexpected UI hides the dialog/close button after free wish, stop instead of guessing.
- Offline template tests passed against `manual_screenshots/公會祈願/002_公會祈願.png`.
- Live test on 2026-06-06 stopped after the free wish because an `獲得道具` overlay hid the dialog enough that the route could not find the title. Screenshot: `captures/issue_guild_wish_after_free_20260606.png`.
- User clarified the correct flow: tap blank area to close `獲得道具`, then tap the top-right X on the Guild Wish dialog.
- Guild Wish now uses the shared blank-tap reward helper after the free wish and supports current-scene continuation from the reward-overlay state. Offline tests after the fix passed 36 tests; live continuation/retest is pending.
- Live continuation on 2026-06-06 from the Guild Wish reward overlay completed successfully and returned to Daily Tasks. Screenshot: `captures/after_guild_wish_continue_20260606.png`.

## 2026-06-06 Live Round Summary

- Skipped Midas because the user had already tested it.
- Secret Realm completed and returned to Daily Tasks.
- Guild Wish initially stopped correctly on the reward overlay; after adding the shared reward blank-tap helper, continuation completed and returned to Daily Tasks.
- Arena initially stopped correctly on low-confidence OCR for confirmed `252k`; after adding the narrow low-power exception, continuation completed and returned to Daily Tasks.
- Summon completed and returned to Daily Tasks. Screenshot: `captures/after_summon_20260606.png`.
- Time Travel completed and returned to Daily Tasks; it used free plus `2x 50-gem`.
- Later same-day live round: Secret Realm and Guild Wish completed. Arena needed the over-7000k low-confidence OCR policy update, then completed. Summon completed the free action but exposed the post-confirm overlay return bug, which was fixed offline and awaits next free-summon live retest. Time Travel was already done and skipped as `done_or_claimable`.

## Current Next Step

Before running `run-all`, implement and verify safe return-to-daily behavior for each route. Secret Realm, Summon, Midas, and Arena have live-tested closed loops. Time Travel has been updated to loop all 50-gem tiers and needs retesting. Guild Wish has offline coverage and needs live testing.
