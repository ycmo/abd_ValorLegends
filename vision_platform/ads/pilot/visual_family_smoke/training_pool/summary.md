# Visual Family Training Pool

This is a development training pool, not a final generalization holdout.

- Source manifest: `vision_platform\ads\pilot\visual_family_smoke\dataset\manifest.csv`
- Rows: 870
- None-of-the-above rows: 554
- Confirmed strong hard-negative contents: 14
- Confirmed strong hard-negative rows fixed to train: 50
- Missing hard-negative contents: 0
- Non-negative hard rows rejected: 0

## Family Counts

- arrow: 58
- free: 40
- google_play: 8
- got: 93
- negative: 554
- next: 24
- play_triangle: 45
- x_mark: 76

## False Activation Source Families

- arrow: 9
- free: 10
- google_play: 4
- x_mark: 42

## Notes

- `negative` remains a human review label and is represented as all-zero official family labels.
- Confirmed strong hard negatives are forced to `split=train` so they actually enter training.
- A new chronological holdout must be collected separately and kept out of this pool.
