# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 774 rows, 415 groups, {'google_play': 5, 'x_mark': 81, 'arrow': 51, 'next': 16, 'free': 109, 'play_triangle': 19, 'got': 110, 'negative': 400}
- val: 154 rows, 89 groups, {'google_play': 3, 'arrow': 14, 'next': 7, 'play_triangle': 4, 'got': 25, 'x_mark': 16, 'free': 10, 'negative': 84}
- test: 164 rows, 89 groups, {'x_mark': 25, 'arrow': 15, 'google_play': 1, 'free': 14, 'play_triangle': 22, 'got': 16, 'next': 3, 'negative': 70}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 25 | 0.7097 | 0.88 | 0.7857 | 9 | 3 |
| play_triangle | 22 | 1.0 | 0.9091 | 0.9524 | 0 | 2 |
| google_play | 1 | 0.1429 | 1.0 | 0.25 | 6 | 0 |
| next | 3 | 0.1667 | 0.6667 | 0.2667 | 10 | 1 |
| free | 14 | 0.7 | 1.0 | 0.8235 | 6 | 0 |
| got | 16 | 1.0 | 0.3125 | 0.4762 | 0 | 11 |
| arrow | 15 | 0.3171 | 0.8667 | 0.4643 | 28 | 2 |

## None-of-the-above Check

- Support: 70
- False activation count: 10
- False activation rate: 0.1429
- Strong hard negative weight: 1.0