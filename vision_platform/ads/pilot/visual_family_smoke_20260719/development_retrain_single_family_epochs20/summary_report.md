# Ads Visual Family Smoke Summary

Dataset: `.\vision_platform\ads\pilot\visual_family_smoke_20260719\development_retrain_single_family\training_pool\manifest.csv`

## Per-family mean over seeds

| family | support avg | precision mean | recall mean | f1 mean | fp avg | fn avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| arrow | 11.0 | 0.570 | 0.895 | 0.688 | 8.0 | 1.0 |
| free | 3.7 | 0.317 | 0.767 | 0.402 | 10.3 | 0.7 |
| google_play | 2.7 | 0.750 | 0.917 | 0.806 | 0.7 | 0.3 |
| got | 22.7 | 1.000 | 1.000 | 1.000 | 0.0 | 0.0 |
| next | 1.3 | 0.095 | 0.500 | 0.157 | 4.0 | 0.7 |
| play_triangle | 30.3 | 1.000 | 0.969 | 0.984 | 0.0 | 1.0 |
| x_mark | 16.7 | 0.724 | 0.842 | 0.768 | 5.0 | 2.7 |

## None-of-the-above Check

- Support avg: 72.7
- False activation count avg: 1.3
- False activation rate avg: 0.018

## Notes

- Frozen MobileNetV3-small head-only smoke test, not production.
- Split grouping uses content_id to prevent exact duplicate leakage.
- `negative` remains a human review label, but is no longer a model head.
- Negative rows are used as all-zero none-of-the-above samples.