# Ads Visual Family Smoke Summary

Dataset: `.\vision_platform\ads\pilot\visual_family_smoke_20260721\development_retrain_with_20260720_click_success\training_pool\manifest.csv`

## Per-family mean over seeds

| family | support avg | precision mean | recall mean | f1 mean | fp avg | fn avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| arrow | 13.0 | 0.395 | 0.769 | 0.521 | 15.3 | 3.0 |
| free | 8.0 | 1.000 | 0.375 | 0.545 | 0.0 | 5.0 |
| google_play | 1.0 | 0.444 | 1.000 | 0.611 | 1.3 | 0.0 |
| got | 35.0 | 1.000 | 0.943 | 0.971 | 0.0 | 2.0 |
| next | 2.0 | 0.000 | 0.000 | 0.000 | 8.3 | 2.0 |
| play_triangle | 30.0 | 0.792 | 0.689 | 0.684 | 2.0 | 9.3 |
| x_mark | 18.0 | 0.639 | 0.981 | 0.774 | 10.0 | 0.3 |

## None-of-the-above Check

- Support avg: 80.0
- False activation count avg: 3.7
- False activation rate avg: 0.046

## Notes

- Frozen MobileNetV3-small head-only smoke test, not production.
- Split grouping uses content_id to prevent exact duplicate leakage.
- `negative` remains a human review label, but is no longer a model head.
- Negative rows are used as all-zero none-of-the-above samples.