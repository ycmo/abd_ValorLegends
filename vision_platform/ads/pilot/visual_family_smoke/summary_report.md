# Ads Visual Family Smoke Summary

Dataset: `.\vision_platform\ads\pilot\visual_family_smoke\dataset\manifest.csv`

## Per-family mean over seeds

| family | support avg | precision mean | recall mean | f1 mean | fp avg | fn avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| arrow | 11.0 | 0.570 | 0.758 | 0.641 | 7.0 | 2.7 |
| free | 9.0 | 0.536 | 1.000 | 0.686 | 9.0 | 0.0 |
| google_play | 3.0 | 0.444 | 0.333 | 0.315 | 1.3 | 2.0 |
| got | 14.0 | 0.667 | 0.333 | 0.442 | 0.0 | 9.3 |
| next | 2.0 | 0.067 | 0.333 | 0.111 | 4.7 | 1.3 |
| play_triangle | 1.0 | 0.111 | 0.333 | 0.167 | 0.7 | 0.7 |
| x_mark | 11.0 | 0.414 | 0.727 | 0.470 | 22.0 | 3.0 |

## None-of-the-above Check

- Support avg: 88.0
- False activation count avg: 21.7
- False activation rate avg: 0.246

## Notes

- Frozen MobileNetV3-small head-only smoke test, not production.
- Split grouping uses content_id to prevent exact duplicate leakage.
- `negative` remains a human review label, but is no longer a model head.
- Negative rows are used as all-zero none-of-the-above samples.