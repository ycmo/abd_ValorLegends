# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 884 rows, 423 groups, {'x_mark': 90, 'arrow': 51, 'next': 124, 'google_play': 5, 'free': 33, 'play_triangle': 75, 'got': 106, 'negative': 400}
- val: 172 rows, 87 groups, {'google_play': 1, 'arrow': 15, 'next': 1, 'x_mark': 17, 'got': 21, 'play_triangle': 28, 'free': 8, 'negative': 81}
- test: 156 rows, 87 groups, {'google_play': 3, 'x_mark': 9, 'arrow': 14, 'play_triangle': 28, 'got': 23, 'next': 1, 'free': 5, 'negative': 73}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 9 | 0.6429 | 1.0 | 0.7826 | 5 | 0 |
| play_triangle | 28 | 1.0 | 0.9643 | 0.9818 | 0 | 1 |
| google_play | 3 | 0.75 | 1.0 | 0.8571 | 1 | 0 |
| next | 1 | 0.25 | 1.0 | 0.4 | 3 | 0 |
| free | 5 | 0.2857 | 0.8 | 0.4211 | 10 | 1 |
| got | 23 | 1.0 | 1.0 | 1.0 | 0 | 0 |
| arrow | 14 | 0.8125 | 0.9286 | 0.8667 | 3 | 1 |

## None-of-the-above Check

- Support: 73
- False activation count: 4
- False activation rate: 0.0548
- Strong hard negative weight: 1.0