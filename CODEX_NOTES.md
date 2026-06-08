# Codex Notes

> Last updated: 2026-06-07
> Purpose: fast handoff notes for Codex. Keep this short, factual, and implementation-focused.

## Read First

1. `docs/project_analysis.v1.md` is the authoritative product/architecture direction.
2. `docs/implementation_notes.md` records live ADB findings.
3. `docs/requirements_QA.md` is user-maintained QA. Append open questions there, do not bury them in chat.
4. `manual_screenshots/` is the user-provided source of truth. Do not overwrite it.

## Current Workspace Shape

- Main project path: `E:\antigravity\adb_vl`.
- Old code/assets/tools were archived under `legacy/20260604_pre_rewrite/`.
- `legacy/` is ignored by git.
- New mainline lives under `src/`.
- Ads work belongs under `ads/`; do not mix ad-watching implementation into daily-task routes.
- User plans to create `ads2/` later for a cleaner ad-blocking/ad-closing rewrite. Current `ads/` is usable but layered; do not expand it into a larger refactor unless explicitly asked.
- `call_of_the_gale/` is the independent AGY/Codex workspace for `王國冒險 -> 疾風的呼喚`; do not mix it into daily-task routes until the mini-game flow is understood and approved.
- `magic_shop/` is the independent AGY workspace for `魔法商店`; AGY may read/import shared `src/` tools but must not modify files outside `magic_shop/` until integration is explicitly approved.

## Runtime

- Use `.venv-codex\Scripts\python.exe` for this project.
- The old `.venv/` points to a missing Python and should not be used.
- Current valid ADB serial: `emulator-5554`.
- `src.config.DEFAULT_SERIAL` uses `VL_ADB_SERIAL` or defaults to `emulator-5554`.
- Confirmed screenshot size: `960x540`.
- Confirmed density: `240`.

Common commands:

```powershell
.\.venv-codex\Scripts\python.exe -m src.main check-device
.\.venv-codex\Scripts\python.exe -m src.main detect-scene
.\.venv-codex\Scripts\python.exe -m src.main go-daily
.\.venv-codex\Scripts\python.exe -m src.main probe-task summon
.\.venv-codex\Scripts\python.exe -m src.main --debug-actions run-current-task guild_wish
.\.venv-codex\Scripts\python.exe -m src.main --debug-actions run-current-scene-task time_travel
.\.venv-codex\Scripts\python.exe -m src.main --debug-actions run-tested-daily
.\.venv-codex\Scripts\python.exe -m compileall src tests tools
.\.venv-codex\Scripts\python.exe -m unittest discover -s tests
.\.venv-codex\Scripts\python.exe -m src.manual_screenshots --task 魔法商店 --index 1 --scene 要購買
```

## Architecture

- `src/adb_controller.py`: ADB connect, screenshot, tap/swipe/back.
- `src/vision_matcher.py`: template matching with ROI and alpha-mask support.
- `src/scene_detector.py`: scene anchors.
- `src/daily_task_finder.py`: daily-task row scan and same-row `前往` detection.
- `src/navigator.py`: navigation into Daily Tasks.
- `src/task_runner.py`: task base classes and action steps.
- `src/tasks/`: per-task implementations.
- `tools/build_initial_assets.py`: deterministic crops from `manual_screenshots/` into `assets/`.
- `src/manual_screenshots.py`: captures manual reference screenshots into `manual_screenshots/<task>/`. It opens the saved image in Paint by default; use `--no-open-paint` only for batch/noninteractive capture.
- All tasks should support the same high-level execution model: if already in the target task feature screen/dialog, continue from that scene; otherwise enter from Daily Tasks. Task-specific `task_scene_anchors` or `is_task_scene()` decide whether a current screen belongs to that task.
- `run-task <task>` now checks the current task scene before opening Daily Tasks. `run-current-scene-task <task>` is the explicit debug/test command for continuing only from the current task scene.
- `run-tested-daily` runs only the live-tested closed-loop daily tasks in `TESTED_DAILY_TASK_ORDER`: Secret Realm, Guild Wish, Arena, Summon, Time Travel, and Midas. It stops on the first `failed` or `needs_assets` result. Do not use `run-all` for routine live testing yet.
- If a task lacks reliable scene anchors/assets, the current-scene path must stop with `needs_assets` or `failed`; do not guess from unknown screens.

