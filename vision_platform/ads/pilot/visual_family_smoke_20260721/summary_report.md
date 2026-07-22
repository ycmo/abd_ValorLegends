# Ads Visual Family Smoke Summary

Dataset: `.\vision_platform\ads\pilot\visual_family_smoke_20260721\training_pool\manifest.csv`

## Per-family mean over seeds

| family | support avg | precision mean | recall mean | f1 mean | fp avg | fn avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| arrow | 18.0 | 0.463 | 0.889 | 0.607 | 19.0 | 2.0 |
| free | 16.0 | 1.000 | 0.708 | 0.829 | 0.0 | 4.7 |
| google_play | 1.0 | 0.000 | 0.000 | 0.000 | 2.0 | 1.0 |
| got | 24.0 | 1.000 | 0.986 | 0.993 | 0.0 | 0.3 |
| next | 1.0 | 0.000 | 0.000 | 0.000 | 11.7 | 1.0 |
| play_triangle | 2.0 | 0.556 | 0.833 | 0.667 | 1.3 | 0.3 |
| x_mark | 23.0 | 0.676 | 0.725 | 0.699 | 8.0 | 6.3 |

## None-of-the-above Check

- Support avg: 74.0
- False activation count avg: 11.0
- False activation rate avg: 0.149

## Notes

- Frozen MobileNetV3-small head-only smoke test, not production.
- Split grouping uses content_id to prevent exact duplicate leakage.
- `negative` remains a human review label, but is no longer a model head.
- Negative rows are used as all-zero none-of-the-above samples.