# Strong Hard Negative Weight Ablation

Only confirmed strong hard negatives are weighted. Labels, taxonomy, backbone, GUI, runtime, and detector are unchanged.

## Split Coverage Check

WARNING: All selected strong hard negatives are outside the training split for these runs.
The sample weights therefore had no effect; identical 1x/2x/3x metrics are expected.

## None-of-the-above

| weight | false activation avg | false activation worst | false activation count avg |
| ---: | ---: | ---: | ---: |
| 1.0 | 0.246 | 0.420 | 21.7 |
| 2.0 | 0.246 | 0.420 | 21.7 |
| 3.0 | 0.246 | 0.420 | 21.7 |

## Family Metrics Mean

| weight | family | precision | recall | recall loss vs 1x | f1 | fp | fn |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1.0 | arrow | 0.570 | 0.758 | 0.000 | 0.641 | 7.0 | 2.7 |
| 1.0 | free | 0.536 | 1.000 | 0.000 | 0.686 | 9.0 | 0.0 |
| 1.0 | google_play | 0.444 | 0.333 | 0.000 | 0.315 | 1.3 | 2.0 |
| 1.0 | got | 0.667 | 0.333 | 0.000 | 0.442 | 0.0 | 9.3 |
| 1.0 | next | 0.067 | 0.333 | 0.000 | 0.111 | 4.7 | 1.3 |
| 1.0 | play_triangle | 0.111 | 0.333 | 0.000 | 0.167 | 0.7 | 0.7 |
| 1.0 | x_mark | 0.414 | 0.727 | 0.000 | 0.470 | 22.0 | 3.0 |
| 2.0 | arrow | 0.570 | 0.758 | 0.000 | 0.641 | 7.0 | 2.7 |
| 2.0 | free | 0.536 | 1.000 | 0.000 | 0.686 | 9.0 | 0.0 |
| 2.0 | google_play | 0.444 | 0.333 | 0.000 | 0.315 | 1.3 | 2.0 |
| 2.0 | got | 0.667 | 0.333 | 0.000 | 0.442 | 0.0 | 9.3 |
| 2.0 | next | 0.067 | 0.333 | 0.000 | 0.111 | 4.7 | 1.3 |
| 2.0 | play_triangle | 0.111 | 0.333 | 0.000 | 0.167 | 0.7 | 0.7 |
| 2.0 | x_mark | 0.414 | 0.727 | 0.000 | 0.470 | 22.0 | 3.0 |
| 3.0 | arrow | 0.570 | 0.758 | 0.000 | 0.641 | 7.0 | 2.7 |
| 3.0 | free | 0.536 | 1.000 | 0.000 | 0.686 | 9.0 | 0.0 |
| 3.0 | google_play | 0.444 | 0.333 | 0.000 | 0.315 | 1.3 | 2.0 |
| 3.0 | got | 0.667 | 0.333 | 0.000 | 0.442 | 0.0 | 9.3 |
| 3.0 | next | 0.067 | 0.333 | 0.000 | 0.111 | 4.7 | 1.3 |
| 3.0 | play_triangle | 0.111 | 0.333 | 0.000 | 0.167 | 0.7 | 0.7 |
| 3.0 | x_mark | 0.414 | 0.727 | 0.000 | 0.470 | 22.0 | 3.0 |

## Family False Activation On None-of-the-above

| weight | family | activation rate avg | activation rate worst | count avg |
| ---: | --- | ---: | ---: | ---: |
| 1.0 | arrow | 0.034 | 0.102 | 3.0 |
| 1.0 | free | 0.072 | 0.102 | 6.3 |
| 1.0 | google_play | 0.015 | 0.045 | 1.3 |
| 1.0 | got | 0.000 | 0.000 | 0.0 |
| 1.0 | next | 0.000 | 0.000 | 0.0 |
| 1.0 | play_triangle | 0.000 | 0.000 | 0.0 |
| 1.0 | x_mark | 0.159 | 0.409 | 14.0 |
| 2.0 | arrow | 0.034 | 0.102 | 3.0 |
| 2.0 | free | 0.072 | 0.102 | 6.3 |
| 2.0 | google_play | 0.015 | 0.045 | 1.3 |
| 2.0 | got | 0.000 | 0.000 | 0.0 |
| 2.0 | next | 0.000 | 0.000 | 0.0 |
| 2.0 | play_triangle | 0.000 | 0.000 | 0.0 |
| 2.0 | x_mark | 0.159 | 0.409 | 14.0 |
| 3.0 | arrow | 0.034 | 0.102 | 3.0 |
| 3.0 | free | 0.072 | 0.102 | 6.3 |
| 3.0 | google_play | 0.015 | 0.045 | 1.3 |
| 3.0 | got | 0.000 | 0.000 | 0.0 |
| 3.0 | next | 0.000 | 0.000 | 0.0 |
| 3.0 | play_triangle | 0.000 | 0.000 | 0.0 |
| 3.0 | x_mark | 0.159 | 0.409 | 14.0 |