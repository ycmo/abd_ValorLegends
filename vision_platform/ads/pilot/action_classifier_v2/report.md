# Ads Action Classifier v2 Pilot

## Dataset

- Source: `vision_platform/vision_assets/review/vision_review.db`
- Builder: `vision_platform/ads/tools/build_action_classifier_dataset.py`
- Output: `vision_platform/ads/pilot/action_classifier_v2/dataset`
- Preprocessing: aspect-preserving canonical object crop, padded to `96x96`, object max side `70%`
- Included domains: `ads`, `shared`
- Included roles: `action_target -> close`, `non_action_target -> not_close`
- Excluded: `game`, `unknown`, `reference_only`, `uncertain`, non-crop images, edge glyphs, binary masks, debug overlays, annotated images

Counts:

| label | count |
| --- | ---: |
| close | 304 |
| not_close | 860 |
| total | 1164 |

Source counts:

| source | count |
| --- | ---: |
| `ads2/assets/1_templates` | 78 |
| `ads2/assets/2_communication` | 47 |
| `ads2/assets/review_crops` | 491 |
| `close_x_classifier/data/review_batch_001` | 174 |
| `close_x_classifier/data/stage0_6_canonical_object_poc` | 39 |
| `close_x_classifier/runtime_collection_dryrun` | 4 |
| `vision_platform/ads/runtime_collection` | 152 |
| `vision_platform/ads/hard_negative_mining` | 179 |

## Validation Runs

Model: existing MobileNetV3-small head-only trainer in `close_x_classifier/train.py`.

Threshold: `0.5`

| run | split sizes train/val/test | TP | FP | TN | FN | precision | recall | F1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| seed42 | 681 / 243 / 240 | 43 | 3 | 182 | 12 | 0.935 | 0.782 | 0.851 |
| seed43 | 710 / 234 / 220 | 57 | 6 | 150 | 7 | 0.905 | 0.891 | 0.898 |
| seed44 | 697 / 244 / 223 | 57 | 21 | 143 | 2 | 0.731 | 0.966 | 0.832 |

Interpretation:

- The classifier has a clear action/non-action signal.
- Seed-to-seed variance is still visible, especially FP/recall tradeoff.
- `0.5` is usable for exploration but should not be treated as calibrated.
- Runtime deployment should use a conservative resolver and continue logging fallback candidates.

## Pilot Deployment Checkpoint

All labeled rows were also fit into a non-production checkpoint:

`vision_platform/ads/pilot/action_classifier_v2/deployment_seed43/best.pt`

Training-set metrics only:

| TP | FP | TN | FN | precision | recall | FPR |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 304 | 2 | 858 | 0 | 0.993 | 1.000 | 0.0023 |

This checkpoint is for manual offline testing only until it is explicitly wired into runtime config.

## Detector Readiness

Current reviewed fullscreen detector data:

| group | screens | bboxes |
| --- | ---: | ---: |
| ads/actionable fullscreen | 91 | 91 |
| shared/actionable fullscreen | 47 | 54 |
| total actionable fullscreen | 138 | 145 |

This is enough for a detector smoke test or dataset export, but not enough to replace the current proposal sources. For now, keep template/glyph/geometry as proposal sources and use the classifier as the stronger second-stage filter.

## Outputs

- Dataset manifest: `vision_platform/ads/pilot/action_classifier_v2/dataset/manifest.csv`
- Dataset sheet: `vision_platform/ads/pilot/action_classifier_v2/dataset/contact_sheet.png`
- Summary metrics: `vision_platform/ads/pilot/action_classifier_v2/summary_metrics.csv`
- Repeated FP list: `vision_platform/ads/pilot/action_classifier_v2/repeated_false_positives.csv`
- Repeated FN list: `vision_platform/ads/pilot/action_classifier_v2/repeated_false_negatives.csv`
- Per-run reports/contact sheets:
  - `vision_platform/ads/pilot/action_classifier_v2/run_seed42`
  - `vision_platform/ads/pilot/action_classifier_v2/run_seed43`
  - `vision_platform/ads/pilot/action_classifier_v2/run_seed44`
