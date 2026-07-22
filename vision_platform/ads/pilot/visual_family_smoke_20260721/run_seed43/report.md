# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 968 rows, 523 groups, {'google_play': 6, 'x_mark': 100, 'arrow': 69, 'next': 3, 'play_triangle': 109, 'free': 23, 'got': 101, 'negative': 557}
- val: 173 rows, 110 groups, {'x_mark': 16, 'next': 2, 'arrow': 16, 'google_play': 2, 'got': 26, 'negative': 84, 'play_triangle': 20, 'free': 7}
- test: 159 rows, 110 groups, {'google_play': 1, 'x_mark': 23, 'arrow': 18, 'free': 16, 'play_triangle': 2, 'got': 24, 'negative': 74, 'next': 1}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 23 | 0.64 | 0.6957 | 0.6667 | 9 | 7 |
| play_triangle | 2 | 0.6667 | 1.0 | 0.8 | 1 | 0 |
| google_play | 1 | 0.0 | 0.0 | 0.0 | 1 | 1 |
| next | 1 | 0.0 | 0.0 | 0.0 | 10 | 1 |
| free | 16 | 1.0 | 0.6875 | 0.8148 | 0 | 5 |
| got | 24 | 1.0 | 1.0 | 1.0 | 0 | 0 |
| arrow | 18 | 0.4444 | 0.8889 | 0.5926 | 20 | 2 |

## None-of-the-above Check

- Support: 74
- False activation count: 16
- False activation rate: 0.2162
- Strong hard negative weight: 1.0