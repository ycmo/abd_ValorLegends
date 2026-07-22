# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 884 rows, 423 groups, {'x_mark': 90, 'arrow': 51, 'next': 124, 'google_play': 5, 'free': 33, 'play_triangle': 75, 'got': 106, 'negative': 400}
- val: 172 rows, 87 groups, {'google_play': 1, 'arrow': 15, 'next': 1, 'x_mark': 17, 'got': 21, 'play_triangle': 28, 'free': 8, 'negative': 81}
- test: 156 rows, 87 groups, {'google_play': 3, 'x_mark': 9, 'arrow': 14, 'play_triangle': 28, 'got': 23, 'next': 1, 'free': 5, 'negative': 73}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 9 | 0.5625 | 1.0 | 0.72 | 7 | 0 |
| play_triangle | 28 | 0.9655 | 1.0 | 0.9825 | 1 | 0 |
| google_play | 3 | 0.6667 | 0.6667 | 0.6667 | 1 | 1 |
| next | 1 | 0.0 | 0.0 | 0.0 | 4 | 1 |
| free | 5 | 1.0 | 0.8 | 0.8889 | 0 | 1 |
| got | 23 | 0.9583 | 1.0 | 0.9787 | 1 | 0 |
| arrow | 14 | 0.6087 | 1.0 | 0.7568 | 9 | 0 |

## None-of-the-above Check

- Support: 73
- False activation count: 6
- False activation rate: 0.0822
- Strong hard negative weight: 1.0