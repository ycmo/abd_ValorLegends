from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
TRAIN_ROLES = {"action_target": "close", "non_action_target": "not_close"}


@dataclass
class ReviewRow:
    instance_id: str
    content_id: str
    original_path: str
    relative_path: str
    width: int
    height: int
    source_root: str
    asset_role: str
    image_scope: str
    vision_domain: str
    asset_type: str
    representation: str
    screen_state: str
    sample_role: str
    sub_role: str
    review_status: str
    note: str
    updated_at: str


@dataclass
class ImagePair:
    pair_id: str
    annotated: ReviewRow
    clean: ReviewRow
    reason: str


def connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def read_reviews(con: sqlite3.Connection) -> list[ReviewRow]:
    rows = con.execute(
        """
        SELECT
            r.instance_id,
            a.content_id,
            a.original_path,
            a.relative_path,
            COALESCE(a.width, 0) AS width,
            COALESCE(a.height, 0) AS height,
            COALESCE(a.source_root, '') AS source_root,
            COALESCE(a.asset_role, '') AS asset_role,
            COALESCE(a.image_scope, '') AS image_scope,
            r.vision_domain,
            r.asset_type,
            r.representation,
            r.screen_state,
            r.sample_role,
            r.sub_role,
            r.review_status,
            r.note,
            r.updated_at
        FROM image_reviews r
        JOIN assets a ON a.instance_id = r.instance_id
        ORDER BY r.updated_at DESC
        """
    ).fetchall()
    return [ReviewRow(**dict(row)) for row in rows]


