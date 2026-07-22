# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 725 rows, 419 groups, {'x_mark': 95, 'google_play': 4, 'arrow': 64, 'next': 20, 'free': 63, 'play_triangle': 14, 'got': 103, 'negative': 385}
- val: 212 rows, 87 groups, {'google_play': 1, 'x_mark': 13, 'arrow': 10, 'next': 5, 'got': 22, 'free': 56, 'negative': 96, 'play_triangle': 13}
- test: 155 rows, 87 groups, {'x_mark': 14, 'arrow': 6, 'google_play': 4, 'free': 14, 'play_triangle': 18, 'got': 26, 'next': 1, 'negative': 73}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 14 | 0.625 | 0.7143 | 0.6667 | 6 | 4 |
| play_triangle | 18 | 0.5667 | 0.9444 | 0.7083 | 13 | 1 |
| google_play | 4 | 0.5 | 0.5 | 0.5 | 2 | 2 |
| next | 1 | 0.0 | 0.0 | 0.0 | 15 | 1 |
| free | 14 | 0.4483 | 0.9286 | 0.6047 | 16 | 1 |
| got | 26 | 0.9286 | 0.5 | 0.65 | 1 | 13 |
| arrow | 6 | 0.2083 | 0.8333 | 0.3333 | 19 | 1 |

## None-of-the-above Check

- Support: 73
- False activation count: 11
- False activation rate: 0.1507
- Strong hard negative weight: 1.0