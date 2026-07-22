# Ads Detector Dataset v2

- Target class: `visual_candidate`
- Screens: 942
- BBoxes: 986
- Partial-annotation screens: 465
- Verified empty negative screens: 0
- Manual bbox count: 509
- Weak-positive bbox count: 477
- Classifier positive-family crops unable to trace parent+bbox: 68

## Split Counts
- `test` screens: 54
- `train` screens: 820
- `val` screens: 68

## Dataset Role by Split
- `manual_positive`: {'train': 343, 'val': 68, 'test': 54}
- `weak_positive`: {'train': 477}

## Proposal Sources
- `close_glyph`: 2
- `close_template`: 198
- `free_ad_template`: 192
- `got_template`: 85

## Notes

- This v2 dataset is for dataset audit only; no detector training or runtime integration is performed.
- `waiting` and `returned_to_game` are not treated as empty negatives unless explicitly verified as no visual candidate.
- `_edit`/`_original` style paths are grouped by normalized creative stem; click-success weak positives are train-only.