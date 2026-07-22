# Embedding Reference Smoke Test

Manifest: `vision_platform\ads\pilot\visual_family_smoke_20260719\development_retrain_single_family\dataset\manifest.csv`
Rows: `1092`
Device: `cuda`

| family | references | threshold | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| next | 6 | 0.80 | 0.105 | 0.333 | 0.160 | 17 | 4 |
| google_play | 9 | 0.92 | 1.000 | 0.667 | 0.800 | 0 | 3 |