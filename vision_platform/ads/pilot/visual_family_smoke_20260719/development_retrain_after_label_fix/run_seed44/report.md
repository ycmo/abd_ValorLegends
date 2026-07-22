# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 800 rows, 419 groups, {'x_mark': 78, 'arrow': 57, 'google_play': 5, 'next': 14, 'free': 28, 'play_triangle': 127, 'got': 103, 'negative': 401}
- val: 169 rows, 87 groups, {'x_mark': 23, 'arrow': 12, 'google_play': 2, 'next': 3, 'got': 20, 'negative': 93, 'free': 16, 'play_triangle': 1}
- test: 123 rows, 87 groups, {'google_play': 2, 'arrow': 11, 'x_mark': 19, 'free': 3, 'play_triangle': 2, 'got': 28, 'negative': 60, 'next': 3}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 19 | 0.6818 | 0.7895 | 0.7317 | 7 | 4 |
| play_triangle | 2 | 0.4 | 1.0 | 0.5714 | 3 | 0 |
| google_play | 2 | 1.0 | 0.5 | 0.6667 | 0 | 1 |
| next | 3 | 0.2727 | 1.0 | 0.4286 | 8 | 0 |
| free | 3 | 0.5 | 0.3333 | 0.4 | 1 | 2 |
| got | 28 | 1.0 | 0.2857 | 0.4444 | 0 | 20 |
| arrow | 11 | 0.3438 | 1.0 | 0.5116 | 21 | 0 |

## None-of-the-above Check

- Support: 60
- False activation count: 13
- False activation rate: 0.2167
- Strong hard negative weight: 1.0