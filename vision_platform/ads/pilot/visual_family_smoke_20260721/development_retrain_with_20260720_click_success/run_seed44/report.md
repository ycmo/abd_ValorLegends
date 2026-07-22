# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 914 rows, 565 groups, {'google_play': 7, 'x_mark': 136, 'arrow': 67, 'next': 3, 'free': 54, 'play_triangle': 94, 'got': 159, 'negative': 394}
- val: 215 rows, 144 groups, {'google_play': 1, 'arrow': 20, 'next': 1, 'x_mark': 23, 'got': 31, 'play_triangle': 7, 'free': 51, 'negative': 81}
- test: 187 rows, 106 groups, {'x_mark': 18, 'arrow': 13, 'next': 2, 'got': 35, 'play_triangle': 30, 'free': 8, 'google_play': 1, 'negative': 80}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 18 | 0.6429 | 1.0 | 0.7826 | 10 | 0 |
| play_triangle | 30 | 0.9375 | 1.0 | 0.9677 | 2 | 0 |
| google_play | 1 | 0.5 | 1.0 | 0.6667 | 1 | 0 |
| next | 2 | 0.0 | 0.0 | 0.0 | 7 | 2 |
| free | 8 | 1.0 | 0.375 | 0.5455 | 0 | 5 |
| got | 35 | 1.0 | 0.9429 | 0.9706 | 0 | 2 |
| arrow | 13 | 0.4167 | 0.7692 | 0.5405 | 14 | 3 |

## None-of-the-above Check

- Support: 80
- False activation count: 3
- False activation rate: 0.0375
- Strong hard negative weight: 1.0