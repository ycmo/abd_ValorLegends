from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


TARGET_CLASS = "visual_candidate"
DEFAULT_DOMAINS = ("ads", "shared")
EXCLUDED_REPRESENTATIONS = {"annotated", "debug_overlay", "edge_glyph", "binary_mask"}
VISUAL_FAMILIES = {"x_mark", "play_triangle", "google_play", "next", "free", "got", "arrow"}
NON_POSITIVE_FAMILIES = {"negative", "other", "uncertain", ""}


@dataclass(frozen=True)
class BBox:
    x: float
    y: float
    w: float
    h: float


def open_db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def stable_hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def normalize_rel(path: str | Path, project_root: Path) -> str:
    try:
        rel = Path(path).resolve().relative_to(project_root.resolve())
    except Exception:
        rel = Path(path)
    return str(rel).replace("\\", "/").lower()


def normalize_creative_stem(path: str | Path) -> str:
    stem = Path(path).stem.lower()
    stem = re.sub(r"(_edit|_edited|_original|_orig)(?=$|[_-])", "", stem)
    stem = re.sub(r"([_-])copy([_-]?\d+)?$", "", stem)
    stem = re.sub(r"([_-])\d{6,}$", "", stem)
    stem = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    return stem or Path(path).stem.lower()


def split_group_for_screen(row: sqlite3.Row | dict[str, Any], project_root: Path, source_session: str = "") -> str:
    if source_session:
        return f"session:{source_session}"
    rel = row["relative_path"] if "relative_path" in row.keys() else normalize_rel(row.get("original_path", ""), project_root)
    source_root = row["source_root"] if "source_root" in row.keys() else ""
    creative = normalize_creative_stem(rel)
    return f"creative:{source_root}:{Path(rel).parent.as_posix()}:{creative}"


def reviewed_fullscreen_rows(con: sqlite3.Connection, domains: list[str], include_annotated: bool) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in domains)
    clauses = [
        "r.review_status = 'reviewed'",
        f"r.vision_domain IN ({placeholders})",
        "a.image_scope = 'fullscreen'",
    ]
    params: list[Any] = list(domains)
    if not include_annotated:
        placeholders_repr = ",".join("?" for _ in EXCLUDED_REPRESENTATIONS)
        clauses.append(f"COALESCE(r.representation, 'unknown') NOT IN ({placeholders_repr})")
        params.extend(sorted(EXCLUDED_REPRESENTATIONS))
    where = " AND ".join(clauses)
    return con.execute(
        f"""
        SELECT
            a.instance_id,
            a.content_id,
            a.original_path,
            a.relative_path,
            a.filename,
            a.width,
            a.height,
            COALESCE(a.source_root, '') AS source_root,
            r.vision_domain,
            r.asset_type,
            r.representation,
            r.screen_state,
            r.has_no_target,
            r.sample_role,
            r.sub_role
        FROM assets a
        JOIN image_reviews r ON r.instance_id = a.instance_id
        WHERE {where}
        ORDER BY a.relative_path COLLATE NOCASE
        """,
        params,
    ).fetchall()


def bboxes_for(con: sqlite3.Connection, instance_ids: list[str]) -> dict[str, list[sqlite3.Row]]:
    result: dict[str, list[sqlite3.Row]] = defaultdict(list)
    if not instance_ids:
        return result
    for start in range(0, len(instance_ids), 500):
        batch = instance_ids[start : start + 500]
        placeholders = ",".join("?" for _ in batch)
        rows = con.execute(
            f"""
            SELECT
                b.id AS bbox_id,
                b.instance_id,
                b.content_id,
                b.original_path,
                b.x,
                b.y,
                b.w,
                b.h,
                b.vision_domain AS bbox_domain,
                b.label,
                b.note,
                COALESCE(c.name, '') AS class_name
            FROM bboxes b
            LEFT JOIN classes c ON c.id = b.class_id
            WHERE b.instance_id IN ({placeholders})
            ORDER BY b.instance_id, b.id
            """,
            batch,
        ).fetchall()
        for row in rows:
            result[row["instance_id"]].append(row)
    return result


def valid_manual_bbox(box: sqlite3.Row, width: int, height: int) -> bool:
    if box["label"] != "positive":
        return False
    class_name = str(box["class_name"] or "")
    if class_name and class_name not in {"action_target", TARGET_CLASS}:
        return False
    try:
        x, y, w, h = float(box["x"]), float(box["y"]), float(box["w"]), float(box["h"])
    except Exception:
        return False
    if w <= 1 or h <= 1:
        return False
    return not (x >= width or y >= height or x + w <= 0 or y + h <= 0)


