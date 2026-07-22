# Ads Visual Family Smoke Summary

Dataset: `.\vision_platform\ads\pilot\visual_family_smoke_20260721\after_high_value_review\training_pool\manifest.csv`

## Per-family mean over seeds

| family | support avg | precision mean | recall mean | f1 mean | fp avg | fn avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| arrow | 18.0 | 0.615 | 0.796 | 0.694 | 9.0 | 3.7 |
| free | 3.0 | 0.500 | 0.667 | 0.571 | 2.0 | 1.0 |
| google_play | 2.0 | 0.340 | 1.000 | 0.505 | 4.0 | 0.0 |
| got | 21.0 | 0.952 | 0.952 | 0.952 | 1.0 | 1.0 |
| next | 1.0 | 0.225 | 1.000 | 0.361 | 4.0 | 0.0 |
| play_triangle | 5.0 | 1.000 | 1.000 | 1.000 | 0.0 | 0.0 |
| x_mark | 15.0 | 0.642 | 0.867 | 0.737 | 7.3 | 2.0 |

## None-of-the-above Check

- Support avg: 111.0
- False activation count avg: 14.3
- False activation rate avg: 0.129

## Notes

- Frozen MobileNetV3-small head-only smoke test, not production.
- Split grouping uses content_id to prevent exact duplicate leakage.
- `negative` remains a human review label, but is no longer a model head.
- Negative rows are used as all-zero none-of-the-above samples.