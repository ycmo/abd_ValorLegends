# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 1166 rows, 771 groups, {'google_play': 7, 'x_mark': 161, 'arrow': 49, 'next': 3, 'play_triangle': 92, 'free': 144, 'got': 188, 'negative': 522}
- val: 244 rows, 146 groups, {'x_mark': 27, 'play_triangle': 43, 'next': 1, 'google_play': 1, 'free': 3, 'got': 45, 'negative': 117, 'arrow': 7}
- test: 269 rows, 147 groups, {'x_mark': 34, 'play_triangle': 48, 'next': 2, 'free': 5, 'got': 32, 'negative': 137, 'arrow': 10, 'google_play': 1}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 34 | 0.7727 | 1.0 | 0.8718 | 10 | 0 |
| play_triangle | 48 | 0.8723 | 0.8542 | 0.8632 | 6 | 7 |
| google_play | 1 | 0.5 | 1.0 | 0.6667 | 1 | 0 |
| next | 2 | 0.05 | 1.0 | 0.0952 | 38 | 0 |
| free | 5 | 0.0 | 0.0 | 0.0 | 0 | 5 |
| got | 32 | 1.0 | 1.0 | 1.0 | 0 | 0 |
| arrow | 10 | 0.7692 | 1.0 | 0.8696 | 3 | 0 |

## None-of-the-above Check

- Support: 137
- False activation count: 7
- False activation rate: 0.0511
- Strong hard negative weight: 1.0