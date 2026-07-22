# Ads Detector Dataset v2

- Target class: `visual_candidate`
- Screens: 702
- BBoxes: 825
- Partial-annotation screens: 692
- Verified empty negative screens: 0
- Manual bbox count: 815
- Weak-positive bbox count: 10
- Classifier positive-family crops unable to trace parent+bbox: 68

## Split Counts
- `test` screens: 92
- `train` screens: 505
- `val` screens: 105

## Dataset Role by Split
- `manual_positive`: {'train': 495, 'val': 105, 'test': 92}
- `weak_positive`: {'train': 10}

## Proposal Sources
- `close_template`: 10

## Notes

- This v2 dataset is for dataset audit only; no detector training or runtime integration is performed.
- `waiting` and `returned_to_game` are not treated as empty negatives unless explicitly verified as no visual candidate.
- `_edit`/`_original` style paths are grouped by normalized creative stem; click-success weak positives are train-only.