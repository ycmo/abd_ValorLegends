# Vision Asset Inventory Summary

> `asset_id` is a legacy compatibility field. Prefer `instance_id` for a physical file path and `content_id` for identical image content.

- Scan time: `2026-07-23T08:41:12.887906+00:00`
- Total instances: `16720`
- Unique image contents: `12639`
- Total size: `3562536706` bytes
- Successful images: `16720`
- Scan errors: `0`
- Files in duplicate groups: `5678`
- Redundant copies: `4081`
- Duplicate groups: `1597`
- Reclaimable bytes: `220399306`
- Cross-source duplicate groups: `196`
- Cross-role duplicate groups: `185`

Duplicate images are not automatically safe to delete. The same content may be intentionally reused as a template, review asset, candidate crop, runtime evidence, or model artifact.

## Counts By Source Root

| Source root | Count |
|---|---:|
| `vision_platform\ads\runtime_collection` | 7553 |
| `log` | 3962 |
| `vision_platform\ads\collections` | 1680 |
| `vision_platform\ads\hard_negative_mining` | 976 |
| `ads2\assets\review_crops` | 562 |
| `close_x_classifier\data\review_batch_001` | 466 |
| `manual_screenshots` | 435 |
| `assets` | 242 |
| `ads2\assets\2_communication` | 240 |
| `close_x_classifier\data\stage0_6_canonical_object_poc` | 237 |
| `ads2\assets\1_templates` | 95 |
| `AwayFromKeyboard\route_screenshots` | 65 |
| `AwayFromKeyboard\debug` | 46 |
| `ads2\assets\3_reference_screens` | 41 |
| `switch_account\templates` | 29 |
| `arcane_forge\assets\manual` | 22 |
| `magic_shop\assets` | 19 |
| `AwayFromKeyboard\integration_task\templates` | 11 |
| `close_x_classifier\runtime_collection_dryrun_all` | 9 |
| `close_x_classifier\runtime_collection_dryrun_max3` | 8 |
| `close_x_classifier\runtime_collection_dryrun` | 6 |
| `close_x_classifier\runtime_collection_dryrun_2` | 6 |
| `close_x_classifier\runtime_collection_dryrun_abstain` | 5 |
| `close_x_classifier\runtime_collection_test_x` | 4 |
| `close_x_classifier\review` | 1 |

## Counts By Vision Domain

| Vision domain | Count |
|---|---:|
| `ads` | 11902 |
| `unknown` | 3989 |
| `game` | 829 |

## Counts By Asset Role

| Asset role | Count |
|---|---:|
| `runtime_collection` | 7591 |
| `runtime_log` | 3962 |
| `candidate_crop` | 3455 |
| `review_asset` | 707 |
| `manual_screenshot` | 457 |
| `template` | 396 |
| `reference_screen` | 106 |
| `debug_output` | 46 |

## Counts By Image Scope

| Image scope | Count |
|---|---:|
| `crop` | 9892 |
| `fullscreen` | 6751 |
| `unknown` | 63 |
| `sheet_or_composite` | 14 |

## Top 20 Directories

| Directory | Count | Size bytes |
|---|---:|---:|
| `log\20260707_160103_33324` | 791 | 438797789 |
| `vision_platform\ads\hard_negative_mining\batch_visual_negative_20260714\crops` | 558 | 2818447 |
| `log\20260710_125824_2204` | 496 | 275301119 |
| `ads2\assets\review_crops\close_glyph_candidates\sample\candidate_crops` | 484 | 8613605 |
| `log\20260723_085250_113628_afk_20260723_085229_tiger_每日任務_task` | 351 | 161131053 |
| `log\20260723_093710_94372_afk_20260723_093649_em3_每日任務_task` | 325 | 148227053 |
| `vision_platform\ads\collections\close_x_proposal_collection_pilot_20260720_latest30\raw_proposal_crops` | 275 | 241578 |
| `vision_platform\ads\collections\close_x_proposal_collection_pilot_20260720_latest30\crops\canonical_96` | 243 | 845738 |
| `vision_platform\ads\collections\close_x_proposal_collection_pilot_20260720_latest30\crops\context_1_5x` | 243 | 421685 |
| `vision_platform\ads\collections\close_x_proposal_collection_pilot_20260720_latest30\crops\raw_bbox` | 243 | 215566 |
| `ads2\assets\2_communication` | 240 | 89528090 |
| `close_x_classifier\data\stage0_6_canonical_object_poc\images` | 236 | 1075195 |
| `log\20260723_104307_12172_afk_20260723_102554_311_每日任務_task` | 225 | 101851556 |
| `close_x_classifier\data\review_batch_001\patches` | 224 | 1623151 |
| `vision_platform\ads\collections\reviewed_bbox_crops_20260718\context_1_5x` | 222 | 1919185 |
| `vision_platform\ads\collections\reviewed_bbox_crops_20260718\crops` | 222 | 960005 |
| `close_x_classifier\data\review_batch_001\review\not_close` | 218 | 1582611 |
| `vision_platform\ads\hard_negative_mining\batch_full_40\crops` | 179 | 803735 |
| `vision_platform\ads\hard_negative_mining\batch_quick_latest\crops` | 153 | 579747 |
| `log\20260723_102614_36328_afk_20260723_102554_311_每日任務_task_fail_returncode_1` | 142 | 60843472 |

## Suggested Next Priorities

1. Review `manual_screenshots/` and `ads2/assets/1_templates/` as curated human/template sources.
2. Review `ads2/assets/review_crops/` and `close_x_classifier/data/review_batch_001/` as candidate/review data.
3. Keep `log/` indexed only; do not copy it into review until a specific mining task needs it.
4. Use `vision_domain` to split future review batches into ads, game, and domain triage queues before any model-specific labeling.
