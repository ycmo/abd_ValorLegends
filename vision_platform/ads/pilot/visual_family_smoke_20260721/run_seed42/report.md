# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 968 rows, 523 groups, {'google_play': 6, 'x_mark': 100, 'arrow': 69, 'next': 3, 'play_triangle': 109, 'free': 23, 'got': 101, 'negative': 557}
- val: 173 rows, 110 groups, {'x_mark': 16, 'next': 2, 'arrow': 16, 'google_play': 2, 'got': 26, 'negative': 84, 'play_triangle': 20, 'free': 7}
- test: 159 rows, 110 groups, {'google_play': 1, 'x_mark': 23, 'arrow': 18, 'free': 16, 'play_triangle': 2, 'got': 24, 'negative': 74, 'next': 1}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 23 | 0.68 | 0.7391 | 0.7083 | 8 | 6 |
| play_triangle | 2 | 0.3333 | 0.5 | 0.4 | 2 | 1 |
| google_play | 1 | 0.0 | 0.0 | 0.0 | 1 | 1 |
| next | 1 | 0.0 | 0.0 | 0.0 | 23 | 1 |
| free | 16 | 1.0 | 0.75 | 0.8571 | 0 | 4 |
| got | 24 | 1.0 | 1.0 | 1.0 | 0 | 0 |
| arrow | 18 | 0.4103 | 0.8889 | 0.5614 | 23 | 2 |

## None-of-the-above Check

- Support: 74
- False activation count: 8
- False activation rate: 0.1081
- Strong hard negative weight: 1.0