# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 845 rows, 423 groups, {'x_mark': 89, 'google_play': 4, 'arrow': 64, 'next': 124, 'free': 31, 'play_triangle': 46, 'got': 102, 'negative': 385}
- val: 212 rows, 87 groups, {'google_play': 1, 'x_mark': 13, 'arrow': 10, 'next': 1, 'got': 22, 'play_triangle': 56, 'free': 13, 'negative': 96}
- test: 155 rows, 87 groups, {'x_mark': 14, 'arrow': 6, 'google_play': 4, 'play_triangle': 29, 'got': 26, 'next': 1, 'free': 2, 'negative': 73}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 14 | 0.9167 | 0.7857 | 0.8462 | 1 | 3 |
| play_triangle | 29 | 1.0 | 1.0 | 1.0 | 0 | 0 |
| google_play | 4 | 0.6667 | 0.5 | 0.5714 | 1 | 2 |
| next | 1 | 0.0 | 0.0 | 0.0 | 3 | 1 |
| free | 2 | 1.0 | 0.5 | 0.6667 | 0 | 1 |
| got | 26 | 1.0 | 1.0 | 1.0 | 0 | 0 |
| arrow | 6 | 0.3333 | 0.8333 | 0.4762 | 10 | 1 |

## None-of-the-above Check

- Support: 73
- False activation count: 6
- False activation rate: 0.0822
- Strong hard negative weight: 1.0