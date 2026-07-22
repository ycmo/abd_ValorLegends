# Ads Visual Family Smoke Summary

Dataset: `.\vision_platform\ads\pilot\visual_family_smoke_20260719\development_retrain_after_label_fix\training_pool\manifest.csv`

## Per-family mean over seeds

| family | support avg | precision mean | recall mean | f1 mean | fp avg | fn avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| arrow | 10.3 | 0.417 | 0.944 | 0.556 | 15.3 | 0.3 |
| free | 3.7 | 0.667 | 0.556 | 0.522 | 2.0 | 1.3 |
| google_play | 3.0 | 0.833 | 0.556 | 0.656 | 0.7 | 1.3 |
| got | 25.7 | 0.939 | 0.494 | 0.625 | 1.0 | 13.3 |
| next | 3.0 | 0.091 | 0.333 | 0.143 | 12.7 | 2.0 |
| play_triangle | 19.3 | 0.600 | 1.000 | 0.739 | 9.0 | 0.0 |
| x_mark | 14.3 | 0.568 | 0.792 | 0.645 | 9.3 | 3.0 |

## None-of-the-above Check

- Support avg: 68.7
- False activation count avg: 11.0
- False activation rate avg: 0.164

## Notes

- Frozen MobileNetV3-small head-only smoke test, not production.
- Split grouping uses content_id to prevent exact duplicate leakage.
- `negative` remains a human review label, but is no longer a model head.
- Negative rows are used as all-zero none-of-the-above samples.