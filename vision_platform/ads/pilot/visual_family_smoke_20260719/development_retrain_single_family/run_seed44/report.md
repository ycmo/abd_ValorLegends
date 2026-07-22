# Ads Visual Family Smoke Test

Device: `cuda`

## Split Counts
- train: 729 rows, 419 groups, {'google_play': 7, 'x_mark': 73, 'arrow': 53, 'next': 2, 'free': 23, 'play_triangle': 63, 'got': 114, 'negative': 394}
- val: 191 rows, 87 groups, {'x_mark': 16, 'arrow': 14, 'next': 2, 'google_play': 1, 'free': 19, 'got': 17, 'play_triangle': 34, 'negative': 88}
- test: 172 rows, 87 groups, {'x_mark': 27, 'arrow': 13, 'google_play': 1, 'play_triangle': 34, 'got': 19, 'next': 2, 'negative': 72, 'free': 4}

## Test Metrics

| family | support | precision | recall | f1 | fp | fn |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x_mark | 27 | 0.7879 | 0.963 | 0.8667 | 7 | 1 |
| play_triangle | 34 | 0.8205 | 0.9412 | 0.8767 | 7 | 2 |
| google_play | 1 | 0.0 | 0.0 | 0.0 | 0 | 1 |
| next | 2 | 0.0 | 0.0 | 0.0 | 0 | 2 |
| free | 4 | 0.4 | 1.0 | 0.5714 | 6 | 0 |
| got | 19 | 1.0 | 0.4737 | 0.6429 | 0 | 10 |
| arrow | 13 | 0.3939 | 1.0 | 0.5652 | 20 | 0 |

## None-of-the-above Check

- Support: 72
- False activation count: 4
- False activation rate: 0.0556
- Strong hard negative weight: 1.0