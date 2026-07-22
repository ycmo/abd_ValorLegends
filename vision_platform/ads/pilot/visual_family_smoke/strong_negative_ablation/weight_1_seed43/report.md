# Ads Visual Family Smoke Test

Device: `cpu`

## Split Counts
- train: 591 rows, 325 groups, {'x_mark': 51, 'arrow': 43, 'google_play': 3, 'next': 18, 'free': 27, 'play_triangle': 43, 'got': 65, 'negative': 363}
- val: 142 rows, 69 groups, {'x_mark': 14, 'google_play': 2, 'next': 4, 'arrow': 4, 'got': 14, 'play_triangle': 1, 'negative': 103, 'free': 4}
- test: 137 rows, 69 groups, {'google_play': 3, 'arrow': 11, 'x_mark': 11, 'play_triangle': 1, 'got': 14, 'negative': 88, 'next': 2, 'free': 9}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 11 | 0.5294 | 0.8182 | 0.6429 | 8 | 2 |
| play_triangle | 1 | 0.0 | 0.0 | 0.0 | 0 | 1 |
| google_play | 3 | 1.0 | 0.3333 | 0.5 | 0 | 2 |
| next | 2 | 0.2 | 1.0 | 0.3333 | 8 | 0 |
| free | 9 | 0.4286 | 1.0 | 0.6 | 12 | 0 |
| got | 14 | 0.0 | 0.0 | 0.0 | 0 | 14 |
| arrow | 11 | 0.7273 | 0.7273 | 0.7273 | 3 | 3 |

## None-of-the-above Check

- Support: 88
- False activation count: 13
- False activation rate: 0.1477
- Strong hard negative weight: 1.0