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
- 2026-06-21: each refresh page now scans three overlapping vertical views. Required recurring purchases are `960k`, `480k`, and `1800k x3`; `5000k` remains optional because it does not appear on every refresh.
- 2026-06-26: product scanning was changed from broad EasyOCR price detection to template matching for speed. Each target now requires both a matching item icon under `magic_shop/assets/商品圖片/` and the expected coin-price button below it. This avoids false positives from similar blue price buttons such as non-target `8294k` or red-gem items. Only coin-balance reading still uses OCR.
- 2026-06-26: refresh-cost detection cross-checks `刷新100.png` and `刷新200.png`. The probe crops off the shared red-gem/button background and compares only the numeric part inside `REFRESH_BUTTON_ROI`; full-button matching made 200 too similar to 100. Refresh is allowed only when 100 passes threshold and beats 200 by the configured margin.
- 2026-06-26: shop-list swipes intentionally use a slower `900ms` drag while keeping the post-swipe settle delay at `1.0s`. The shop list contains tappable item cards, and very mechanical/fast ADB swipes can behave less like a human press-then-drag gesture.
- 2026-06-27: a live debug run showed `480k` can land at the viewport edge with the item icon clipped while the price button is fully visible. `480k` now has a high-confidence price-only fallback (`0.98`) after the normal icon+price scan. This is intentionally narrow; generic price-only matching at lower confidence caused false positives on similar blue coin buttons.
- 2026-06-27: removed the `碎片買滿.png` tap from the purchase dialog flow. That template covered the whole quantity panel, so its match center was the quantity field, producing a harmless but confusing extra tap such as action debug `000158`. Multi-buy still works by repeatedly buying while the price button remains bright.
- 2026-06-27: item search now uses narrow fixed x-axis column ROIs with the same y-axis as the old shop ROI. `960k` scans the left column, `480k` and `1800k` scan the middle column, and `5000k` scans the right-middle column. Review image: `magic_shop/debug_output/current_item_column_rois.png`.
