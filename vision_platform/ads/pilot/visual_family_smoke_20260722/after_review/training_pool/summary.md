# Visual Family Training Pool

This is a development training pool, not a final generalization holdout.

- Source manifest: `vision_platform\ads\pilot\visual_family_smoke_20260722\after_review\dataset\manifest.csv`
- Rows: 1679
- None-of-the-above rows: 776
- Confirmed strong hard-negative contents: 12
- Confirmed strong hard-negative rows fixed to train: 28
- Missing hard-negative contents: 0
- Non-negative hard rows rejected: 0

## Family Counts

- arrow: 66
- free: 152
- google_play: 9
- got: 265
- negative: 776
- next: 6
- play_triangle: 183
- x_mark: 222

## False Activation Source Families

- arrow: 3
- free: 3
- google_play: 2
- x_mark: 4

## Notes

- `negative` remains a human review label and is represented as all-zero official family labels.
- Confirmed strong hard negatives are forced to `split=train` so they actually enter training.
- A new chronological holdout must be collected separately and kept out of this pool.
