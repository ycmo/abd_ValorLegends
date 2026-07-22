# Ads Visual Family Smoke Summary

Dataset: `.\vision_platform\ads\pilot\visual_family_smoke_20260719\development_retrain\training_pool\manifest.csv`

## Per-family mean over seeds

| family | support avg | precision mean | recall mean | f1 mean | fp avg | fn avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| arrow | 10.3 | 0.417 | 0.944 | 0.556 | 15.3 | 0.3 |
| free | 11.7 | 0.424 | 0.976 | 0.589 | 14.3 | 0.3 |
| google_play | 3.0 | 0.583 | 0.444 | 0.484 | 1.7 | 1.7 |
| got | 25.7 | 0.937 | 0.479 | 0.615 | 1.0 | 13.7 |
| next | 3.0 | 0.258 | 0.533 | 0.325 | 8.7 | 1.0 |
| play_triangle | 12.0 | 0.485 | 0.648 | 0.550 | 5.0 | 1.0 |
| x_mark | 14.3 | 0.547 | 0.768 | 0.627 | 9.3 | 3.3 |

## None-of-the-above Check

- Support avg: 68.7
- False activation count avg: 9.7
- False activation rate avg: 0.144

## Notes

- Frozen MobileNetV3-small head-only smoke test, not production.
- Split grouping uses content_id to prevent exact duplicate leakage.
- `negative` remains a human review label, but is no longer a model head.
- Negative rows are used as all-zero none-of-the-above samples.