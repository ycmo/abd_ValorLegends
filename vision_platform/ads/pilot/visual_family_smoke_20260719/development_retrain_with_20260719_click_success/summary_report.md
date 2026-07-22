# Ads Visual Family Smoke Summary

Dataset: `.\vision_platform\ads\pilot\visual_family_smoke_20260719\development_retrain_with_20260719_click_success\training_pool\manifest.csv`

## Per-family mean over seeds

| family | support avg | precision mean | recall mean | f1 mean | fp avg | fn avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| arrow | 11.0 | 0.443 | 0.818 | 0.575 | 11.3 | 2.0 |
| free | 18.0 | 0.769 | 0.926 | 0.830 | 6.3 | 1.3 |
| google_play | 1.0 | 0.556 | 1.000 | 0.667 | 1.3 | 0.0 |
| got | 27.0 | 1.000 | 1.000 | 1.000 | 0.0 | 0.0 |
| next | 1.0 | 0.044 | 0.667 | 0.082 | 12.3 | 0.3 |
| play_triangle | 16.0 | 0.933 | 0.875 | 0.903 | 1.0 | 2.0 |
| x_mark | 25.0 | 0.802 | 0.760 | 0.778 | 5.0 | 6.0 |

## None-of-the-above Check

- Support avg: 103.0
- False activation count avg: 10.0
- False activation rate avg: 0.097

## Notes

- Frozen MobileNetV3-small head-only smoke test, not production.
- Split grouping uses content_id to prevent exact duplicate leakage.
- `negative` remains a human review label, but is no longer a model head.
- Negative rows are used as all-zero none-of-the-above samples.