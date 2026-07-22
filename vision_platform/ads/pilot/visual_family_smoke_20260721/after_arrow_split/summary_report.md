# Ads Visual Family Smoke Summary

Dataset: `.\vision_platform\ads\pilot\visual_family_smoke_20260721\after_arrow_split\training_pool\manifest.csv`

## Per-family mean over seeds

| family | support avg | precision mean | recall mean | f1 mean | fp avg | fn avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| arrow | 7.0 | 0.504 | 0.952 | 0.658 | 6.7 | 0.3 |
| free | 4.0 | 0.256 | 1.000 | 0.407 | 11.7 | 0.0 |
| google_play | 3.0 | 0.173 | 1.000 | 0.295 | 14.3 | 0.0 |
| got | 32.0 | 1.000 | 1.000 | 1.000 | 0.0 | 0.0 |
| next | 2.0 | 0.064 | 0.500 | 0.114 | 14.7 | 1.0 |
| play_triangle | 22.0 | 0.758 | 0.909 | 0.824 | 6.7 | 2.0 |
| x_mark | 28.0 | 0.684 | 0.952 | 0.796 | 12.3 | 1.3 |

## None-of-the-above Check

- Support avg: 103.0
- False activation count avg: 14.3
- False activation rate avg: 0.139

## Notes

- Frozen MobileNetV3-small head-only smoke test, not production.
- Split grouping uses content_id to prevent exact duplicate leakage.
- `negative` remains a human review label, but is no longer a model head.
- Negative rows are used as all-zero none-of-the-above samples.