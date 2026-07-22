# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 764 rows, 419 groups, {'x_mark': 95, 'arrow': 51, 'next': 14, 'google_play': 5, 'free': 81, 'play_triangle': 28, 'got': 107, 'negative': 400}
- val: 172 rows, 87 groups, {'google_play': 1, 'arrow': 15, 'next': 7, 'x_mark': 17, 'got': 21, 'free': 35, 'negative': 81, 'play_triangle': 1}
- test: 156 rows, 87 groups, {'google_play': 3, 'x_mark': 10, 'arrow': 14, 'play_triangle': 16, 'got': 23, 'free': 17, 'next': 5, 'negative': 73}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 10 | 0.3636 | 0.8 | 0.5 | 14 | 2 |
| play_triangle | 16 | 0.8889 | 1.0 | 0.9412 | 2 | 0 |
| google_play | 3 | 0.25 | 0.3333 | 0.2857 | 3 | 2 |
| next | 5 | 0.5 | 0.6 | 0.5455 | 3 | 2 |
| free | 17 | 0.4595 | 1.0 | 0.6296 | 20 | 0 |
| got | 23 | 0.8824 | 0.6522 | 0.75 | 2 | 8 |
| arrow | 14 | 0.7 | 1.0 | 0.8235 | 6 | 0 |

## None-of-the-above Check

- Support: 73
- False activation count: 6
- False activation rate: 0.0822
- Strong hard negative weight: 1.0