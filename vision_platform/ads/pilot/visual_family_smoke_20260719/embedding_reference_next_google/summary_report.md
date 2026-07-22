# Embedding Reference Smoke Test

Manifest: `vision_platform\ads\pilot\visual_family_smoke_20260719\development_retrain_single_family\dataset\manifest.csv`
Rows: `1092`
Device: `cuda`

| family | references | threshold | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| next | 6 | 0.88 | 0.500 | 0.667 | 0.571 | 4 | 2 |
| google_play | 9 | 0.94 | 1.000 | 0.778 | 0.875 | 0 | 2 |