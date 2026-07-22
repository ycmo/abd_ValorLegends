# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 764 rows, 419 groups, {'x_mark': 90, 'arrow': 51, 'next': 4, 'google_play': 5, 'free': 33, 'play_triangle': 75, 'got': 106, 'negative': 400}
- val: 172 rows, 87 groups, {'google_play': 1, 'arrow': 15, 'next': 1, 'x_mark': 17, 'got': 21, 'play_triangle': 28, 'free': 8, 'negative': 81}
- test: 156 rows, 87 groups, {'google_play': 3, 'x_mark': 9, 'arrow': 14, 'play_triangle': 28, 'got': 23, 'next': 1, 'free': 5, 'negative': 73}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 9 | 0.381 | 0.8889 | 0.5333 | 13 | 1 |
| play_triangle | 28 | 0.7 | 1.0 | 0.8235 | 12 | 0 |
| google_play | 3 | 1.0 | 0.6667 | 0.8 | 0 | 1 |
| next | 1 | 0.0769 | 1.0 | 0.1429 | 12 | 0 |
| free | 5 | 0.5556 | 1.0 | 0.7143 | 4 | 0 |
| got | 23 | 0.8824 | 0.6522 | 0.75 | 2 | 8 |
| arrow | 14 | 0.7 | 1.0 | 0.8235 | 6 | 0 |

## None-of-the-above Check

- Support: 73
- False activation count: 7
- False activation rate: 0.0959
- Strong hard negative weight: 1.0