# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 725 rows, 419 groups, {'x_mark': 89, 'google_play': 4, 'arrow': 64, 'next': 4, 'free': 31, 'play_triangle': 46, 'got': 102, 'negative': 385}
- val: 212 rows, 87 groups, {'google_play': 1, 'x_mark': 13, 'arrow': 10, 'next': 1, 'got': 22, 'play_triangle': 56, 'free': 13, 'negative': 96}
- test: 155 rows, 87 groups, {'x_mark': 14, 'arrow': 6, 'google_play': 4, 'play_triangle': 29, 'got': 26, 'next': 1, 'free': 2, 'negative': 73}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 14 | 0.8462 | 0.7857 | 0.8148 | 2 | 3 |
| play_triangle | 29 | 1.0 | 1.0 | 1.0 | 0 | 0 |
| google_play | 4 | 0.75 | 0.75 | 0.75 | 1 | 1 |
| next | 1 | 0.0 | 0.0 | 0.0 | 0 | 1 |
| free | 2 | 0.5 | 0.5 | 0.5 | 1 | 1 |
| got | 26 | 1.0 | 1.0 | 1.0 | 0 | 0 |
| arrow | 6 | 0.5 | 0.8333 | 0.625 | 5 | 1 |

## None-of-the-above Check

- Support: 73
- False activation count: 0
- False activation rate: 0.0
- Strong hard negative weight: 1.0