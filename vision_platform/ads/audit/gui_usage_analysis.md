# GUI Usage Analysis

- Reviewed images: 1074
- BBoxes: 246
- Postponed images: 0
- Uncertain sample_role: 199
- Notes used: 3

## Option Usage
### domain
- ads: 918
- shared: 99
- game: 35
- unknown: 22

### image_scope
- crop: 869
- fullscreen: 177
- unknown: 24
- sheet_or_composite: 4

### representation
- raw: 1070
- edge_glyph: 3
- unknown: 1

### screen_state
- uncertain: 881
- actionable: 169
- returned_to_game: 16
- waiting: 8

### sample_role
- non_action_target: 682
- uncertain: 199
- action_target: 164
- reference_only: 29

### sub_role
- (blank): 984
- play: 38
- got: 18
- 主城: 8
- free: 8
- 王國事件: 3
- 時間沙漏: 3
- 禮物屋: 2
- continue: 2
- 確定: 2
- 探寶鏟: 2
- back: 1
- 異界奇聞: 1
- 王國金庫: 1
- 免費: 1

### review_status
- reviewed: 1074
- pending: 1

## Observations
- `sample_role=uncertain` and `screen_state=uncertain` are the highest-friction states to review first.
- `reference_only` is rarely used; templates/glyphs marked action_target should be reviewed before training.
- Add GUI filters for suspect reason, model disagreement, red annotation risk, and duplicate-content conflicts.
- Add save-time warnings for actionable fullscreen without bbox, non-actionable screen with bbox, and crop/template uncertain role.