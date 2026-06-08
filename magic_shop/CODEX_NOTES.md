# Magic Shop Codex Notes

> Purpose: handoff notes for AGY/Codex working only inside `magic_shop/`.

## Scope

- Task: develop automation for `魔法商店`.
- This is an isolated module. Do not integrate into daily-task mainline until the route is proven and approved.
- Do not modify files outside `magic_shop/`.

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

- Workspace scaffold created.
- No route implementation yet.
- Product policy for what Magic Shop should buy is not yet confirmed in this directory.

