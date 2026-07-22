# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 759 rows, 415 groups, {'google_play': 5, 'x_mark': 86, 'arrow': 58, 'next': 22, 'free': 99, 'play_triangle': 38, 'got': 101, 'negative': 372}
- val: 173 rows, 89 groups, {'google_play': 1, 'x_mark': 10, 'arrow': 11, 'free': 18, 'got': 25, 'negative': 102, 'next': 3, 'play_triangle': 6}
- test: 160 rows, 89 groups, {'x_mark': 26, 'google_play': 3, 'arrow': 11, 'free': 16, 'play_triangle': 1, 'got': 25, 'negative': 80, 'next': 1}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 26 | 0.2727 | 0.3462 | 0.3051 | 24 | 17 |
| play_triangle | 1 | 0.0 | 0.0 | 0.0 | 0 | 1 |
| google_play | 3 | 0.0 | 0.0 | 0.0 | 0 | 3 |
| next | 1 | 0.125 | 1.0 | 0.2222 | 7 | 0 |
| free | 16 | 0.6667 | 1.0 | 0.8 | 8 | 0 |
| got | 25 | 1.0 | 0.32 | 0.4848 | 0 | 17 |
| arrow | 11 | 0.2381 | 0.9091 | 0.3774 | 32 | 1 |

## None-of-the-above Check

- Support: 80
- False activation count: 12
- False activation rate: 0.15
- Strong hard negative weight: 1.0