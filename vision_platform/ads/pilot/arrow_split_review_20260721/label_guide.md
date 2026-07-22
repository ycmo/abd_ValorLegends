# Arrow Split Review Guide

Goal: split the broad parent `arrow` label into visual subfamilies. The current training builder maps `arrow_*` labels back to the parent `arrow` head until we explicitly change the model taxonomy.

Use one label per image unless the crop truly contains two independent visual targets.

- `play_triangle`: a single play triangle, e.g. `▶`.
- `double_triangle`: two play triangles or skip mark, e.g. `▶▶`, `▶▶|`.
- `single_chevron`: a single chevron, e.g. `>` or `<`, without a play-triangle fill.
- `double_chevron`: two or more chevrons, e.g. `>>`, without readable text as the main crop.
- `double_chevron_text`: `>>` plus readable text, especially `>> Ad`.
- `back_arrow`: a normal back/left arrow, often boxed, e.g. `←`.
- `next_button`: readable `Next` pill/button. Use this only when the word `Next` is a first-class visual cue.
- `x_mark`: this crop is actually an X/close mark, not arrow.
- `negative`: clearly not an actionable visual family.
- `other`: valid-looking visual pattern, but not one of the above.
- `uncertain`: genuinely hard to decide.

Practical rule: `▶▶|` goes to `double_triangle`; `>> Ad` goes to `double_chevron_text`; readable `Next` goes to `next_button`.