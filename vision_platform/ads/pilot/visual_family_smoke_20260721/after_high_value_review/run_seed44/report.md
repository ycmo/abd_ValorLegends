# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 991 rows, 560 groups, {'google_play': 5, 'x_mark': 112, 'arrow': 87, 'next': 4, 'free': 38, 'play_triangle': 124, 'got': 97, 'negative': 524}
- val: 198 rows, 118 groups, {'x_mark': 12, 'arrow': 12, 'google_play': 2, 'got': 33, 'play_triangle': 2, 'negative': 131, 'next': 1, 'free': 5}
- test: 176 rows, 118 groups, {'google_play': 2, 'arrow': 18, 'x_mark': 15, 'got': 21, 'play_triangle': 5, 'negative': 111, 'next': 1, 'free': 3}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 15 | 0.5909 | 0.8667 | 0.7027 | 9 | 2 |
| play_triangle | 5 | 1.0 | 1.0 | 1.0 | 0 | 0 |
| google_play | 2 | 0.2857 | 1.0 | 0.4444 | 5 | 0 |
| next | 1 | 0.1429 | 1.0 | 0.25 | 6 | 0 |
| free | 3 | 0.5 | 0.6667 | 0.5714 | 2 | 1 |
| got | 21 | 0.9524 | 0.9524 | 0.9524 | 1 | 1 |
| arrow | 18 | 0.625 | 0.8333 | 0.7143 | 9 | 3 |

## None-of-the-above Check

- Support: 111
- False activation count: 17
- False activation rate: 0.1532
- Strong hard negative weight: 1.0