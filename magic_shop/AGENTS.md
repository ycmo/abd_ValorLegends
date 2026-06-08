# AGY Instructions: Magic Shop

This directory is the isolated workspace for the Valor Legends Magic Shop task.

## Hard Boundary

- You may create, edit, and delete files only under `magic_shop/`.
- Do not modify files outside `magic_shop/`, including `src/`, `assets/`, `tests/`, `docs/`, `ads/`, `ads2/`, `manual_screenshots/`, and project root files.
- You may read files outside this directory for reference.
- You may import or call shared project tools from `src/` at runtime.
- If shared code needs a change, do not patch it. Write the requested change or blocker in `magic_shop/QA.md` and stop.

## Required Runtime Rules

- Use Traditional Chinese for notes and user-facing messages.
- Follow the project golden rule: if UI behavior is uncertain or a live run hits a problem, stop, take a screenshot, ask the user, open the screenshot in Paint, and wait.
- In debug/live runs, use action -> screenshot -> recognition -> next action.
- Keep debug screenshots under `magic_shop/debug_output/` or `magic_shop/runtime_captures/`.
- Do not rely on blind coordinate-only automation. Coordinates are hints; verify with screenshots/templates/OCR.
- Prefer correctness over speed.

## Allowed Shared APIs

You may import and call these project tools without editing them:

- `src.adb_controller.DeviceController`
- `src.vision_matcher.VisionMatcher`, `read_image`, `write_image`
- `src.ocr_utils`
- `src.config.DEFAULT_SERIAL`, `EXPECTED_SCREEN_SIZE`
- `src.main` CLI commands for screenshots/device checks when useful

## Initial Reference

- Existing manual screenshot: `manual_screenshots/魔法商店/001_要購買.png`
- Current project ADB serial default: `emulator-5554`
- Screen size: `960x540`

