# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 991 rows, 560 groups, {'google_play': 5, 'x_mark': 112, 'arrow': 87, 'next': 4, 'free': 38, 'play_triangle': 124, 'got': 97, 'negative': 524}
- val: 198 rows, 118 groups, {'x_mark': 12, 'arrow': 12, 'google_play': 2, 'got': 33, 'play_triangle': 2, 'negative': 131, 'next': 1, 'free': 5}
- test: 176 rows, 118 groups, {'google_play': 2, 'arrow': 18, 'x_mark': 15, 'got': 21, 'play_triangle': 5, 'negative': 111, 'next': 1, 'free': 3}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 15 | 0.65 | 0.8667 | 0.7429 | 7 | 2 |
| play_triangle | 5 | 1.0 | 1.0 | 1.0 | 0 | 0 |
| google_play | 2 | 0.4 | 1.0 | 0.5714 | 3 | 0 |
| next | 1 | 0.2 | 1.0 | 0.3333 | 4 | 0 |
| free | 3 | 0.5 | 0.6667 | 0.5714 | 2 | 1 |
| got | 21 | 0.9524 | 0.9524 | 0.9524 | 1 | 1 |
| arrow | 18 | 0.6364 | 0.7778 | 0.7 | 8 | 4 |

## None-of-the-above Check

- Support: 111
- False activation count: 13
- False activation rate: 0.1171
- Strong hard negative weight: 1.0