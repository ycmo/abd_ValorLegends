# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 764 rows, 419 groups, {'x_mark': 93, 'arrow': 51, 'next': 8, 'google_play': 5, 'free': 34, 'play_triangle': 74, 'got': 107, 'negative': 400}
- val: 172 rows, 87 groups, {'google_play': 1, 'arrow': 15, 'next': 7, 'x_mark': 17, 'got': 21, 'play_triangle': 28, 'free': 8, 'negative': 81}
- test: 156 rows, 87 groups, {'google_play': 3, 'x_mark': 10, 'arrow': 14, 'play_triangle': 28, 'got': 23, 'next': 5, 'free': 5, 'negative': 73}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 10 | 0.3333 | 0.8 | 0.4706 | 16 | 2 |
| play_triangle | 28 | 0.7 | 1.0 | 0.8235 | 12 | 0 |
| google_play | 3 | 1.0 | 0.6667 | 0.8 | 0 | 1 |
| next | 5 | 0.0 | 0.0 | 0.0 | 12 | 5 |
| free | 5 | 0.5 | 1.0 | 0.6667 | 5 | 0 |
| got | 23 | 0.8889 | 0.6957 | 0.7805 | 2 | 7 |
| arrow | 14 | 0.7 | 1.0 | 0.8235 | 6 | 0 |

## None-of-the-above Check

- Support: 73
- False activation count: 7
- False activation rate: 0.0959
- Strong hard negative weight: 1.0