# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 802 rows, 430 groups, {'google_play': 6, 'x_mark': 93, 'arrow': 53, 'next': 4, 'free': 35, 'play_triangle': 110, 'got': 107, 'negative': 394}
- val: 161 rows, 89 groups, {'arrow': 16, 'x_mark': 11, 'google_play': 1, 'next': 1, 'free': 8, 'got': 21, 'play_triangle': 10, 'negative': 93}
- test: 146 rows, 89 groups, {'google_play': 2, 'x_mark': 19, 'arrow': 21, 'play_triangle': 11, 'got': 22, 'next': 1, 'free': 3, 'negative': 67}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 19 | 0.4722 | 0.8947 | 0.6182 | 19 | 2 |
| play_triangle | 11 | 0.8889 | 0.7273 | 0.8 | 1 | 3 |
| google_play | 2 | 0.1667 | 0.5 | 0.25 | 5 | 1 |
| next | 1 | 0.0 | 0.0 | 0.0 | 7 | 1 |
| free | 3 | 0.5 | 0.6667 | 0.5714 | 2 | 1 |
| got | 22 | 0.9565 | 1.0 | 0.9778 | 1 | 0 |
| arrow | 21 | 0.8333 | 0.9524 | 0.8889 | 4 | 1 |

## None-of-the-above Check

- Support: 67
- False activation count: 3
- False activation rate: 0.0448
- Strong hard negative weight: 1.0