# Ads Detector Dataset v2

- Target class: `visual_candidate`
- Screens: 707
- BBoxes: 751
- Partial-annotation screens: 323
- Verified empty negative screens: 0
- Manual bbox count: 367
- Weak-positive bbox count: 384
- Classifier positive-family crops unable to trace parent+bbox: 77

## Split Counts
- `test` screens: 83
- `train` screens: 581
- `val` screens: 43

## Dataset Role by Split
- `manual_positive`: {'val': 43, 'train': 197, 'test': 83}
- `weak_positive`: {'train': 384}

## Proposal Sources
- `close_glyph`: 2
- `close_template`: 131
- `free_ad_template`: 118
- `got_template`: 133

## Notes

- This v2 dataset is for dataset audit only; no detector training or runtime integration is performed.
- `waiting` and `returned_to_game` are not treated as empty negatives unless explicitly verified as no visual candidate.
- `_edit`/`_original` style paths are grouped by normalized creative stem; click-success weak positives are train-only.