# Close X Classifier

Offline experiment for a small close / not-close classifier on geometry candidates.

This does not modify runtime behavior. The intended pipeline is:

1. Geometry/template code proposes candidate crops.
2. This classifier scores candidate context patches.
3. Benchmark compares geometry-only, classifier-only, and geometry + classifier ranking.

## Data

Manifest columns:

- `image_path`
- `label`: `close`, `not_close`, `uncertain`, or blank
- `review_status`: `pending` or `reviewed`
- `source_screen`
- `source_session`
- `ad_source`
- `icon_family`
- `reject_type`
- `candidate_score`
- `geometry_score`
- optional `split`: `train`, `val`, or `test`

Main benchmark splits are source-session based. The same `source_session` must never appear in more than one split.

## Quick Start

Build a starter manifest from the current sample folders:

```powershell
.\.venv-codex\Scripts\python.exe .\close_x_classifier\build_manifest_from_sample.py
```

Train head-only MobileNetV3-small:

```powershell
.\.venv-codex\Scripts\python.exe .\close_x_classifier\train.py --manifest .\close_x_classifier\data\manifest.csv --output-dir .\close_x_classifier\runs\baseline_head
```

## Candidate Dataset Pipeline

Export runtime-shaped candidate context patches from a geometry `scan_report.md`:

```powershell
.\.venv-codex\Scripts\python.exe .\close_x_classifier\export_candidates_from_scan.py --scan-report .\ads2\assets\review_crops\close_glyph_candidates\sample_candidate_twostroke_filtered_v3\scan_report.md --output-dir .\close_x_classifier\data\review_batch_001
```

This creates:

- `patches/`: 96x96 RGB context patches
- `review/pending/`: files to manually label
- `review/close/`
- `review/not_close/`
- `review/uncertain/`
- `review_manifest.csv`: metadata source of truth
- `review_sheet.png`: quick visual review sheet
- `label_guide.md`

Folder labeling workflow:

Short path for new manual samples:

- `close_x_classifier/review/close/`
- `close_x_classifier/review/not_close/`
- `close_x_classifier/review/uncertain/`

The Stage 0 and Stage 0.6 builders read this short path automatically.

Batch review workflow:

1. Open `close_x_classifier/data/review_batch_001/review/pending/`.
2. Use Windows File Explorer large-icon view.
3. Move each image into `close/`, `not_close/`, or `uncertain/`.
4. Sync folder labels back to the manifest:

```powershell
.\.venv-codex\Scripts\python.exe .\close_x_classifier\sync_labels_from_folders.py --manifest .\close_x_classifier\data\review_batch_001\review_manifest.csv --review-dir .\close_x_classifier\data\review_batch_001\review
```

5. Create the source-session split:

```powershell
.\.venv-codex\Scripts\python.exe .\close_x_classifier\make_group_split.py --manifest .\close_x_classifier\data\review_batch_001\review_manifest.csv --output .\close_x_classifier\data\review_batch_001\manifest_split.csv
```

6. Train:

```powershell
.\.venv-codex\Scripts\python.exe .\close_x_classifier\train.py --manifest .\close_x_classifier\data\review_batch_001\manifest_split.csv --output-dir .\close_x_classifier\runs\review_batch_001_head
```

`pending` means not reviewed yet. `uncertain` means a human reviewed the candidate but cannot reliably decide.

`pending != uncertain`.

`pending`, blank labels, and `uncertain` are ignored by candidate-level training.

Analysis-only fields:

- `source_screen`
- `source_session`
- `icon_family`
- `reject_type`
- `geometry_score`

Suggested `reject_type` values:

- `text_fragment`
- `decorative_x`
- `star_glint`
- `ui_crossing`
- `border_cross`
- `blob`
- `other`

The split groups by `source_session` only. Do not use random crop splits.

## POC Data Target

Before drawing model-generalization conclusions, collect at least:

- positive: 200
- hard negative: 500
- source sessions: 20

Before that threshold, use runs only for pipeline validation.

## Benchmark Question

The first real question is:

Can MobileNet rank true close candidates above X-like hard negatives that geometry cannot reject?

The most important runtime-shaped metric is `per_screen_top1.csv`: for each source screen, among geometry fallback candidates, whether the classifier's top-ranked candidate is an acceptable close.

`per_screen_top1.csv` only includes complete screens. A complete screen is one where every candidate for that `source_screen` is labeled `close` or `not_close`. Screens containing pending, blank, or uncertain candidates are excluded and counted in `metrics.json`.

Outputs include:

- `best.pt`
- `predictions.csv`
- `metrics.json`
- `confusion_matrix.png`
- `pr_curve.png`
- `roc_curve.png`
- `per_session_metrics.csv`
- `per_screen_top1.csv`
- `false_positive_contact_sheet.png`
- `false_negative_contact_sheet.png`

## Notes

- Input patches are resized to `96x96` RGB.
- First stage freezes the MobileNetV3-small backbone and trains only the classifier head.
- Fine-tuning is intentionally not enabled by default. Only add it after head-only validation shows useful separation.
- Current sample data is tiny; use results as a smoke test, not proof of generalization.