## Current Known Good

- `go-daily` works by clicking top-right `任務` from main-like screens.
- Main-screen `任務` entry has at least two appearances. `Navigator` matches `assets/shared/daily_tasks_entry*.png` in the top-right ROI; `daily_tasks_entry_alt.png` was cropped from `captures/after_game_restart_waiting.png` after the old template missed the restarted main screen.
- `go-daily` live retested successfully after adding `daily_tasks_entry_alt.png`; screenshot after return: `captures/after_go_daily_alt_template.png`.
- Daily task scanning now resets to top and scans down.
- Scroll gestures use x=360 to avoid right-side buttons and the bottom `一鍵領取` overlay.
- `probe-task` was tested across all 10 task keys and produced plausible states.
- `run-task summon` live-tested one free summon, dismissed the second reward overlay, and returned to Daily Tasks.
- `run-task secret_realm` live-tested Lost Forest purchase/sweep flow and returned to Daily Tasks.
- `run-task midas` live-tested all allowed free/20/50 gem attempts and returned to Daily Tasks.
- `run-current-task arena` live-tested Arena from a visible Daily Tasks row and returned to Daily Tasks.
- 2026-06-06 live round completed existing closed-loop tasks except Midas, which the user had already tested: Secret Realm, Guild Wish, Arena, Summon, and Time Travel all returned to Daily Tasks.

## Current Safety Rules

- Golden rule: if there is any uncertainty, ask. During development or live execution, when a problem or uncertain screen appears, stop, take a screenshot, ask the user, open the screenshot in Paint, and wait for the user before continuing.
- Normal UI loop is action -> screenshot -> recognition -> next action. Coordinates are reference points for comparing ranges/ROIs, not the only source of truth.
- Prefer correctness over speed. It is acceptable for live automation to wait longer between actions if that makes screenshot recognition safer.
- ADB `input` commands can be slow on the current emulator. `ADB_INPUT_TIMEOUT_SECONDS` is intentionally longer than generic shell commands.
- Page/state recognition may combine template anchors with OCR fallback. Use fixed ROIs and fuzzy keyword checks for stylized Chinese text; do not require exact OCR strings.
- Reward overlays with `獲得道具` should use the shared `BaseTask.dismiss_reward_overlay_by_blank_taps()` flow: tap a blank/outside area, then re-check the expected underlying task screen. Do not hand-roll per-task reward dismissal unless a specific overlay needs a different button.
- Daily-task opening must use one shared search flow for every task: ensure Daily Tasks -> inspect current screen -> if ready, tap same-row `前往` -> only if current screen misses, reset/scan with `DailyTaskFinder`. Do not probe a ready row and then run a command that blindly re-scrolls away from it.
- Daily-task row edge handling is shared in `DailyTaskFinder`. A bottom-edge row is still runnable if the same-row `前往` button is fully detected; if the label is near the edge but the button is not safely detected, use the common fixed nudge/swipe search before classifying or giving up.
- Task execution must also use one shared scene-continuation rule for every task: first inspect whether the current screen is already the target task scene; if yes, continue from that state, and only use Daily Tasks entry/opening when not already in-task.
- If Daily Tasks OCR fallback is added, compare against `TaskSpec.daily_text` full task names such as `成功通關2次公會副本挑戰`, not short display names. Use fuzzy matching and core keywords, and still tap only a verified same-row `前往`.
- Debug-stage rule: keep the normal action/screenshot/recognition loop, but persist screenshots so the path can be reviewed later. Use `--debug-actions` or `VL_DEBUG_ACTIONS=1`; recognition screenshots and before/after input screenshots are saved under `captures/action_debug/`.
- If Codex appends a new QA question, stop the current implementation path and explicitly tell the user there is a question waiting in `docs/requirements_QA.md`.
- After every live action, take/inspect a screenshot or otherwise verify the resulting scene before continuing.
- For swipes, constrain the unused axis when possible: vertical scrolling should lock x, and horizontal scrolling should lock y.
- Daily Tasks scrolling must detect list boundaries and avoid repeated blind swipes when already at the top or bottom.
- Every live/debug swipe must have before/after screenshots available for review. Use `--debug-actions` for any live task search or run.
- Normal task discovery may still scroll the Daily Tasks list automatically. If a problem occurs and the user manually repositions the list, first inspect/understand the current screen before deciding whether to use current-screen commands or resume automatic search.
- Do not use Android Back as a generic unknown-screen recovery action.
- Some screens can trigger `你確定要退出遊戲嗎？` if back is used incorrectly.
- Each route needs explicit safe return-to-daily logic before enabling `run-all`.
- For task rows, label found but same-row `前往` missing means `done_or_claimable`; skip for now.
- First version does not auto-click Daily Tasks rewards/`領取`.

