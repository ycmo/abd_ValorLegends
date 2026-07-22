# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 800 rows, 419 groups, {'x_mark': 80, 'arrow': 57, 'google_play': 5, 'next': 20, 'free': 113, 'play_triangle': 42, 'got': 103, 'negative': 401}
- val: 169 rows, 87 groups, {'x_mark': 23, 'arrow': 12, 'google_play': 2, 'next': 3, 'got': 20, 'negative': 93, 'free': 16, 'play_triangle': 1}
- test: 123 rows, 87 groups, {'google_play': 2, 'arrow': 11, 'x_mark': 19, 'free': 4, 'play_triangle': 2, 'got': 28, 'negative': 60, 'next': 3}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 19 | 0.6522 | 0.7895 | 0.7143 | 8 | 4 |
| play_triangle | 2 | 0.0 | 0.0 | 0.0 | 0 | 2 |
| google_play | 2 | 1.0 | 0.5 | 0.6667 | 0 | 1 |
| next | 3 | 0.2727 | 1.0 | 0.4286 | 8 | 0 |
| free | 4 | 0.3636 | 1.0 | 0.5333 | 7 | 0 |
| got | 28 | 1.0 | 0.2857 | 0.4444 | 0 | 20 |
| arrow | 11 | 0.3438 | 1.0 | 0.5116 | 21 | 0 |

## None-of-the-above Check

- Support: 60
- False activation count: 12
- False activation rate: 0.2
- Strong hard negative weight: 1.0