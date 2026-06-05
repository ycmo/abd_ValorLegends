# Codex Notes

> Last updated: 2026-06-05
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
.\.venv-codex\Scripts\python.exe -m compileall src tests tools
.\.venv-codex\Scripts\python.exe -m unittest discover -s tests
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

## Current Known Good

- `go-daily` works by clicking top-right `任務` from main-like screens.
- Daily task scanning now resets to top and scans down.
- Scroll gestures use x=360 to avoid right-side buttons and the bottom `一鍵領取` overlay.
- `probe-task` was tested across all 10 task keys and produced plausible states.
- `run-task summon` live-tested one free summon, dismissed the second reward overlay, and returned to Daily Tasks.
- `run-task secret_realm` live-tested Lost Forest purchase/sweep flow and returned to Daily Tasks.
- `run-task midas` live-tested all allowed free/20/50 gem attempts and returned to Daily Tasks.
- `run-current-task arena` live-tested Arena from a visible Daily Tasks row and returned to Daily Tasks.

## Current Safety Rules

- Golden rule: if there is any uncertainty, ask. During development or live execution, when a problem or uncertain screen appears, stop, take a screenshot, ask the user, open the screenshot in Paint, and wait for the user before continuing.
- If Codex appends a new QA question, stop the current implementation path and explicitly tell the user there is a question waiting in `docs/requirements_QA.md`.
- After every live action, take/inspect a screenshot or otherwise verify the resulting scene before continuing.
- Daily Tasks scrolling must detect list boundaries and avoid repeated blind swipes when already at the top or bottom.
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
- `probe-current-task <task>` and `run-current-task <task>` operate only on the current Daily Tasks screen without scroll-to-top. Use them when the user manually positions a row.

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

## Time Travel Notes

- Policy: tap `免費`, dismiss reward overlay, tap `50` gems, dismiss reward overlay, tap `取消` to close the dialog, then return to Daily Tasks.
- Implemented as a custom conservative flow in `src/tasks/time_travel.py`, not a generic asset sequence.
- Required templates are generated by `tools/build_initial_assets.py` under `assets/tasks/time_travel/`.
- Time Travel is a modal dialog. Closing `取消` should reveal Daily Tasks when opened from Daily Tasks, or a main-like screen when opened from the lobby.
- `50` and `100` gem button templates are visually similar, so gem-cost matching uses a high threshold and checks for the `100` gem tier before tapping `50`.
- Unit tests in `tests/test_time_travel.py` verify that the route stops before the `100` gem tier.
- Live test on 2026-06-05 found the old `gem_50_button.png` crop did not match the current 360-minute reward version. Screenshot: `captures/time_travel_50_missing.png`; it was opened in Paint for user marking.
- `gem_50_button.png` was recropped to the `50` price text and matched `captures/time_travel_50_missing.png` at confidence `1.000` around `(753, 420)`.
- Current paused state: the 50-gem button was manually tapped, a reward overlay appeared, a blank-area tap was sent, and `captures/time_travel_after_blank.png` exists but was not inspected before the user stopped the flow. Do not claim Time Travel is completed; next live step must start by inspecting the current screen/screenshot.

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

## Arena Notes

- Policy: cancel/avoid opponents above `7000k`, then fight until the accumulated opponent count reaches at least 8. Q011 answered that exceeding 8 is acceptable.
- Implemented as a custom conservative flow in `src/tasks/arena.py`, not a generic asset sequence.
- Required templates are generated by `tools/build_initial_assets.py` under `assets/tasks/arena/`.
- The old hash OCR is not safe enough for live Arena decisions. On `manual_screenshots/競技場/003_選擇對手.png`, it misread `9733k` and `8127k`.
- Arena now uses the old EasyOCR ROI approach with additional filtering of score text on the far right of each ROI.
- If any opponent power OCR is missing or below confidence `0.70`, stop before selecting opponents.
- If a checkbox state is between the checked/unchecked green-ratio thresholds, stop before tapping.
- After tapping an over-7000k checked opponent, Arena takes a fresh screenshot and verifies that checkbox is now unchecked before continuing.
- No unknown-screen fallback tap is allowed; the old route's "tap top-left on unknown" behavior must not return.
- Offline tests on 2026-06-05 passed against manual screenshots and fake OCR; real EasyOCR audit correctly detected `9733k`, `8127k`, and `7531k` as over-7000k on the manual opponent-list screenshot.
- Live test on 2026-06-05 used `run-current-task arena` from a currently visible Daily Tasks row. It completed successfully, fought 9 opponents across 2 rounds, and returned to Daily Tasks.
- Post-run screenshot: `captures/after_arena_live_test.png`. Post-run scene detection was `daily_tasks`.

## Next Work

1. Resume Time Travel from a fresh screenshot/current-screen check; verify it closes back to Daily Tasks after the 50-gem reward.
2. Continue route-specific safe return-to-daily work before enabling `run-all`.
3. Keep appending unclear requirements to `docs/requirements_QA.md`; stop and notify the user when adding a new QA question.
