# midas

Required:

```text
task_label.png
free_button.png
gem_20_button.png
gem_50_button.png
```

Optional:

```text
confirm_button.png
```

Policy: free + 20 gems + 50 gems only.

## AFK route requirement

Recurring Midas runs must enter through:

```text
AwayFromKeyboard/route_screenshots/點金手
```

After that route opens the Midas dialog, execute only the current scene:

```text
python -m src.main run-current-scene-task midas
```

Do not use `run-task midas` from `loop_toggle_midas.py` or an AFK route. That
command may fall back to the Daily Tasks list when the current Midas dialog is
not recognized. Completed Daily Tasks can no longer provide a runnable Midas
row, while the AFK lobby route remains available for recurring Midas runs.

Cooldown OCR uses the fixed 960x540 ROI `(482, 124, 74, 22)`. This narrow crop
excludes the refresh icon/text that previously produced leading noise such as
`0:04:17:52` or `004:58:36`. If EasyOCR returns separate noise and time blocks,
select the valid `HH:MM:SS` block instead of concatenating every block.