## Template Notes

- Formal templates live under `assets/shared/` and `assets/tasks/<task_key>/`.
- Rebuild initial templates with:

```powershell
.\.venv-codex\Scripts\python.exe tools\build_initial_assets.py
```

- Task label templates are alpha-masked text crops.
- Alpha template matching should use `TM_CCOEFF_NORMED`; `TM_CCORR_NORMED` caused false positives on short Chinese labels.
- Restrict task-label matching to the task-list content area; never search full screen for row labels.
- Same-row `前往` search uses a wider right-side ROI centered on the task label row; the earlier narrow row ROI caused false negatives for ready tasks.
- If a task label is too close to the bottom edge, finder now treats it as not safely classifiable and keeps scanning instead of misclassifying it as `done_or_claimable`.
- `probe-current-task <task>` inspects only the current Daily Tasks screen. `run-current-task <task>` does not reset to the top, but it may use the shared small fixed nudge when a target row is near the viewport edge. Use them when the user manually positions a row.

## Summon Notes

- Policy: free summon only.
- Implemented as a custom conservative flow in `src/tasks/summon.py`, not a generic asset sequence.
- Existing templates:
  - `assets/tasks/summon/advanced_contract_label.png`
  - `assets/tasks/summon/free_summon_button.png`
  - `assets/tasks/summon/confirm_button.png`
  - `assets/tasks/summon/leave_button.png`
- User confirmed the Summon top-left in-game arrow is previous-page navigation and has no confirmation dialog.
- Current flow:
  1. Confirm advanced-contract page with `advanced_contract_label.png`.
  2. Tap only `free_summon_button.png`.
  3. Tap only blue `confirm_button.png` on the result screen.
  4. Dismiss post-confirm `獲得道具` overlay by blank-area taps, then require the summon page.
  5. Tap `leave_button.png`.
  6. If not already on Daily Tasks, use `go_to_daily_tasks`.
