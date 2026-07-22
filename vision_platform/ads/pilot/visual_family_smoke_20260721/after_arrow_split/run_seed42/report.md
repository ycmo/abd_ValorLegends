# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 1147 rows, 703 groups, {'x_mark': 146, 'arrow': 36, 'play_triangle': 138, 'next': 3, 'google_play': 5, 'free': 80, 'got': 156, 'negative': 583}
- val: 210 rows, 152 groups, {'x_mark': 18, 'google_play': 1, 'play_triangle': 23, 'next': 1, 'negative': 90, 'arrow': 11, 'got': 37, 'free': 29}
- test: 201 rows, 134 groups, {'google_play': 3, 'x_mark': 28, 'play_triangle': 22, 'arrow': 7, 'free': 4, 'negative': 103, 'got': 32, 'next': 2}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 28 | 0.6667 | 0.9286 | 0.7761 | 13 | 2 |
| play_triangle | 22 | 0.6897 | 0.9091 | 0.7843 | 9 | 2 |
| google_play | 3 | 0.1765 | 1.0 | 0.3 | 14 | 0 |
| next | 2 | 0.0667 | 0.5 | 0.1176 | 14 | 1 |
| free | 4 | 0.25 | 1.0 | 0.4 | 12 | 0 |
| got | 32 | 1.0 | 1.0 | 1.0 | 0 | 0 |
| arrow | 7 | 0.5 | 1.0 | 0.6667 | 7 | 0 |

## None-of-the-above Check

- Support: 103
- False activation count: 15
- False activation rate: 0.1456
- Strong hard negative weight: 1.0