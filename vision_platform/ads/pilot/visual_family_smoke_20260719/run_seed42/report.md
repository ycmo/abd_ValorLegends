# Ads Visual Family Smoke Test

Device: `cpu`

## Split Counts
- train: 779 rows, 415 groups, {'google_play': 6, 'x_mark': 97, 'arrow': 55, 'next': 21, 'free': 103, 'play_triangle': 32, 'got': 104, 'negative': 384}
- val: 176 rows, 89 groups, {'arrow': 9, 'next': 1, 'google_play': 2, 'x_mark': 14, 'play_triangle': 10, 'got': 24, 'negative': 101, 'free': 16}
- test: 137 rows, 89 groups, {'x_mark': 11, 'google_play': 1, 'arrow': 16, 'got': 23, 'free': 14, 'negative': 69, 'play_triangle': 3, 'next': 4}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 11 | 0.3056 | 1.0 | 0.4681 | 25 | 0 |
| play_triangle | 3 | 1.0 | 1.0 | 1.0 | 0 | 0 |
| google_play | 1 | 0.0 | 0.0 | 0.0 | 0 | 1 |
| next | 4 | 0.2308 | 0.75 | 0.3529 | 10 | 1 |
| free | 14 | 0.5833 | 1.0 | 0.7368 | 10 | 0 |
| got | 23 | 0.9412 | 0.6957 | 0.8 | 1 | 7 |
| arrow | 16 | 0.6667 | 0.875 | 0.7568 | 7 | 2 |

## None-of-the-above Check

- Support: 69
- False activation count: 6
- False activation rate: 0.087
- Strong hard negative weight: 1.0