def read_bboxes(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT b.*, a.relative_path, a.width, a.height, r.screen_state, r.vision_domain AS review_domain
        FROM bboxes b
        JOIN assets a ON a.instance_id = b.instance_id
        LEFT JOIN image_reviews r ON r.instance_id = b.instance_id
        ORDER BY b.instance_id, b.id
        """
    ).fetchall()


def add_suspect(suspects: list[dict[str, Any]], row: ReviewRow | sqlite3.Row, reason: str, check: str, extra: dict[str, Any] | None = None) -> None:
    if isinstance(row, ReviewRow):
        data = {
            "instance_id": row.instance_id,
            "content_id": row.content_id,
            "original_path": row.original_path,
            "relative_path": row.relative_path,
            "suspect_reason": reason,
            "current_annotation": f"domain={row.vision_domain}; asset_type={row.asset_type}; scope={row.image_scope}; repr={row.representation}; screen_state={row.screen_state}; sample_role={row.sample_role}; sub_role={row.sub_role}; status={row.review_status}",
            "suggested_check": check,
        }
    else:
        data = {
            "instance_id": row["instance_id"],
            "content_id": row["content_id"],
            "original_path": row["original_path"],
            "relative_path": row["relative_path"],
            "suspect_reason": reason,
            "current_annotation": f"bbox_id={row['id']}; bbox=({row['x']:.1f},{row['y']:.1f},{row['w']:.1f},{row['h']:.1f}); screen_state={row['screen_state']}; domain={row['review_domain']}",
            "suggested_check": check,
        }
    if extra:
        data.update(extra)
    suspects.append(data)


def is_crop_like(row: ReviewRow) -> bool:
    return row.asset_type in {"crop", "template"} or row.image_scope == "crop" or row.asset_role == "template"


def is_fullscreen_like(row: ReviewRow) -> bool:
    return row.image_scope == "fullscreen" or row.asset_type in {"clean_fullscreen", "annotated_fullscreen"}


def looks_annotated(row: ReviewRow) -> bool:
    path = row.relative_path.replace("\\", "/").lower()
    name = Path(path).name
    return (
        row.representation in {"annotated", "debug_overlay"}
        or "_edit" in name
        or "marked" in name
        or "annotated" in name
        or "debug_overlay" in name
    )


def looks_clean(row: ReviewRow) -> bool:
    path = row.relative_path.replace("\\", "/").lower()
    name = Path(path).name
    return (
        row.representation in {"raw", "unknown"}
        and "_edit" not in name
        and "marked" not in name
        and "annotated" not in name
        and "debug_overlay" not in name
        and "hits_debug" not in name
    )


def clean_pair_key(row: ReviewRow) -> str:
    path = row.relative_path.replace("\\", "/").lower()
    name = Path(path).stem
    parent = str(Path(path).parent)
    for token in ["_edit", "-edit", "_marked", "-marked", "_annotated", "-annotated", "_debug_overlay", "-debug_overlay"]:
        name = name.replace(token, "")
    for token in ["_original", "-original", "_clean", "-clean"]:
        name = name.replace(token, "")
    return f"{parent}/{name}_{row.width}x{row.height}"


def build_clean_pairs(rows: list[ReviewRow]) -> tuple[dict[str, ImagePair], dict[str, ImagePair]]:
    clean_by_key: dict[str, ReviewRow] = {}
    for row in rows:
        if looks_clean(row):
            key = clean_pair_key(row)
            if key not in clean_by_key or "_original" in row.relative_path.lower():
                clean_by_key[key] = row

    annotated_to_pair: dict[str, ImagePair] = {}
    clean_to_pair: dict[str, ImagePair] = {}
    for row in rows:
        if not looks_annotated(row):
            continue
        clean = clean_by_key.get(clean_pair_key(row))
        if clean is None or clean.instance_id == row.instance_id:
            continue
        pair_id = f"pair_{row.content_id}_{clean.content_id}"
        pair = ImagePair(pair_id=pair_id, annotated=row, clean=clean, reason="filename_clean_pair")
        annotated_to_pair[row.instance_id] = pair
        clean_to_pair[clean.instance_id] = pair
    return annotated_to_pair, clean_to_pair


def image_open(path: str) -> Image.Image | None:
    try:
        return Image.open(path).convert("RGB")
    except Exception:
        return None


def red_ratio(image: Image.Image) -> float:
    arr = np.asarray(image.convert("RGB"))
    if arr.size == 0:
        return 0.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    red = (r > 180) & (g < 110) & (b < 110) & ((r.astype(np.int16) - np.maximum(g, b).astype(np.int16)) > 70)
    return float(red.mean())


def crop_bbox(image: Image.Image, bbox: sqlite3.Row, pad: int = 8) -> Image.Image:
    x, y, w, h = float(bbox["x"]), float(bbox["y"]), float(bbox["w"]), float(bbox["h"])
    left = max(0, int(math.floor(x - pad)))
    top = max(0, int(math.floor(y - pad)))
    right = min(image.width, int(math.ceil(x + w + pad)))
    bottom = min(image.height, int(math.ceil(y + h + pad)))
    if right <= left or bottom <= top:
        return Image.new("RGB", (1, 1), (0, 0, 0))
    return image.crop((left, top, right, bottom))


def canonical_object(image: Image.Image, output_size: int = 96, object_ratio: float = 0.70) -> Image.Image:
    image = image.convert("RGB")
    target_max = max(1, round(output_size * object_ratio))
    scale = target_max / max(image.width, image.height, 1)
    new_w = max(1, round(image.width * scale))
    new_h = max(1, round(image.height * scale))
    resized = image.resize((new_w, new_h), Image.Resampling.BILINEAR)
    canvas = Image.new("RGB", (output_size, output_size), (0, 0, 0))
    canvas.paste(resized, ((output_size - new_w) // 2, (output_size - new_h) // 2))
    return canvas


def draw_contact_sheet(items: list[dict[str, Any]], output: Path, title: str, max_items: int = 80) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    items = items[:max_items]
    cols, thumb, label_h, pad = 5, 180, 54, 10
    rows = max(1, (len(items) + cols - 1) // cols)
    sheet = Image.new("RGB", (cols * (thumb + pad) + pad, rows * (thumb + label_h + pad) + pad + 26), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    draw.text((pad, 6), title, fill=(20, 20, 20), font=font)
    for i, item in enumerate(items):
        x = pad + (i % cols) * (thumb + pad)
        y = pad + 26 + (i // cols) * (thumb + label_h + pad)
        image = image_open(item.get("preview_path") or item.get("original_path", ""))
        if image is None:
            continue
        image.thumbnail((thumb, thumb), Image.Resampling.LANCZOS)
        sheet.paste(image, (x, y))
        draw.rectangle([x, y, x + thumb - 1, y + thumb - 1], outline=(200, 60, 60), width=2)
        text = str(item.get("label") or item.get("suspect_reason") or "")[:28]
        draw.text((x, y + thumb + 3), text, fill=(20, 20, 20), font=font)
        draw.text((x, y + thumb + 17), Path(item.get("relative_path", "")).name[:28], fill=(20, 20, 20), font=font)
        draw.text((x, y + thumb + 31), str(item.get("score", ""))[:28], fill=(80, 80, 80), font=font)
    sheet.save(output)


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        keys = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
        fieldnames = keys or ["empty"]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def simple_embedding(image: Image.Image) -> np.ndarray:
    image = canonical_object(image, 64, 0.78).resize((32, 32), Image.Resampling.BILINEAR).convert("L")
    arr = np.asarray(image, dtype=np.float32).reshape(-1) / 255.0
    arr = arr - arr.mean()
    norm = np.linalg.norm(arr) + 1e-8
    return arr / norm


def compute_embeddings(samples: list[ReviewRow]) -> tuple[np.ndarray, list[ReviewRow]]:
    vectors, kept = [], []
    for row in samples:
        image = image_open(row.original_path)
        if image is None:
            continue
        vectors.append(simple_embedding(image))
        kept.append(row)
    if not vectors:
        return np.zeros((0, 1), dtype=np.float32), []
    return np.stack(vectors).astype(np.float32), kept


def visual_consistency(samples: list[ReviewRow], audit_dir: Path) -> dict[str, Any]:
    vectors, kept = compute_embeddings(samples)
    if len(kept) < 3:
        return {"sample_count": len(kept), "outliers": 0, "contradict_pairs": 0}
    labels = [row.sample_role for row in kept]
    outliers: list[dict[str, Any]] = []
    for label in sorted(set(labels)):
        idxs = [i for i, lab in enumerate(labels) if lab == label]
        if len(idxs) < 3:
            continue
        centroid = vectors[idxs].mean(axis=0)
        centroid = centroid / (np.linalg.norm(centroid) + 1e-8)
        dists = [(1 - float(vectors[i] @ centroid), i) for i in idxs]
        for dist, i in sorted(dists, reverse=True)[:10]:
            row = kept[i]
            outliers.append({
                "instance_id": row.instance_id,
                "content_id": row.content_id,
                "original_path": row.original_path,
                "relative_path": row.relative_path,
                "sample_role": row.sample_role,
                "score": f"dist_to_label_centroid={dist:.3f}",
                "label": f"outlier:{row.sample_role}",
            })
    pairs: list[dict[str, Any]] = []
    sim = vectors @ vectors.T
    for i, row in enumerate(kept):
        order = np.argsort(-sim[i])
        for j in order[1:8]:
            other = kept[int(j)]
            if row.content_id == other.content_id:
                continue
            if row.sample_role != other.sample_role and {row.sample_role, other.sample_role} <= {"action_target", "non_action_target"}:
                pairs.append({
                    "instance_id": row.instance_id,
                    "content_id": row.content_id,
                    "original_path": row.original_path,
                    "relative_path": row.relative_path,
                    "sample_role": row.sample_role,
                    "neighbor_instance_id": other.instance_id,
                    "neighbor_path": other.relative_path,
                    "neighbor_sample_role": other.sample_role,
                    "score": f"cosine={float(sim[i, int(j)]):.3f}",
                    "label": f"{row.sample_role} vs {other.sample_role}",
                })
                break
    pairs = sorted(pairs, key=lambda x: x["score"], reverse=True)[:40]
    write_csv(audit_dir / "visual_outliers.csv", outliers)
    write_csv(audit_dir / "visual_contradict_pairs.csv", pairs)
    draw_contact_sheet(outliers, audit_dir / "contact_sheets" / "visual_outliers.png", "Visual outliers")
    draw_contact_sheet(pairs, audit_dir / "contact_sheets" / "visual_contradict_pairs.png", "Similar but opposite labels")
    return {"sample_count": len(kept), "outliers": len(outliers), "contradict_pairs": len(pairs)}


def source_session(row: ReviewRow) -> str:
    parts = Path(row.relative_path).parts
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return row.content_id


def clean_training_source(row: ReviewRow, annotated_to_pair: dict[str, ImagePair]) -> tuple[ReviewRow, str, str, str]:
    pair = annotated_to_pair.get(row.instance_id)
    if pair is not None:
        return pair.clean, pair.pair_id, row.instance_id, pair.clean.instance_id
    return row, "", "", row.instance_id


def build_pilot_manifest(rows: list[ReviewRow], pilot_dir: Path, annotated_to_pair: dict[str, ImagePair]) -> dict[str, Any]:
    dataset_dir = pilot_dir / "action_classifier_dataset"
    image_dir = dataset_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict[str, Any]] = []
    seen_group: set[str] = set()
    annotated_export_count = 0
    for row in rows:
        if row.review_status != "reviewed" or row.vision_domain not in {"ads", "shared"}:
            continue
        if not is_crop_like(row) or row.sample_role not in TRAIN_ROLES:
            continue
        if row.representation in {"edge_glyph", "binary_mask", "debug_overlay", "annotated"}:
            continue
        source_row, pair_id, annotated_instance_id, clean_instance_id = clean_training_source(row, annotated_to_pair)
        group_id = pair_id or source_row.content_id
        if group_id in seen_group:
            continue
        if looks_annotated(source_row):
            annotated_export_count += 1
        image = image_open(source_row.original_path)
        if image is None:
            continue
        seen_group.add(group_id)
        label = TRAIN_ROLES[row.sample_role]
        out = image_dir / f"ads_action_{len(manifest_rows)+1:05d}_{label}.png"
        canonical_object(image).save(out)
        manifest_rows.append({
            "image_path": str(out.resolve()),
            "label": label,
            "review_status": "reviewed",
            "source_screen": source_row.original_path,
            "source_session": group_id,
            "ad_source": row.source_root or "unknown_source",
            "icon_family": row.sub_role or row.asset_role or "unknown_family",
            "reject_type": "",
            "candidate_score": "",
            "geometry_score": "",
            "bbox": "",
            "split": "",
            "instance_id": row.instance_id,
            "content_id": row.content_id,
            "training_instance_id": source_row.instance_id,
            "training_content_id": source_row.content_id,
            "annotated_instance_id": annotated_instance_id,
            "clean_instance_id": clean_instance_id,
            "pair_id": pair_id,
            "sample_role": row.sample_role,
            "representation": source_row.representation,
            "relative_path": row.relative_path,
            "training_relative_path": source_row.relative_path,
        })
    write_csv(dataset_dir / "manifest.csv", manifest_rows)
    draw_contact_sheet(
        [{"original_path": r["image_path"], "relative_path": r["relative_path"], "label": r["label"]} for r in manifest_rows],
        dataset_dir / "contact_sheet.png",
        "Ads action classifier dataset",
        max_items=160,
    )
    return {
        "manifest": str((dataset_dir / "manifest.csv").resolve()),
        "counts": dict(Counter(r["label"] for r in manifest_rows)),
        "rows": len(manifest_rows),
        "annotated_images_exported_into_training": annotated_export_count,
    }


def audit(args: argparse.Namespace) -> None:
    audit_dir = args.audit_dir
    pilot_dir = args.pilot_dir
    contact_dir = audit_dir / "contact_sheets"
    audit_dir.mkdir(parents=True, exist_ok=True)
    contact_dir.mkdir(parents=True, exist_ok=True)
    pilot_dir.mkdir(parents=True, exist_ok=True)
    con = connect(args.db)
    reviews = read_reviews(con)
    bboxes = read_bboxes(con)
    reviewed = [r for r in reviews if r.review_status == "reviewed"]
    row_by_instance = {row.instance_id: row for row in reviews}
    annotated_to_pair, _clean_to_pair = build_clean_pairs(reviews)
    suspects: list[dict[str, Any]] = []
    bbox_clean_pairs: list[dict[str, Any]] = []
    red_frame_without_clean_pairs: list[dict[str, Any]] = []

    bbox_by_instance = defaultdict(list)
    for box in bboxes:
        bbox_by_instance[box["instance_id"]].append(box)

    for row in reviewed:
        boxes = bbox_by_instance.get(row.instance_id, [])
        if not row.vision_domain or row.vision_domain == "unknown":
            add_suspect(suspects, row, "missing_or_unknown_domain", "確認 domain 是否 ads/game/shared")
        if is_fullscreen_like(row) and row.screen_state == "actionable" and not boxes:
            add_suspect(suspects, row, "fullscreen_actionable_without_bbox", "actionable 畫面應至少有一個 bbox")
        if is_fullscreen_like(row) and row.screen_state in {"waiting", "returned_to_game"} and boxes:
            add_suspect(suspects, row, "non_actionable_screen_has_bbox", "waiting/returned_to_game 通常不應保留 bbox")
        if is_crop_like(row) and row.sample_role in {"", "uncertain"}:
            add_suspect(suspects, row, "crop_template_uncertain_sample_role", "確認 crop/template 的 sample_role")
        if is_crop_like(row) and row.screen_state != "uncertain":
            add_suspect(suspects, row, "crop_template_has_screen_state", "crop/template 不應使用 fullscreen screen_state")
        if row.representation in {"annotated", "debug_overlay"} and row.sample_role == "action_target":
            add_suspect(suspects, row, "annotated_debug_as_action_target", "避免把人工標記/overlay 當 runtime action sample")
        if row.vision_domain in {"ads", "shared"} and is_crop_like(row) and row.sample_role in TRAIN_ROLES and looks_annotated(row) and row.instance_id not in annotated_to_pair:
            add_suspect(suspects, row, "annotated_training_source_without_clean_pair", "這張可能是人工標記版本，且找不到 clean pair；不應直接進 training")
        if row.representation in {"edge_glyph", "binary_mask", "grayscale"} and row.sample_role == "action_target":
            add_suspect(suspects, row, "reference_asset_as_action_target", "edge/mask/glyph 通常應為 reference_only")

    by_content = defaultdict(list)
    for row in reviewed:
        by_content[row.content_id].append(row)
    for content_id, group in by_content.items():
        binary_roles = {r.sample_role for r in group if r.sample_role in {"action_target", "non_action_target"}}
        if {"action_target", "non_action_target"} <= binary_roles:
            for row in group:
                if row.sample_role in {"action_target", "non_action_target"}:
                    add_suspect(
                        suspects,
                        row,
                        "duplicate_content_action_non_action_conflict",
                        "Same content_id has both action_target and non_action_target. This must be corrected.",
                        {"group_size": len(group)},
                    )

    for box in bboxes:
        width, height = float(box["width"] or 0), float(box["height"] or 0)
        x, y, w, h = float(box["x"]), float(box["y"]), float(box["w"]), float(box["h"])
        area = max(width * height, 1.0)
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width + 1 or y + h > height + 1:
            add_suspect(suspects, box, "bbox_out_of_bounds_or_invalid", "檢查 bbox 座標是否超出圖片")
        ratio = (w * h) / area
        if w < 6 or h < 6:
            add_suspect(suspects, box, "bbox_too_small", "確認 bbox 是否小到不適合作為 detector target")
        if ratio > 0.55:
            add_suspect(suspects, box, "bbox_too_large", "確認是否框到接近整張圖")
        img = image_open(box["original_path"])
        if img is not None:
            rr = red_ratio(crop_bbox(img, box))
            if rr > 0.003:
                pair = annotated_to_pair.get(box["instance_id"])
                if pair is not None:
                    bbox_clean_pairs.append({
                        "pair_id": pair.pair_id,
                        "bbox_id": box["id"],
                        "annotated_instance_id": pair.annotated.instance_id,
                        "clean_instance_id": pair.clean.instance_id,
                        "annotated_content_id": pair.annotated.content_id,
                        "clean_content_id": pair.clean.content_id,
                        "annotated_path": pair.annotated.relative_path,
                        "clean_path": pair.clean.relative_path,
                        "x": box["x"],
                        "y": box["y"],
                        "w": box["w"],
                        "h": box["h"],
                        "red_ratio": f"{rr:.5f}",
                        "pair_reason": pair.reason,
                    })
                else:
                    red_frame_without_clean_pairs.append({
                        "bbox_id": box["id"],
                        "instance_id": box["instance_id"],
                        "content_id": box["content_id"],
                        "original_path": box["original_path"],
                        "relative_path": box["relative_path"],
                        "x": box["x"],
                        "y": box["y"],
                        "w": box["w"],
                        "h": box["h"],
                        "red_ratio": f"{rr:.5f}",
                    })

    dist_tables = {
        "domain": Counter(r.vision_domain for r in reviewed),
        "image_scope": Counter(r.image_scope for r in reviewed),
        "representation": Counter(r.representation for r in reviewed),
        "screen_state": Counter(r.screen_state for r in reviewed),
        "sample_role": Counter(r.sample_role for r in reviewed),
        "sub_role": Counter(r.sub_role or "(blank)" for r in reviewed),
        "review_status": Counter(r.review_status for r in reviews),
    }

    visual_samples = [r for r in reviewed if is_crop_like(r) and r.sample_role in {"action_target", "non_action_target", "reference_only"}]
    visual_summary = visual_consistency(visual_samples, audit_dir)
    pilot_summary = build_pilot_manifest(reviews, pilot_dir, annotated_to_pair)
    red_frame_without_clean_pair = len(red_frame_without_clean_pairs)
    red_frame_with_clean_pair = len(bbox_clean_pairs)

    write_csv(audit_dir / "suspect_annotations.csv", suspects)
    write_csv(audit_dir / "bbox_clean_pairs.csv", bbox_clean_pairs)
    write_csv(audit_dir / "red_frame_bbox_without_clean_pair.csv", red_frame_without_clean_pairs)
    draw_contact_sheet(suspects, contact_dir / "suspects_top80.png", "Top suspect annotations", max_items=80)

    bbox_count_by_state = Counter()
    for box in bboxes:
        bbox_count_by_state[box["screen_state"] or "unknown"] += 1

    gui_md = [
        "# GUI Usage Analysis",
        "",
        f"- Reviewed images: {len(reviewed)}",
        f"- BBoxes: {len(bboxes)}",
        f"- Postponed images: {sum(1 for r in reviews if r.review_status == 'postponed')}",
        f"- Uncertain sample_role: {dist_tables['sample_role'].get('uncertain', 0)}",
        f"- Notes used: {sum(1 for r in reviewed if r.note.strip())}",
        "",
        "## Option Usage",
    ]
    for name, counter in dist_tables.items():
        gui_md.append(f"### {name}")
        for key, value in counter.most_common():
            gui_md.append(f"- {key}: {value}")
        gui_md.append("")
    gui_md.extend([
        "## Observations",
        "- `sample_role=uncertain` and `screen_state=uncertain` are the highest-friction states to review first.",
        "- `reference_only` is rarely used; templates/glyphs marked action_target should be reviewed before training.",
        "- Add GUI filters for suspect reason, model disagreement, red annotation risk, and duplicate-content conflicts.",
        "- Add save-time warnings for actionable fullscreen without bbox, non-actionable screen with bbox, and crop/template uncertain role.",
    ])
    (audit_dir / "gui_usage_analysis.md").write_text("\n".join(gui_md), encoding="utf-8")

    md = [
        "# Ads Annotation Audit",
        "",
        f"- Database: `{args.db}`",
        f"- Total image_reviews: {len(reviews)}",
        f"- Reviewed images: {len(reviewed)}",
        f"- BBoxes: {len(bboxes)}",
        f"- Suspect rows: {len(suspects)}",
        f"- Visual samples embedded: {visual_summary['sample_count']}",
        f"- Visual outliers: {visual_summary['outliers']}",
        f"- Similar opposite-label pairs: {visual_summary['contradict_pairs']}",
        f"- Pilot classifier dataset: {pilot_summary['rows']} rows, {pilot_summary['counts']}",
        f"- Red-frame bbox with clean pair: {red_frame_with_clean_pair}",
        f"- Red-frame bbox without clean pair: {red_frame_without_clean_pair}",
        f"- Annotated images currently exported into training: {pilot_summary['annotated_images_exported_into_training']}",
        "",
        "## Distributions",
    ]
    for name, counter in dist_tables.items():
        md.append(f"### {name}")
        for key, value in counter.most_common():
            pct = value / max(len(reviewed), 1) * 100 if name != "review_status" else value / max(len(reviews), 1) * 100
            md.append(f"- {key}: {value} ({pct:.1f}%)")
        md.append("")
    md.extend([
        "## Detector Readiness",
        f"- Fullscreen reviewed: {sum(1 for r in reviewed if is_fullscreen_like(r))}",
        f"- BBoxes available: {len(bboxes)}",
        "- Detector training is not recommended until bbox positives cover more sessions and non-action screen negatives are explicitly balanced.",
        "",
        "## Outputs",
        f"- Suspects: `{audit_dir / 'suspect_annotations.csv'}`",
        f"- Contact sheets: `{contact_dir}`",
        f"- Visual outliers CSV: `{audit_dir / 'visual_outliers.csv'}`",
        f"- Visual contradictory pairs CSV: `{audit_dir / 'visual_contradict_pairs.csv'}`",
        f"- Pilot manifest: `{pilot_summary['manifest']}`",
        f"- BBox clean pairs: `{audit_dir / 'bbox_clean_pairs.csv'}`",
    ])
    (audit_dir / "annotation_audit.md").write_text("\n".join(md), encoding="utf-8")

    summary = {
        "review_count": len(reviews),
        "reviewed_count": len(reviewed),
        "bbox_count": len(bboxes),
        "suspect_count": len(suspects),
        "distributions": {k: dict(v) for k, v in dist_tables.items()},
        "visual_summary": visual_summary,
        "pilot_summary": pilot_summary,
        "red_frame_bbox_with_clean_pair": red_frame_with_clean_pair,
        "red_frame_bbox_without_clean_pair": red_frame_without_clean_pair,
        "annotated_images_currently_exported_into_training": pilot_summary["annotated_images_exported_into_training"],
    }
    (audit_dir / "audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    con.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("vision_platform/vision_assets/review/vision_review.db"))
    parser.add_argument("--audit-dir", type=Path, default=Path("vision_platform/ads/audit"))
    parser.add_argument("--pilot-dir", type=Path, default=Path("vision_platform/ads/pilot"))
    args = parser.parse_args()
    audit(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
