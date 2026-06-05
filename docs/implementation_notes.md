# Implementation Notes

> Last updated: 2026-06-05

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
- Daily task list must be treated as scrollable and order-unstable.
- Finder now scrolls to the top first, then scans downward.
- Scroll gestures should stay in the list text area around `x=360`, avoiding right-side buttons and the bottom floating `一鍵領取` button.
- The right-side `前往` search ROI should stay in the right side of the same row, not the whole row.
- The same-row `前往` ROI was widened to the right-side area centered around the label row. The earlier narrow ROI caused false negatives for ready rows.
- Daily-task scrolling now compares screenshots/fingerprints after swipes so it can stop at top/bottom boundaries instead of blindly swiping.
- If a task row is too close to the bottom edge, the visible `前往` button may only partially match, e.g. Arena bottom-row live screenshot matched at only `0.6744`. Finder now treats bottom-edge rows as not safely classifiable instead of `done_or_claimable`.
- `probe-current-task <task>` and `run-current-task <task>` do not scroll. Use them after the user manually positions a target row on screen.

Important safety rule:

- Do not use Android Back as a generic recovery action from unknown screens.
- Some screens can show `你確定要退出遊戲嗎？` if the wrong back action is used.
- Route-specific return logic is required before enabling `run-all`.
- Golden rule for uncertainty or live/development problems: stop, take a screenshot, ask the user, open the screenshot in Paint, and wait.

## Template Findings

- `manual_screenshots/` is the user-provided source of truth.
- `tools/build_initial_assets.py` generates the first batch of formal templates into `assets/`.
- Initial shared templates:
  - `assets/shared/daily_tasks_title.png`
  - `assets/shared/go_button.png`
  - `assets/shared/main_lobby_anchor.png`
  - `assets/shared/daily_tasks_entry.png`
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

## Time Travel Findings

- User confirmed the safe policy: tap `免費`, close reward overlay, tap `50` gems, close reward overlay, close the dialog, and return to Daily Tasks.
- Do not tap the `100` gem tier.
- Time Travel is a modal dialog over the previous screen, not a full feature page.
- Dedicated templates now exist under `assets/tasks/time_travel/`:
  - `time_travel_title.png`
  - `free_button.png`
  - `gem_50_button.png`
  - `gem_100_button.png`
  - `cancel_button.png`
  - `reward_title.png`
- Offline template audit showed `50` and `100` gem buttons are visually similar. The route therefore uses high-confidence matching for gem-cost buttons and checks for `gem_100_button.png` before tapping `gem_50_button.png`.
- Live test on 2026-06-05 reached the Time Travel dialog from Daily Tasks. The route completed the free action and dismissed the first reward overlay.
- The old `gem_50_button.png` crop failed on the live 360-minute reward version. Screenshot: `captures/time_travel_50_missing.png`; it was opened in Paint for user marking.
- `gem_50_button.png` was recropped to the `50` price text. Offline match against `captures/time_travel_50_missing.png` reached confidence `1.000` around `(753, 420)`.
- Current paused state: the 50-gem button was manually tapped, the reward overlay appeared, a blank-area tap was sent, and `captures/time_travel_after_blank.png` was captured but not inspected before the user stopped the flow. Do not mark Time Travel complete until a fresh/current screenshot confirms the final close/return path.

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
- Live test on 2026-06-05:
  - Initial `probe-task arena` failed because auto-scanning moved the list and the row was not visible; user repositioned the list.
  - `probe-current-task arena` found the visible row at `label_center=(330, 349)`, `go_center=(840, 358)`.
  - `run-current-task arena` completed successfully: `Arena fights: 9 across 2 round(s)`.
  - Post-run scene detection was `daily_tasks`; post-run screenshot is `captures/after_arena_live_test.png`.

## Current Next Step

Before running `run-all`, implement and verify safe return-to-daily behavior for each route. Secret Realm, Summon, Midas, and Arena have live-tested closed loops. Time Travel is paused after the 50-gem reward dismissal attempt and needs a fresh/current screenshot check before continuing.
