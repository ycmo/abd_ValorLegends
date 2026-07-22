# Ads Detector Dataset v2

- Target class: `visual_candidate`
- Screens: 942
- BBoxes: 1023
- Partial-annotation screens: 581
- Verified empty negative screens: 0
- Manual bbox count: 662
- Weak-positive bbox count: 361
- Classifier positive-family crops unable to trace parent+bbox: 68

## Split Counts
- `test` screens: 132
- `train` screens: 736
- `val` screens: 74

## Dataset Role by Split
- `manual_positive`: {'train': 375, 'test': 132, 'val': 74}
- `weak_positive`: {'train': 361}

## Proposal Sources
- `close_glyph`: 2
- `close_template`: 159
- `free_ad_template`: 153
- `got_template`: 47

## Notes

- This v2 dataset is for dataset audit only; no detector training or runtime integration is performed.
- `waiting` and `returned_to_game` are not treated as empty negatives unless explicitly verified as no visual candidate.
- `_edit`/`_original` style paths are grouped by normalized creative stem; click-success weak positives are train-only.