def clamp_bbox_values(x: Any, y: Any, w: Any, h: Any, width: int, height: int) -> BBox | None:
    try:
        xf, yf, wf, hf = float(x), float(y), float(w), float(h)
    except Exception:
        return None
    if wf <= 1 or hf <= 1 or width <= 0 or height <= 0:
        return None
    x1 = max(0.0, min(float(width - 1), xf))
    y1 = max(0.0, min(float(height - 1), yf))
    x2 = max(x1 + 1.0, min(float(width), xf + wf))
    y2 = max(y1 + 1.0, min(float(height), yf + hf))
    return BBox(x1, y1, x2 - x1, y2 - y1)


def bbox_key(parent_path: str, bbox: BBox) -> str:
    rounded = (round(bbox.x, 1), round(bbox.y, 1), round(bbox.w, 1), round(bbox.h, 1))
    return f"{str(Path(parent_path)).lower()}|{rounded}"


def copy_screen(source: Path, output_images: Path, screen_id: str) -> Path:
    suffix = source.suffix.lower() or ".png"
    dest = output_images / f"{screen_id}{suffix}"
    shutil.copy2(source, dest)
    return dest


def image_size(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as image:
            return image.size
    except Exception:
        return None


def parse_event_bbox(event: dict[str, Any]) -> Any:
    metadata = event.get("metadata") or {}
    detector_candidate = event.get("detector_training_candidate") or {}
    return detector_candidate.get("bbox") or metadata.get("bbox")


def event_paths(collection_root: Path, date: str, max_events: int) -> list[Path]:
    pattern = f"click_success_{date}_*" if date else "click_success_*"
    paths = sorted(path / "event.json" for path in collection_root.glob(pattern) if (path / "event.json").exists())
    if max_events > 0:
        return paths[:max_events]
    return paths


def families_from_text(value: str) -> set[str]:
    return {part for part in value.split("|") if part}


def load_traceable_crop_manifests(collections_root: Path) -> dict[str, dict[str, str]]:
    traceable: dict[str, dict[str, str]] = {}
    for manifest in sorted(collections_root.glob("reviewed_bbox_crops_*/manifest.csv")):
        for row in read_csv(manifest):
            for key in [row.get("crop_path", ""), row.get("context_crop_path", "")]:
                if key:
                    traceable[str(Path(key)).lower()] = row
    return traceable


def trace_from_click_success_crop(path: Path) -> dict[str, str] | None:
    parts = [part.lower() for part in path.parts]
    if "runtime_collection" not in parts or "click_success" not in parts:
        return None
    event_dir = path.parent.parent if path.parent.name.lower() == "crops" else path.parent
    event_json = event_dir / "event.json"
    if not event_json.exists():
        return None
    try:
        event = json.loads(event_json.read_text(encoding="utf-8"))
    except Exception:
        return None
    parent = event.get("pre_click_screenshot") or event.get("primary_review_image") or ""
    bbox_value = parse_event_bbox(event)
    try:
        x, y, w, h = [float(value) for value in bbox_value]
    except Exception:
        return None
    return {
        "parent_instance_id": "",
        "parent_content_id": "",
        "parent_path": str(parent),
        "bbox_id": "",
        "bbox": json.dumps([x, y, w, h], ensure_ascii=False),
        "bbox_x": f"{x:.3f}",
        "bbox_y": f"{y:.3f}",
        "bbox_w": f"{w:.3f}",
        "bbox_h": f"{h:.3f}",
    }


def visual_family_traceability(
    con: sqlite3.Connection,
    traceable_by_path: dict[str, dict[str, str]],
    domains: list[str],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    placeholders = ",".join("?" for _ in domains)
    rows = con.execute(
        f"""
        SELECT
            a.instance_id,
            a.content_id,
            a.original_path,
            a.relative_path,
            a.image_scope,
            a.vision_domain,
            COALESCE(r.representation, 'unknown') AS representation,
            COALESCE(v.families, '') AS families,
            v.review_status
        FROM visual_family_reviews v
        JOIN assets a ON a.instance_id = v.instance_id
        LEFT JOIN image_reviews r ON r.instance_id = a.instance_id
        WHERE v.review_status = 'reviewed'
          AND a.vision_domain IN ({placeholders})
          AND a.image_scope = 'crop'
        """,
        domains,
    ).fetchall()
    records: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for row in rows:
        families = families_from_text(row["families"])
        positive_families = sorted(families & VISUAL_FAMILIES)
        if not positive_families:
            counts["non_positive_or_unknown_crop"] += 1
            continue
        source = str(Path(row["original_path"])).lower()
        trace = traceable_by_path.get(source)
        if not trace:
            trace = trace_from_click_success_crop(Path(row["original_path"]))
        status = "traceable_parent_bbox" if trace else "untraceable_parent_bbox"
        counts[status] += 1
        records.append(
            {
                "instance_id": row["instance_id"],
                "content_id": row["content_id"],
                "original_path": row["original_path"],
                "relative_path": row["relative_path"],
                "vision_domain": row["vision_domain"],
                "families": "|".join(positive_families),
                "trace_status": status,
                "parent_instance_id": trace.get("parent_instance_id", "") if trace else "",
                "parent_content_id": trace.get("parent_content_id", "") if trace else "",
                "parent_path": trace.get("parent_path", "") if trace else "",
                "bbox_id": trace.get("bbox_id", "") if trace else "",
                "bbox": trace.get("bbox", "") if trace else "",
                "bbox_x": trace.get("bbox_x", "") if trace else "",
                "bbox_y": trace.get("bbox_y", "") if trace else "",
                "bbox_w": trace.get("bbox_w", "") if trace else "",
                "bbox_h": trace.get("bbox_h", "") if trace else "",
            }
        )
    return records, counts


def assign_splits(screen_rows: list[dict[str, Any]], seed: int, val_ratio: float, test_ratio: float) -> None:
    import random

    eligible_groups = sorted(
        {
            row["split_group"]
            for row in screen_rows
            if row["dataset_role"] == "manual_positive" and row["annotation_completeness"] == "partial_annotation"
        }
    )
    rng = random.Random(seed)
    rng.shuffle(eligible_groups)
    total = len(eligible_groups)
    test_n = max(1, round(total * test_ratio)) if total >= 3 and test_ratio > 0 else 0
    val_n = max(1, round(total * val_ratio)) if total >= 3 and val_ratio > 0 else 0
    test_groups = set(eligible_groups[:test_n])
    val_groups = set(eligible_groups[test_n : test_n + val_n])
    for row in screen_rows:
        if row["dataset_role"] == "weak_positive":
            row["split"] = "train"
        elif row["dataset_role"] == "verified_empty_negative":
            group = row["split_group"]
            row["split"] = "test" if group in test_groups else "val" if group in val_groups else "train"
        elif row["split_group"] in test_groups:
            row["split"] = "test"
        elif row["split_group"] in val_groups:
            row["split"] = "val"
        else:
            row["split"] = "train"


def draw_contact_sheet(
    rows: list[dict[str, Any]],
    output: Path,
    *,
    title: str,
    max_items: int = 80,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    items = rows[:max_items]
    cols, thumb_w, thumb_h, label_h, pad = 4, 240, 135, 54, 8
    rows_n = max(1, math.ceil(max(1, len(items)) / cols))
    sheet = Image.new("RGB", (cols * (thumb_w + pad) + pad, rows_n * (thumb_h + label_h + pad) + pad + 18), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    draw.text((pad, 4), title[:180], fill=(20, 20, 20), font=font)
    if not items:
        draw.text((pad, 30), "No items", fill=(90, 90, 90), font=font)
        sheet.save(output)
        return
    for index, row in enumerate(items):
        x0 = pad + (index % cols) * (thumb_w + pad)
        y0 = pad + 18 + (index // cols) * (thumb_h + label_h + pad)
        image_path = Path(row["image_path"])
        try:
            image = Image.open(image_path).convert("RGB")
            original_w, original_h = image.size
        except Exception:
            image = Image.new("RGB", (thumb_w, thumb_h), (80, 80, 80))
            original_w, original_h = image.size
        sx = thumb_w / max(original_w, 1)
        sy = thumb_h / max(original_h, 1)
        image = image.resize((thumb_w, thumb_h), Image.Resampling.BILINEAR)
        item_draw = ImageDraw.Draw(image)
        if row.get("bbox_x") not in {"", None}:
            bx = float(row["bbox_x"])
            by = float(row["bbox_y"])
            bw = float(row["bbox_w"])
            bh = float(row["bbox_h"])
            item_draw.rectangle((bx * sx, by * sy, (bx + bw) * sx, (by + bh) * sy), outline=(0, 230, 0), width=2)
        sheet.paste(image, (x0, y0))
        line1 = f"{row.get('screen_id','')} {row.get('dataset_role','')}"[:34]
        line2 = f"{row.get('annotation_completeness','')} {row.get('split','')}"[:34]
        line3 = f"{row.get('proposal_source','')} {row.get('template_name','')}"[:34]
        draw.text((x0, y0 + thumb_h + 2), line1, fill=(20, 20, 20), font=font)
        draw.text((x0, y0 + thumb_h + 18), line2, fill=(80, 80, 80), font=font)
        draw.text((x0, y0 + thumb_h + 36), line3, fill=(80, 80, 80), font=font)
    sheet.save(output)


def bbox_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    widths = [float(row["bbox_w"]) for row in rows if row.get("bbox_w") not in {"", None}]
    heights = [float(row["bbox_h"]) for row in rows if row.get("bbox_h") not in {"", None}]
    areas = [w * h for w, h in zip(widths, heights)]

    def stats(values: list[float]) -> dict[str, float]:
        if not values:
            return {"count": 0, "min": 0, "mean": 0, "max": 0}
        return {"count": len(values), "min": round(min(values), 3), "mean": round(sum(values) / len(values), 3), "max": round(max(values), 3)}

    return {"width": stats(widths), "height": stats(heights), "area": stats(areas)}


def build(args: argparse.Namespace) -> None:
    output_dir: Path = args.output_dir
    if output_dir.exists() and any(output_dir.iterdir()):
        if not args.overwrite:
            raise SystemExit(f"output dir exists and is not empty; pass --overwrite: {output_dir}")
        shutil.rmtree(output_dir)
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    project_root = args.project_root.resolve()
    con = open_db(args.db)
    fullscreens = reviewed_fullscreen_rows(con, args.domains, args.include_annotated)
    boxes_by_instance = bboxes_for(con, [row["instance_id"] for row in fullscreens])

    screen_rows: list[dict[str, Any]] = []
    annotation_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    copied_by_source: dict[str, dict[str, Any]] = {}
    bbox_keys_seen: set[str] = set()
    screen_seq = 0
    ann_seq = 0

    def ensure_screen(
        source: Path,
        *,
        original_path: str,
        relative_path: str,
        instance_id: str,
        content_id: str,
        width: int,
        height: int,
        vision_domain: str,
        legacy_screen_state: str,
        asset_type: str,
        representation: str,
        source_root: str,
        source_session: str,
        dataset_role: str,
        annotation_completeness: str,
        proposal_source: str = "",
        template_name: str = "",
        event_json: str = "",
        event_id: str = "",
        timestamp: str = "",
        screen_change_score: str = "",
    ) -> dict[str, Any]:
        nonlocal screen_seq
        key = str(source.resolve()).lower()
        if key in copied_by_source:
            row = copied_by_source[key]
            if row["dataset_role"] == "weak_positive" and dataset_role == "manual_positive":
                row["dataset_role"] = dataset_role
                row["annotation_completeness"] = annotation_completeness
            return row
        screen_seq += 1
        screen_id = f"vis_det_v2_{screen_seq:06d}"
        image_path = copy_screen(source, images_dir, screen_id)
        split_group = split_group_for_screen(
            {
                "relative_path": relative_path,
                "source_root": source_root,
                "original_path": original_path,
            },
            project_root,
            source_session,
        )
        row = {
            "screen_id": screen_id,
            "image_path": str(image_path),
            "original_path": original_path,
            "relative_path": relative_path,
            "instance_id": instance_id,
            "content_id": content_id,
            "vision_domain": vision_domain,
            "legacy_screen_state": legacy_screen_state,
            "asset_type": asset_type,
            "representation": representation,
            "source_root": source_root,
            "source_session": source_session,
            "width": width,
            "height": height,
            "dataset_role": dataset_role,
            "annotation_completeness": annotation_completeness,
            "proposal_source": proposal_source,
            "template_name": template_name,
            "event_json": event_json,
            "event_id": event_id,
            "timestamp": timestamp,
            "screen_change_score": screen_change_score,
            "positive_bbox_count": 0,
            "split_group": split_group,
            "split": "",
        }
        copied_by_source[key] = row
        screen_rows.append(row)
        return row

    for screen in fullscreens:
        width = int(screen["width"] or 0)
        height = int(screen["height"] or 0)
        source = Path(screen["original_path"])
        if width <= 0 or height <= 0:
            skipped["manual_invalid_dimensions"] += 1
            continue
        if not source.exists():
            skipped["manual_missing_file"] += 1
            continue
        raw_boxes = boxes_by_instance.get(screen["instance_id"], [])
        positives = [box for box in raw_boxes if valid_manual_bbox(box, width, height)]
        if positives:
            screen_row = ensure_screen(
                source,
                original_path=screen["original_path"],
                relative_path=screen["relative_path"],
                instance_id=screen["instance_id"],
                content_id=screen["content_id"],
                width=width,
                height=height,
                vision_domain=screen["vision_domain"],
                legacy_screen_state=screen["screen_state"],
                asset_type=screen["asset_type"],
                representation=screen["representation"],
                source_root=screen["source_root"],
                source_session="",
                dataset_role="manual_positive",
                annotation_completeness="partial_annotation",
            )
            for box in positives:
                bbox = clamp_bbox_values(box["x"], box["y"], box["w"], box["h"], width, height)
                if bbox is None:
                    skipped["manual_invalid_bbox"] += 1
                    continue
                key = bbox_key(screen["original_path"], bbox)
                if key in bbox_keys_seen:
                    skipped["duplicate_manual_bbox"] += 1
                    continue
                bbox_keys_seen.add(key)
                ann_seq += 1
                screen_row["positive_bbox_count"] = int(screen_row["positive_bbox_count"]) + 1
                annotation_rows.append(
                    {
                        "annotation_id": f"v2_ann_{ann_seq:06d}",
                        "screen_id": screen_row["screen_id"],
                        "image_path": screen_row["image_path"],
                        "original_path": screen_row["original_path"],
                        "instance_id": screen_row["instance_id"],
                        "content_id": screen_row["content_id"],
                        "bbox_id": box["bbox_id"],
                        "bbox_x": f"{bbox.x:.3f}",
                        "bbox_y": f"{bbox.y:.3f}",
                        "bbox_w": f"{bbox.w:.3f}",
                        "bbox_h": f"{bbox.h:.3f}",
                        "category": TARGET_CLASS,
                        "label_kind": "manual_positive",
                        "label_source": "manual_bbox",
                        "annotation_completeness": "partial_annotation",
                        "legacy_bbox_class": box["class_name"],
                        "legacy_bbox_label": box["label"],
                        "proposal_source": "",
                        "template_name": "",
                        "screen_change_score": "",
                        "split_group": screen_row["split_group"],
                        "split": "",
                    }
                )
        elif int(screen["has_no_target"] or 0) and screen["screen_state"] == "waiting":
            ensure_screen(
                source,
                original_path=screen["original_path"],
                relative_path=screen["relative_path"],
                instance_id=screen["instance_id"],
                content_id=screen["content_id"],
                width=width,
                height=height,
                vision_domain=screen["vision_domain"],
                legacy_screen_state=screen["screen_state"],
                asset_type=screen["asset_type"],
                representation=screen["representation"],
                source_root=screen["source_root"],
                source_session="",
                dataset_role="verified_empty_negative",
                annotation_completeness="complete_negative",
            )
        elif screen["screen_state"] in {"waiting", "returned_to_game"}:
            skipped[f"non_actionable_not_verified_empty_{screen['screen_state']}"] += 1
        elif screen["screen_state"] == "actionable":
            skipped["actionable_without_positive_bbox"] += 1

    for event_json in event_paths(args.click_success_root, args.click_success_date, args.max_click_success):
        try:
            event = json.loads(event_json.read_text(encoding="utf-8"))
        except Exception:
            skipped["weak_event_read_error"] += 1
            continue
        if not event.get("verified_success"):
            skipped["weak_not_verified_success"] += 1
            continue
        if float(event.get("screen_change_score") or 0.0) < args.min_screen_change:
            skipped["weak_screen_change_below_threshold"] += 1
            continue
        parent = Path(event.get("pre_click_screenshot") or event.get("primary_review_image") or "")
        if not parent.exists():
            skipped["weak_missing_parent_image"] += 1
            continue
        size = image_size(parent)
        if size is None:
            skipped["weak_image_read_error"] += 1
            continue
        width, height = size
        bbox_value = parse_event_bbox(event)
        try:
            x, y, w, h = bbox_value
        except Exception:
            skipped["weak_missing_bbox"] += 1
            continue
        bbox = clamp_bbox_values(x, y, w, h, width, height)
        if bbox is None:
            skipped["weak_invalid_bbox"] += 1
            continue
        parent_key = str(parent.resolve()).lower()
        existing_screen = copied_by_source.get(parent_key)
        if existing_screen and existing_screen.get("dataset_role") != "weak_positive":
            skipped["weak_parent_already_has_manual_evidence"] += 1
            continue
        key = bbox_key(str(parent), bbox)
        if key in bbox_keys_seen:
            skipped["duplicate_weak_bbox_existing_manual_or_weak"] += 1
            continue
        bbox_keys_seen.add(key)
        metadata = event.get("metadata") or {}
        source_session = event.get("source_session") or f"click_success:{event.get('event_id', event_json.parent.name)}"
        rel = normalize_rel(parent, project_root)
        screen_row = ensure_screen(
            parent,
            original_path=str(parent),
            relative_path=rel,
            instance_id="",
            content_id="",
            width=width,
            height=height,
            vision_domain="ads",
            legacy_screen_state="",
            asset_type="clean_fullscreen",
            representation="raw",
            source_root="vision_platform/ads/runtime_collection",
            source_session=source_session,
            dataset_role="weak_positive",
            annotation_completeness="weak_single_bbox",
            proposal_source=str(event.get("proposal_source") or ""),
            template_name=str(metadata.get("template_name") or ""),
            event_json=str(event_json),
            event_id=str(event.get("event_id") or event_json.parent.name),
            timestamp=str(event.get("timestamp") or ""),
            screen_change_score=str(event.get("screen_change_score") or ""),
        )
        ann_seq += 1
        screen_row["positive_bbox_count"] = int(screen_row["positive_bbox_count"]) + 1
        annotation_rows.append(
            {
                "annotation_id": f"v2_ann_{ann_seq:06d}",
                "screen_id": screen_row["screen_id"],
                "image_path": screen_row["image_path"],
                "original_path": screen_row["original_path"],
                "instance_id": "",
                "content_id": "",
                "bbox_id": "",
                "bbox_x": f"{bbox.x:.3f}",
                "bbox_y": f"{bbox.y:.3f}",
                "bbox_w": f"{bbox.w:.3f}",
                "bbox_h": f"{bbox.h:.3f}",
                "category": TARGET_CLASS,
                "label_kind": "weak_positive",
                "label_source": "click_success_verified",
                "annotation_completeness": "weak_single_bbox",
                "legacy_bbox_class": "",
                "legacy_bbox_label": "",
                "proposal_source": event.get("proposal_source", ""),
                "template_name": metadata.get("template_name", ""),
                "screen_change_score": event.get("screen_change_score", ""),
                "split_group": screen_row["split_group"],
                "split": "train",
            }
        )

    trace_records, trace_counts = visual_family_traceability(
        con,
        load_traceable_crop_manifests(args.collections_root),
        args.domains,
    )
    con.close()

    assign_splits(screen_rows, args.seed, args.val_ratio, args.test_ratio)
    split_by_screen = {row["screen_id"]: row["split"] for row in screen_rows}
    for row in annotation_rows:
        row["split"] = split_by_screen.get(row["screen_id"], row.get("split", ""))

    ann_by_screen = defaultdict(list)
    for row in annotation_rows:
        ann_by_screen[row["screen_id"]].append(row)

    for screen in screen_rows:
        boxes = ann_by_screen.get(screen["screen_id"], [])
        if boxes:
            for box in boxes:
                manifest_rows.append({**screen, **box})
        else:
            manifest_rows.append(
                {
                    **screen,
                    "annotation_id": "",
                    "bbox_id": "",
                    "bbox_x": "",
                    "bbox_y": "",
                    "bbox_w": "",
                    "bbox_h": "",
                    "category": "none",
                    "label_kind": "verified_empty_negative",
                    "label_source": "manual_verified_empty",
                    "legacy_bbox_class": "",
                    "legacy_bbox_label": "",
                }
            )

    coco_image_id = {row["screen_id"]: index for index, row in enumerate(screen_rows, start=1)}
    coco_images = [
        {
            "id": coco_image_id[row["screen_id"]],
            "file_name": str(Path(row["image_path"]).relative_to(output_dir)).replace("\\", "/"),
            "width": int(row["width"]),
            "height": int(row["height"]),
            "screen_id": row["screen_id"],
            "dataset_role": row["dataset_role"],
            "annotation_completeness": row["annotation_completeness"],
            "split": row["split"],
        }
        for row in screen_rows
    ]
    coco_annotations = []
    for index, row in enumerate(annotation_rows, start=1):
        coco_annotations.append(
            {
                "id": index,
                "image_id": coco_image_id[row["screen_id"]],
                "category_id": 1,
                "bbox": [float(row["bbox_x"]), float(row["bbox_y"]), float(row["bbox_w"]), float(row["bbox_h"])],
                "area": float(row["bbox_w"]) * float(row["bbox_h"]),
                "iscrowd": 0,
                "label_kind": row["label_kind"],
                "label_source": row["label_source"],
            }
        )

    screen_fields = [
        "screen_id",
        "image_path",
        "original_path",
        "relative_path",
        "instance_id",
        "content_id",
        "vision_domain",
        "legacy_screen_state",
        "asset_type",
        "representation",
        "source_root",
        "source_session",
        "width",
        "height",
        "dataset_role",
        "annotation_completeness",
        "proposal_source",
        "template_name",
        "event_json",
        "event_id",
        "timestamp",
        "screen_change_score",
        "positive_bbox_count",
        "split_group",
        "split",
    ]
    annotation_fields = [
        "annotation_id",
        "screen_id",
        "image_path",
        "original_path",
        "instance_id",
        "content_id",
        "bbox_id",
        "bbox_x",
        "bbox_y",
        "bbox_w",
        "bbox_h",
        "category",
        "label_kind",
        "label_source",
        "annotation_completeness",
        "legacy_bbox_class",
        "legacy_bbox_label",
        "proposal_source",
        "template_name",
        "screen_change_score",
        "split_group",
        "split",
    ]
    manifest_fields = list(dict.fromkeys(screen_fields + annotation_fields))
    trace_fields = [
        "instance_id",
        "content_id",
        "original_path",
        "relative_path",
        "vision_domain",
        "families",
        "trace_status",
        "parent_instance_id",
        "parent_content_id",
        "parent_path",
        "bbox_id",
        "bbox",
        "bbox_x",
        "bbox_y",
        "bbox_w",
        "bbox_h",
    ]

    write_csv(output_dir / "screens.csv", screen_rows, screen_fields)
    write_csv(output_dir / "annotations.csv", annotation_rows, annotation_fields)
    write_csv(output_dir / "manifest.csv", manifest_rows, manifest_fields)
    write_csv(output_dir / "classifier_crop_traceability.csv", trace_records, trace_fields)
    (output_dir / "annotations_coco.json").write_text(
        json.dumps(
            {
                "images": coco_images,
                "annotations": coco_annotations,
                "categories": [{"id": 1, "name": TARGET_CLASS}],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    sheets = output_dir / "contact_sheets"
    manual_rows = [row for row in manifest_rows if row.get("label_kind") == "manual_positive"]
    weak_rows = [row for row in manifest_rows if row.get("label_kind") == "weak_positive"]
    empty_rows = [row for row in manifest_rows if row.get("label_kind") == "verified_empty_negative"]
    val_test_rows = [row for row in manifest_rows if row.get("split") in {"val", "test"} and row.get("bbox_x")]
    draw_contact_sheet(manual_rows, sheets / "manual_partial_positive_bbox_overlay.png", title="Manual partial visual_candidate positives")
    draw_contact_sheet(weak_rows, sheets / "click_success_weak_positive_bbox_overlay.png", title="Click-success weak positives train-only")
    draw_contact_sheet(empty_rows, sheets / "verified_empty_negative_screens.png", title="Verified empty negative screens")
    draw_contact_sheet(val_test_rows, sheets / "val_test_manual_bbox_overlay.png", title="Val/test manual bbox overlay")

    summary = {
        "dataset_kind": "ads_detector_visual_candidate_v2",
        "target_class": TARGET_CLASS,
        "db": str(args.db),
        "domains": args.domains,
        "seed": args.seed,
        "val_ratio": args.val_ratio,
        "test_ratio": args.test_ratio,
        "screens_total": len(screen_rows),
        "bbox_total": len(annotation_rows),
        "complete_positive_screens": 0,
        "partial_annotation_screens": sum(1 for row in screen_rows if row["annotation_completeness"] == "partial_annotation"),
        "verified_empty_negative_screens": sum(1 for row in screen_rows if row["dataset_role"] == "verified_empty_negative"),
        "manual_bbox_count": sum(1 for row in annotation_rows if row["label_kind"] == "manual_positive"),
        "weak_positive_bbox_count": sum(1 for row in annotation_rows if row["label_kind"] == "weak_positive"),
        "classifier_crops_with_positive_family": sum(1 for row in trace_records),
        "classifier_crops_traceable_parent_bbox": trace_counts.get("traceable_parent_bbox", 0),
        "classifier_crops_untraceable_parent_bbox": trace_counts.get("untraceable_parent_bbox", 0),
        "classifier_crops_unable_to_trace_parent_bbox": trace_counts.get("untraceable_parent_bbox", 0),
        "screen_dataset_role_counts": dict(Counter(row["dataset_role"] for row in screen_rows)),
        "annotation_label_kind_counts": dict(Counter(row["label_kind"] for row in annotation_rows)),
        "annotation_completeness_counts": dict(Counter(row["annotation_completeness"] for row in screen_rows)),
        "split_counts_screens": dict(Counter(row["split"] for row in screen_rows)),
        "split_counts_annotations": dict(Counter(row["split"] for row in annotation_rows)),
        "split_counts_by_dataset_role": {
            role: dict(Counter(row["split"] for row in screen_rows if row["dataset_role"] == role))
            for role in sorted({row["dataset_role"] for row in screen_rows})
        },
        "proposal_source_counts": dict(Counter(row.get("proposal_source", "") for row in annotation_rows if row.get("proposal_source"))),
        "bbox_stats": bbox_stats(annotation_rows),
        "skipped": dict(skipped),
        "notes": [
            "Detector target is visual_candidate; action_target/click semantics are retained only as legacy provenance.",
            "Manual positive screens are marked partial_annotation by default; unlabeled regions must not be used as detector background negatives.",
            "Click-success bboxes are weak_positive and forced to train split only.",
            "No verified empty negatives are exported unless the review DB explicitly marks a waiting screen has_no_target=1.",
        ],
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Ads Detector Dataset v2",
        "",
        f"- Target class: `{TARGET_CLASS}`",
        f"- Screens: {summary['screens_total']}",
        f"- BBoxes: {summary['bbox_total']}",
        f"- Partial-annotation screens: {summary['partial_annotation_screens']}",
        f"- Verified empty negative screens: {summary['verified_empty_negative_screens']}",
        f"- Manual bbox count: {summary['manual_bbox_count']}",
        f"- Weak-positive bbox count: {summary['weak_positive_bbox_count']}",
        f"- Classifier positive-family crops unable to trace parent+bbox: {summary['classifier_crops_unable_to_trace_parent_bbox']}",
        "",
        "## Split Counts",
    ]
    for split, count in sorted(summary["split_counts_screens"].items()):
        lines.append(f"- `{split}` screens: {count}")
    lines += ["", "## Dataset Role by Split"]
    for role, counts in summary["split_counts_by_dataset_role"].items():
        lines.append(f"- `{role}`: {counts}")
    lines += ["", "## Proposal Sources"]
    if summary["proposal_source_counts"]:
        for source, count in sorted(summary["proposal_source_counts"].items()):
            lines.append(f"- `{source}`: {count}")
    else:
        lines.append("- none")
    lines += [
        "",
        "## Notes",
        "",
        "- This v2 dataset is for dataset audit only; no detector training or runtime integration is performed.",
        "- `waiting` and `returned_to_game` are not treated as empty negatives unless explicitly verified as no visual candidate.",
        "- `_edit`/`_original` style paths are grouped by normalized creative stem; click-success weak positives are train-only.",
    ]
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Ads detector dataset v2 with Vision-layer visual_candidate semantics.")
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--db", type=Path, default=Path("vision_platform/vision_assets/review/vision_review.db"))
    parser.add_argument("--collections-root", type=Path, default=Path("vision_platform/ads/collections"))
    parser.add_argument("--click-success-root", type=Path, default=Path("vision_platform/ads/runtime_collection/click_success"))
    parser.add_argument("--click-success-date", default="")
    parser.add_argument("--output-dir", type=Path, default=Path("vision_platform/ads/datasets/detector/visual_candidate_v2"))
    parser.add_argument("--domains", nargs="+", default=list(DEFAULT_DOMAINS), choices=["ads", "shared"])
    parser.add_argument("--include-annotated", action="store_true")
    parser.add_argument("--min-screen-change", type=float, default=2.0)
    parser.add_argument("--max-click-success", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--test-ratio", type=float, default=0.15)
    parser.add_argument("--overwrite", action="store_true")
    build(parser.parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
