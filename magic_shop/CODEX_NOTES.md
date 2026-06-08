# Magic Shop Codex Notes

> Purpose: handoff notes for AGY/Codex working only inside `magic_shop/`.

## Scope

- Task: develop automation for `魔法商店`.
- The user approved daily-task mainline integration on 2026-06-08 for debug/optimization.
- Buying logic still lives in `magic_shop/`; mainline integration is only the thin task registry/spec path under `src/`.

## Known Inputs

- Manual screenshot: `manual_screenshots/魔法商店/001_要購買.png`
- The screenshot was captured with:

```powershell
python -m src.manual_screenshots --task 魔法商店 --index 1 --scene 要購買
```

`src.manual_screenshots` now opens Paint by default after saving.

## Development Notes

- Store module assets in `magic_shop/assets/`.
- Store scripts in `magic_shop/scripts/`.
- Store runtime captures in `magic_shop/runtime_captures/`.
- Store debug crops/annotated images in `magic_shop/debug_output/`.
- If a reusable change seems necessary in `src/`, write it in `QA.md` and stop instead of editing outside this directory.

## Current Status

- `MagicShopTask` is implemented in `magic_shop_task.py`.
- It is registered as `magic_shop` in the main daily-task runner.
- Daily task label asset: `assets/tasks/magic_shop/task_label.png`, copied from `manual_screenshots/魔法商店/001_每日任務.png`.
- Return-to-Daily uses `magic_shop/assets/back_arrow.png`, cropped from `captures/magic_shop_probe.png`.
- Offline checks passed on 2026-06-08: compileall, `src.main list-tasks`, missing-asset check, Magic Shop scene match on `captures/magic_shop_probe.png`, and 44 unittest tests.
- Live run is still pending because ADB reported no connected devices after integration.
