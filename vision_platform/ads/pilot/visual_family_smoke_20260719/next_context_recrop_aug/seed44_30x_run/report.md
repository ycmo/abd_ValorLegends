# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 789 rows, 421 groups, {'google_play': 7, 'x_mark': 73, 'arrow': 53, 'next': 62, 'free': 23, 'play_triangle': 63, 'got': 114, 'negative': 394}
- val: 191 rows, 87 groups, {'x_mark': 16, 'arrow': 14, 'next': 2, 'google_play': 1, 'free': 19, 'got': 17, 'play_triangle': 34, 'negative': 88}
- test: 172 rows, 87 groups, {'x_mark': 27, 'arrow': 13, 'google_play': 1, 'play_triangle': 34, 'got': 19, 'next': 2, 'negative': 72, 'free': 4}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 27 | 0.7931 | 0.8519 | 0.8214 | 6 | 4 |
| play_triangle | 34 | 1.0 | 0.9412 | 0.9697 | 0 | 2 |
| google_play | 1 | 0.5 | 1.0 | 0.6667 | 1 | 0 |
| next | 2 | 1.0 | 0.5 | 0.6667 | 0 | 1 |
| free | 4 | 0.1538 | 1.0 | 0.2667 | 22 | 0 |
| got | 19 | 1.0 | 1.0 | 1.0 | 0 | 0 |
| arrow | 13 | 0.5 | 0.9231 | 0.6486 | 12 | 1 |

## None-of-the-above Check

- Support: 72
- False activation count: 2
- False activation rate: 0.0278
- Strong hard negative weight: 1.0