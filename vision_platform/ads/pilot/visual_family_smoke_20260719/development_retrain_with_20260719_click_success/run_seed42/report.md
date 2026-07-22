# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 818 rows, 491 groups, {'google_play': 7, 'x_mark': 101, 'arrow': 66, 'next': 4, 'free': 37, 'play_triangle': 107, 'got': 132, 'negative': 364}
- val: 183 rows, 107 groups, {'arrow': 13, 'google_play': 1, 'x_mark': 20, 'got': 30, 'next': 1, 'free': 23, 'negative': 87, 'play_triangle': 8}
- test: 202 rows, 104 groups, {'x_mark': 25, 'arrow': 11, 'google_play': 1, 'play_triangle': 16, 'free': 18, 'got': 27, 'next': 1, 'negative': 103}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 25 | 0.6786 | 0.76 | 0.717 | 9 | 6 |
| play_triangle | 16 | 0.9333 | 0.875 | 0.9032 | 1 | 2 |
| google_play | 1 | 1.0 | 1.0 | 1.0 | 0 | 0 |
| next | 1 | 0.0833 | 1.0 | 0.1538 | 11 | 0 |
| free | 18 | 0.5161 | 0.8889 | 0.6531 | 15 | 2 |
| got | 27 | 1.0 | 1.0 | 1.0 | 0 | 0 |
| arrow | 11 | 0.4286 | 0.8182 | 0.5625 | 12 | 2 |

## None-of-the-above Check

- Support: 103
- False activation count: 20
- False activation rate: 0.1942
- Strong hard negative weight: 1.0