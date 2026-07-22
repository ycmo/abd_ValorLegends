# Label Guide

Use folder-based review.

1. Open `review/pending/` in Windows File Explorer.
2. Use large icons.
3. Move each image into `review/close/`, `review/not_close/`, or `review/uncertain/`.
4. Run `sync_labels_from_folders.py` to update `review_manifest.csv`.

Allowed labels:
- `close`
- `not_close`
- `uncertain`

`pending` means not reviewed yet.
`uncertain` means a human reviewed it but cannot reliably decide.
pending != uncertain.

Allowed `reject_type` values for analysis only:
- `text_fragment`
- `decorative_x`
- `star_glint`
- `ui_crossing`
- `border_cross`
- `blob`
- `other`

Do not use `reject_type` as classifier label.
