# Call of the Gale Notes

> Last updated: 2026-06-05
> Scope: 「王國冒險 -> 疾風的呼喚」小遊戲研究與 AGY 開發交接。

## Boundaries

- This folder is independent from daily-task automation.
- Do not add Call of the Gale logic to `src/tasks/` until the mini-game flow is understood and user-approved.
- Do not mix this work into `ads/`; AGY ad-watching work stays there.
- Shared ADB assumptions remain the same as the main project: `emulator-5554`, 960x540 screenshot, density 240.

## Golden Rule

If UI state, route, template match, OCR, or next action is uncertain:

1. Stop immediately.
2. Take a screenshot into `call_of_the_gale/runtime_captures/`.
3. Ask the user a concrete question.
4. Open the screenshot with Paint from the outer shell.
5. Wait for user feedback before continuing.

Do not repeatedly tap, swipe, or retry while uncertain.

## Initial Plan

1. Entry mapping
   - Start from a known main/kingdom screen.
   - Record the path into `王國冒險 -> 疾風的呼喚`.
   - Save each stable screen and note safe return behavior.

2. State inventory
   - List stable screens, dialogs, rewards, fail states, and loading states.
   - Identify buttons that consume resources or attempts.
   - Mark any action that must stop for user confirmation.

3. Template acquisition
   - Promote only stable templates into `assets/`.
   - Keep raw/debug screenshots in `runtime_captures/` or `debug_output/`.
   - Avoid red markup in formal template crops.

4. Prototype automation
   - Build scripts under `scripts/`.
   - Prototype must fail closed: if expected UI is missing, stop and request review.
   - No unknown-screen Android Back fallback.

5. Integration decision
   - Only after live validation, decide whether this remains standalone or becomes a mainline task/tool.

## Open Facts

- Exact Chinese UI path: `王國冒險 -> 疾風的呼喚`.
- English folder name chosen for repo stability: `call_of_the_gale`.
- Detailed rules, rewards, resources, and win/finish conditions are not documented yet.