- Do not treat Android Back as the close action.
- Unit tests in `tests/test_summon.py` verify the explicit return helper behavior.
- Live test on 2026-06-05 completed the free summon and returned to Daily Tasks. It consumed only the free summon; no ticket/gem summon was tapped.
- `confirm_button.png` was recropped after live failure; current live match point was `(615, 460)` at confidence `1.000`.
- Summon page recognition now uses the `advanced_contract_label.png` template first, with a Chinese EasyOCR fallback over the same ROI. EasyOCR can misread `高級契約` as text like `高紐契約`, so the fallback checks fuzzy keywords (`高`, `契`, `約`) rather than exact text.
- Retest on 2026-06-05 confirmed a game freeze/crash case: after tapping Daily Tasks `前往`, the game reached the Summon background scene but never rendered the full left/right UI. Screenshot: `captures/issue_summon_retest_after_ocr_fallback_failed.png`. Treat this as app/UI freeze, not template/OCR failure.
- The Summon free button/logo can flicker. Live captures matched `free_summon_button.png` at about `0.873-0.879`, just below the old `0.88` threshold. Since `FREE_BUTTON_ROI` only covers the left free-button area and paid buttons are outside it, `FREE_BUTTON_THRESHOLD` is `0.80`.
- Retest from the already-open Advanced Contract page after relaxing `FREE_BUTTON_THRESHOLD` completed successfully and returned to Daily Tasks. Screenshot: `captures/after_summon_threshold_relax_retest.png`.
- 2026-06-06 later live run completed the free summon, but return-to-Daily failed because the post-confirm reward overlay was still present; tapping the left arrow only dismissed that overlay, leaving the script on the Summon page. Screenshot: `captures/issue_summon_return_failed_20260606.png`.
- Summon was updated so post-confirm reward handling always sends a blank tap before verifying the page, and return-to-Daily can tap the in-game left arrow up to two times if the first tap only clears an overlay. Offline tests after this fix passed 40 tests. Full live retest of the fixed Summon return is pending for the next available free summon.

## Secret Realm Notes

- Policy: buy Lost Forest first two purchases, then tap `掃蕩全部`.
- Implemented as a custom conservative flow in `src/tasks/secret_realm.py`, not a generic asset sequence.
- Required templates are generated by `tools/build_initial_assets.py` under `assets/tasks/secret_realm/`.
- Purchase dialog must show `每日購買次數 5/5`; otherwise stop/fail instead of buying.
- After tapping quantity plus once, the script requires the quantity field to show `2` before tapping `購買`.
- Shared `assets/shared/back_button.png` did not match Secret Realm live back arrow. Use `assets/tasks/secret_realm/secret_realm_back_button.png`.
- Live test on 2026-06-05 returned from Secret Realm to Daily Tasks using the task-specific back template.
- `probe-task secret_realm` then reported `done_or_claimable`, so the buy/sweep action was not executed.
- Full live test on 2026-06-05 completed Lost Forest purchase + sweep all and returned to Daily Tasks; post-run probe was `done_or_claimable`.
- Retest on 2026-06-05 completed again: bought Lost Forest twice, tapped sweep all, and returned to Daily Tasks. Screenshot: `captures/after_secret_realm_retest.png`.
- 2026-06-06 live round completed again and returned to Daily Tasks. Screenshot: `captures/after_secret_realm_20260606.png`.

## Time Travel Notes

