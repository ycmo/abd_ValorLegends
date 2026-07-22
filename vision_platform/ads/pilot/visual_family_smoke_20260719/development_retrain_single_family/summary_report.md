# Ads Visual Family Smoke Summary

Dataset: `.\vision_platform\ads\pilot\visual_family_smoke_20260719\development_retrain_single_family\training_pool\manifest.csv`

## Per-family mean over seeds

| family | support avg | precision mean | recall mean | f1 mean | fp avg | fn avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| arrow | 11.0 | 0.434 | 0.944 | 0.574 | 15.0 | 0.3 |
| free | 3.7 | 0.652 | 0.833 | 0.651 | 3.3 | 0.3 |
| google_play | 2.7 | 0.500 | 0.389 | 0.433 | 0.7 | 1.3 |
| got | 22.7 | 0.937 | 0.542 | 0.681 | 1.0 | 10.3 |
| next | 1.3 | 0.026 | 0.333 | 0.048 | 12.0 | 1.0 |
| play_triangle | 30.3 | 0.748 | 0.980 | 0.847 | 10.0 | 0.7 |
| x_mark | 16.7 | 0.695 | 0.879 | 0.749 | 7.0 | 1.7 |

## None-of-the-above Check

- Support avg: 72.7
- False activation count avg: 8.7
- False activation rate avg: 0.119

## Notes

- Frozen MobileNetV3-small head-only smoke test, not production.
- Split grouping uses content_id to prevent exact duplicate leakage.
- `negative` remains a human review label, but is no longer a model head.
- Negative rows are used as all-zero none-of-the-above samples.