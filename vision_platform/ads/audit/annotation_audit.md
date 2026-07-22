# Ads Annotation Audit

- Database: `vision_platform\vision_assets\review\vision_review.db`
- Total image_reviews: 1075
- Reviewed images: 1074
- BBoxes: 246
- Suspect rows: 24
- Visual samples embedded: 875
- Visual outliers: 30
- Similar opposite-label pairs: 40
- Pilot classifier dataset: 797 rows, {'close': 119, 'not_close': 678}
- Red-frame bbox with clean pair: 33
- Red-frame bbox without clean pair: 95
- Annotated images currently exported into training: 2

## Distributions
### domain
- ads: 918 (85.5%)
- shared: 99 (9.2%)
- game: 35 (3.3%)
- unknown: 22 (2.0%)

### image_scope
- crop: 869 (80.9%)
- fullscreen: 177 (16.5%)
- unknown: 24 (2.2%)
- sheet_or_composite: 4 (0.4%)

### representation
- raw: 1070 (99.6%)
- edge_glyph: 3 (0.3%)
- unknown: 1 (0.1%)

### screen_state
- uncertain: 881 (82.0%)
- actionable: 169 (15.7%)
- returned_to_game: 16 (1.5%)
- waiting: 8 (0.7%)

### sample_role
- non_action_target: 682 (63.5%)
- uncertain: 199 (18.5%)
- action_target: 164 (15.3%)
- reference_only: 29 (2.7%)

### sub_role
- (blank): 984 (91.6%)
- play: 38 (3.5%)
- got: 18 (1.7%)
- 主城: 8 (0.7%)
- free: 8 (0.7%)
- 王國事件: 3 (0.3%)
- 時間沙漏: 3 (0.3%)
- 禮物屋: 2 (0.2%)
- continue: 2 (0.2%)
- 確定: 2 (0.2%)
- 探寶鏟: 2 (0.2%)
- back: 1 (0.1%)
- 異界奇聞: 1 (0.1%)
- 王國金庫: 1 (0.1%)
- 免費: 1 (0.1%)

### review_status
- reviewed: 1074 (99.9%)
- pending: 1 (0.1%)

## Detector Readiness
- Fullscreen reviewed: 177
- BBoxes available: 246
- Detector training is not recommended until bbox positives cover more sessions and non-action screen negatives are explicitly balanced.

## Outputs
- Suspects: `vision_platform\ads\audit\suspect_annotations.csv`
- Contact sheets: `vision_platform\ads\audit\contact_sheets`
- Visual outliers CSV: `vision_platform\ads\audit\visual_outliers.csv`
- Visual contradictory pairs CSV: `vision_platform\ads\audit\visual_contradict_pairs.csv`
- Pilot manifest: `D:\Projects\adb_vl\vision_platform\ads\pilot\action_classifier_dataset\manifest.csv`
- BBox clean pairs: `vision_platform\ads\audit\bbox_clean_pairs.csv`

## Model POC Result

- Run: `vision_platform\ads\pilot\action_classifier_mobilenet_seed42`
- Test split: 159 samples
- Confusion @ 0.5: {'tp': 23, 'fp': 3, 'tn': 131, 'fn': 2}
- Precision/Recall/F1 @ 0.5: 0.885 / 0.920 / 0.902
- Threshold comparison:
  - 0.3: precision=0.821, recall=0.920, f1=0.868, tp/fp/tn/fn=23/5/129/2
  - 0.5: precision=0.885, recall=0.920, f1=0.902, tp/fp/tn/fn=23/3/131/2
  - 0.7: precision=0.880, recall=0.880, f1=0.880, tp/fp/tn/fn=22/3/131/3
- High-confidence model disagreements added to suspects: 5

## Suspect Reason Counts
- missing_or_unknown_domain: 22
- model_high_confidence_false_positive: 3
- annotated_training_source_without_clean_pair: 2
- model_high_confidence_false_negative: 2

## Priority Review Queue
- CSV: `vision_platform\ads\audit\top20_review_queue.csv`
