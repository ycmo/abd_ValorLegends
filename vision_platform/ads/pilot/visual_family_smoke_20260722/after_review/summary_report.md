# Ads Visual Family Smoke Summary

Dataset: `.\vision_platform\ads\pilot\visual_family_smoke_20260722\after_review\training_pool\manifest.csv`

## Per-family mean over seeds

| family | support avg | precision mean | recall mean | f1 mean | fp avg | fn avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| arrow | 10.0 | 0.756 | 1.000 | 0.860 | 3.3 | 0.0 |
| free | 5.0 | 0.000 | 0.000 | 0.000 | 0.0 | 5.0 |
| google_play | 1.0 | 0.583 | 1.000 | 0.689 | 1.3 | 0.0 |
| got | 32.0 | 1.000 | 1.000 | 1.000 | 0.0 | 0.0 |
| next | 2.0 | 0.056 | 0.833 | 0.104 | 30.3 | 0.3 |
| play_triangle | 48.0 | 0.815 | 0.896 | 0.852 | 10.0 | 5.0 |
| x_mark | 34.0 | 0.763 | 0.941 | 0.843 | 10.0 | 2.0 |

## None-of-the-above Check

- Support avg: 137.0
- False activation count avg: 13.7
- False activation rate avg: 0.100

## Notes

- Frozen MobileNetV3-small head-only smoke test, not production.
- Split grouping uses content_id to prevent exact duplicate leakage.
- `negative` remains a human review label, but is no longer a model head.
- Negative rows are used as all-zero none-of-the-above samples.