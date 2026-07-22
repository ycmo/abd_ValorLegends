# Ads Visual Family Smoke Test

Device: `cpu`

## Split Counts
- train: 591 rows, 325 groups, {'x_mark': 51, 'arrow': 43, 'google_play': 3, 'next': 18, 'free': 27, 'play_triangle': 43, 'got': 65, 'negative': 363}
- val: 142 rows, 69 groups, {'x_mark': 14, 'google_play': 2, 'next': 4, 'arrow': 4, 'got': 14, 'play_triangle': 1, 'negative': 103, 'free': 4}
- test: 137 rows, 69 groups, {'google_play': 3, 'arrow': 11, 'x_mark': 11, 'play_triangle': 1, 'got': 14, 'negative': 88, 'next': 2, 'free': 9}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 11 | 0.1562 | 0.9091 | 0.2667 | 54 | 1 |
| play_triangle | 1 | 0.3333 | 1.0 | 0.5 | 2 | 0 |
| google_play | 3 | 0.0 | 0.0 | 0.0 | 0 | 3 |
| next | 2 | 0.0 | 0.0 | 0.0 | 0 | 2 |
| free | 9 | 0.75 | 1.0 | 0.8571 | 3 | 0 |
| got | 14 | 1.0 | 0.5714 | 0.7273 | 0 | 6 |
| arrow | 11 | 0.5333 | 0.7273 | 0.6154 | 7 | 3 |

## None-of-the-above Check

- Support: 88
- False activation count: 37
- False activation rate: 0.4205
- Strong hard negative weight: 3.0