- Policy: tap `免費`, dismiss reward overlay, then keep tapping every tier that still costs `50` gems. Stop before `100` gems or any unknown/non-50 price, tap `取消` to close the dialog, then return to Daily Tasks.
- Implemented as a custom conservative flow in `src/tasks/time_travel.py`, not a generic asset sequence.
- Required templates are generated by `tools/build_initial_assets.py` under `assets/tasks/time_travel/`.
- Time Travel is a modal dialog. Closing `取消` should reveal Daily Tasks when opened from Daily Tasks, or a main-like screen when opened from the lobby.
- `50` and `100` gem button templates are visually similar. Time Travel now reads the cost button with EasyOCR over a fixed ROI, with template matching as fallback, before tapping any paid tier.
- Time Travel cost detection must use the same screenshot for dialog presence and price reading. If the Time Travel dialog is already gone after at least one 50-gem tap, treat it as finished instead of reading price from Daily Tasks.
- Unit tests in `tests/test_time_travel.py` verify that the route taps all 50-gem tiers and stops before the 100-gem tier.
- Live test on 2026-06-05 found the old `gem_50_button.png` crop did not match the current 360-minute reward version. Screenshot: `captures/time_travel_50_missing.png`; it was opened in Paint for user marking.
- `gem_50_button.png` was recropped to the `50` price text and matched `captures/time_travel_50_missing.png` at confidence `1.000` around `(753, 420)`.
- Retest on 2026-06-05 only tapped one 50-gem tier, then the user noticed a second 50-gem tier remained. Debug screenshots show the next Time Travel dialog still displayed cost `50` at `captures/action_debug/20260605_215250_1188/000022_20260605_215318_screen.png`; do not treat that run as a complete Time Travel validation.
- Offline fix after that retest passed 27 tests, but the updated all-50 loop still needs live retesting when the user is ready.
- Time Travel now supports current-scene continuation. If the dialog is already at a 50-gem tier, `run-task time_travel` or `run-current-scene-task time_travel` continues from that tier instead of requiring the free button to be present. The state machine only taps free when the free button is visible, then taps all visible 50-gem tiers and stops before 100/unknown cost.
- Offline tests after adding current-scene continuation passed 32 tests.
- 2026-06-06 live retest completed from Daily Tasks and returned to Daily Tasks. It tapped free plus `2x 50-gem`, fixing the previous missing-second-50 issue. Screenshot: `captures/after_time_travel_20260606.png`.

## Midas Notes

- Policy: exhaust all remaining attempts in allowed tiers: `免費`, `20` gems, and `50` gems, until those buttons are no longer active.
- Q010 answered: user allows all free/20/50 Midas attempts to be used.
- Current implementation in `src/tasks/midas.py` repeatedly taps the first active allowed button from left to right, with a hard tap limit to avoid loops.
- Required templates are generated by `tools/build_initial_assets.py` under `assets/tasks/midas/`.
- Active free/20/50 templates come from legacy live captures because current manual Midas screenshots only show a partially used state.
- Use `reward_title.png` to dismiss the Midas reward overlay before checking buttons; dimmed buttons can still match under reward overlay.
- Unit tests in `tests/test_midas.py` verify the active-button tap helper does not tap missing buttons.
- Live test on 2026-06-05 completed from Daily Tasks and returned to Daily Tasks. Tap sequence was: `free`, `20-gem`, `20-gem`, `20-gem`, `50-gem`, `50-gem`, `50-gem`.
- Post-run screenshot: `captures/after_midas_live_test.png`. Post-run `probe-task midas` returned `done_or_claimable`.
- Retest on 2026-06-05: `probe-task midas` returned `done_or_claimable`, so no action was taken.
- 2026-06-06 current-scene live test started from an already-open Midas dialog and returned to Daily Tasks. Tap sequence was: `free`, `20-gem`, `20-gem`, `20-gem`, `50-gem`, `50-gem`, `50-gem`, `50-gem`. Screenshot: `captures/after_midas_current_scene_20260606.png`.

## Arena Notes

- Policy: cancel/avoid opponents above `7000k`, then fight until the accumulated opponent count reaches at least 8. Q011 answered that exceeding 8 is acceptable.
- Implemented as a custom conservative flow in `src/tasks/arena.py`, not a generic asset sequence.
- Required templates are generated by `tools/build_initial_assets.py` under `assets/tasks/arena/`.
- The old hash OCR is not safe enough for live Arena decisions. On `manual_screenshots/競技場/003_選擇對手.png`, it misread `9733k` and `8127k`.
- Arena now uses the old EasyOCR ROI approach with additional filtering of score text on the far right of each ROI.
- If any opponent power OCR is missing or below confidence `0.70`, stop before selecting opponents.
- Arena OCR confidence policy: default minimum is `0.70`. Values `<=1000k` are accepted at confidence `>=0.60` because live EasyOCR read a confirmed `252k` at `0.6005`. Values `>7000k` are also accepted at confidence `>=0.60` so they can be conservatively unchecked. Missing values and low-confidence mid/safe values still stop before selecting opponents.
- If a checkbox state is between the checked/unchecked green-ratio thresholds, stop before tapping.
- After tapping an over-7000k checked opponent, Arena takes a fresh screenshot and verifies that checkbox is now unchecked before continuing.
- No unknown-screen fallback tap is allowed; the old route's "tap top-left on unknown" behavior must not return.
- Offline tests on 2026-06-05 passed against manual screenshots and fake OCR; real EasyOCR audit correctly detected `9733k`, `8127k`, and `7531k` as over-7000k on the manual opponent-list screenshot.
- Live test on 2026-06-05 used `run-current-task arena` from a currently visible Daily Tasks row. It completed successfully, fought 9 opponents across 2 rounds, and returned to Daily Tasks.
- Post-run screenshot: `captures/after_arena_live_test.png`. Post-run scene detection was `daily_tasks`.
- Retest on 2026-06-05 completed successfully: `Arena fights: 11 across 3 round(s)`, then returned to Daily Tasks. Screenshot: `captures/after_arena_retest.png`.
- Live test on 2026-06-06 stopped safely on the opponent list because `252k` was read with confidence `0.601`, below the old `0.70` global threshold. User confirmed `252k` is correct. Offline fix added the narrow low-power exception and 38 tests passed; live continuation is pending.
- 2026-06-06 live continuation after the OCR fix completed successfully: `Arena fights: 8 across 2 round(s)` and returned to Daily Tasks. Screenshot: `captures/after_arena_continue_20260606.png`.
- Later 2026-06-06 live test stopped on confirmed high-power values including `8092k`, `10275k`, and `8130k`; `8130k` was read at confidence `0.634`. Policy was updated so over-7000k readings at confidence `>=0.60` are accepted for unchecking, while low-confidence mid/safe values still stop.
- 2026-06-06 live continuation after this high-power OCR policy change completed successfully: `Arena fights: 9 across 2 round(s)` and returned to Daily Tasks. Screenshot: `captures/after_arena_8130_fix_20260606.png`.
- 2026-06-07 Arena opponent-list uncertainty now saves the current screenshot under `captures/arena_uncertain/`, prints `saved_screenshot=<path>` to console, taps the opponent-list top-right X, then uses the Arena left back arrow to return to Daily Tasks. This is reported as `skipped` so later daily tasks can continue.

## Guild Wish Notes

- Policy: free wish only. Do not tap 100/200 gem wishes.
- Implemented as a custom conservative flow in `src/tasks/guild_wish.py`, not a generic asset sequence.
- Required templates are generated by `tools/build_initial_assets.py` under `assets/tasks/guild_wish/`.
- Current flow:
  1. Confirm the Guild Wish dialog title with `guild_wish_title.png`.
  2. Confirm the left `普通祈願` card with `ordinary_wish_label.png`.
  3. Tap only the left `free_wish_button.png` inside the free-button ROI.
  4. Require the Guild Wish dialog is still visible, then close with `close_button.png`.
- If a reward overlay hides the dialog or the close button after the free wish, the route fails/stops instead of tapping paid buttons or guessing.
- After tapping the free wish, Guild Wish uses the shared reward-overlay blank tap flow, then closes the dialog with the top-right X. If a live run stops on the reward overlay, `run-current-scene-task guild_wish` should continue by blank-tapping the overlay and then closing X.
- Offline tests on 2026-06-05 passed against the manual Guild Wish screenshot.
- Live test on 2026-06-06 exposed the missing reward-overlay dismissal after free wish. The route was updated offline and now has tests for reward-overlay continuation.
- 2026-06-06 live continuation from the reward overlay completed successfully and returned to Daily Tasks. Screenshot: `captures/after_guild_wish_continue_20260606.png`.

## Next Work

1. Live-test Guild Wish from Daily Tasks when its row is ready.
3. Keep appending unclear requirements to `docs/requirements_QA.md`; stop and notify the user when adding a new QA question.
