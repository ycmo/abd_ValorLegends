from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}

CSV_FIELDS = [
    "instance_id",
    "content_id",
    "asset_id",
    "original_path",
    "relative_path",
    "filename",
    "extension",
    "parent_directory",
    "source_root",
    "width",
    "height",
    "file_size_bytes",
    "modified_time",
    "sha256",
    "duplicate_group",
    "vision_domain",
    "asset_role",
    "image_scope",
    "scan_status",
    "scan_error",
]


@dataclass(frozen=True)
class SourceRoot:
    configured: str
    path: Path

    @property
    def display(self) -> str:
        return self.configured.replace("/", "\\").rstrip("\\")


def normalize_rel(path: Path) -> str:
    return str(path).replace("/", "\\")


def normalize_relative_path_for_id(relative_path: str) -> str:
    return relative_path.replace("/", "\\").lower()


def short_sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def default_workers() -> int:
    cpu = os.cpu_count() or 1
    return max(1, min(4, cpu))


def load_sources(config_path: Path) -> list[str]:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    sources = data.get("active_sources")
    if not isinstance(sources, list):
        raise ValueError("scan_sources.json must contain an active_sources list")
    return [str(item) for item in sources]


def expand_sources(project_root: Path, source_specs: list[str]) -> list[SourceRoot]:
    seen: set[Path] = set()
    roots: list[SourceRoot] = []
    for spec in source_specs:
        normalized_spec = spec.replace("\\", "/")
        matches = sorted(project_root.glob(normalized_spec)) if any(ch in normalized_spec for ch in "*?[]") else [project_root / normalized_spec]
        for match in matches:
            resolved = match.resolve()
            if not resolved.exists():
                print(f"warning: source does not exist: {spec}")
                continue
            if not resolved.is_dir():
                print(f"warning: source is not a directory: {spec}")
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            rel = normalize_rel(resolved.relative_to(project_root))
            roots.append(SourceRoot(configured=rel, path=resolved))
    return roots


def iter_image_files(source: SourceRoot) -> list[Path]:
    files: list[Path] = []
    for path in source.path.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            files.append(path)
    return sorted(files, key=lambda p: str(p).lower())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_size(path: Path) -> tuple[int | str, int | str]:
    with Image.open(path) as image:
        return image.size


def classify_image_scope(relative_path: str, width: int | str, height: int | str, asset_role: str) -> str:
    p = relative_path.replace("\\", "/").lower()
    name = Path(p).name
    if any(token in p or token in name for token in ("review_sheet", "contact_sheet", "sheet", "mosaic")):
        return "sheet_or_composite"
    if "/runtime_collection/click_success/" in p and name in {"pre_click.png", "post_click.png"}:
        return "fullscreen"
    if asset_role == "candidate_crop":
        return "crop"
    if "/candidates/" in p or "/patches/" in p or "/images/" in p:
        if asset_role in {"review_asset", "runtime_collection"}:
            return "crop"
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        return "unknown"
    if width <= 256 and height <= 256:
        return "crop"
    ratio = width / height
    if width >= 480 and height >= 270 and 1.3 <= ratio <= 2.1:
        return "fullscreen"
    if any(token in name for token in ("crop", "roi", "cand_", "candidate")):
        return "crop"
    return "unknown"


def classify_asset_role(relative_path: str) -> str:
    p = relative_path.replace("\\", "/").lower()

    if p.startswith("log/"):
        return "runtime_log"
    if p.startswith("close_x_classifier/runtime_collection") or p.startswith("vision_platform/ads/runtime_collection/"):
        return "runtime_collection"
    if p.startswith("vision_platform/ads/hard_negative_mining/"):
        return "candidate_crop"
    if p.startswith("vision_platform/ads/collections/"):
        return "candidate_crop"
    if "/debug/" in p or "/debug_output/" in p or p.startswith("debug/") or "debug" in Path(p).parts:
        return "debug_output"
    if p.startswith("close_x_classifier/runs/"):
        return "model_output"
    if p.startswith("assets/tasks/") or p.startswith("assets/shared/"):
        return "template"
    if p.startswith("ads2/assets/1_templates/"):
        return "template"
    if p.startswith("switch_account/templates/"):
        return "template"
    if p.startswith("awayfromkeyboard/integration_task/templates/"):
        return "template"
    if p.startswith("manual_screenshots/"):
        return "manual_screenshot"
    if p.startswith("ads2/assets/3_reference_screens/"):
        return "reference_screen"
    if p.startswith("awayfromkeyboard/route_screenshots/"):
        return "reference_screen"
    if p.startswith("close_x_classifier/review/"):
        return "review_asset"
    if p.startswith("close_x_classifier/data/review_batch_001/"):
        return "review_asset"
    if p.startswith("ads2/assets/2_communication/"):
        return "review_asset"
    if p.startswith("ads2/assets/review_crops/"):
        return "candidate_crop"
    if p.startswith("close_x_classifier/data/stage0_6_canonical_object_poc/"):
        return "candidate_crop"
    if p.startswith("arcane_forge/assets/manual/"):
        return "manual_screenshot"
    if p.startswith("magic_shop/assets/"):
        return "template"
    return "unknown"


def classify_vision_domain(relative_path: str) -> str:
    p = relative_path.replace("\\", "/").lower()
    parts = p.split("/")

    if p.startswith("ads/") or p.startswith("ads2/") or p.startswith("close_x_classifier/") or p.startswith("vision_platform/ads/"):
        return "ads"
    if (
        p.startswith("awayfromkeyboard/")
        or p.startswith("switch_account/")
        or p.startswith("call_of_the_gale/")
        or p.startswith("magic_shop/")
        or p.startswith("arcane_forge/")
        or p.startswith("screw/")
        or p.startswith("tasks/")
        or p.startswith("assets/tasks/")
    ):
        return "game"
    if p.startswith("manual_screenshots/"):
        manual_tokens = set(parts[1:]) if len(parts) > 1 else set()
        joined = "/".join(parts[1:])
        if any(token in joined for token in ("看廣告", "route廣告", "/廣告/", "廣告/")):
            return "ads"
        if manual_tokens:
            return "game"
        return "unknown"
    if p.startswith("assets/shared/"):
        return "unknown"
    if p.startswith("log/"):
        return "unknown"
    return "unknown"


def scan_one(project_root: Path, source: SourceRoot, path: Path) -> dict[str, Any]:
    relative = normalize_rel(path.relative_to(project_root))
    parent = normalize_rel(path.parent.relative_to(project_root))
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    size = path.stat().st_size
    sha = ""
    width: int | str = ""
    height: int | str = ""
    status = "ok"
    error = ""

    try:
        sha = sha256_file(path)
        width, height = image_size(path)
    except Exception as exc:  # Keep corrupt/unreadable files in inventory.
        status = "error"
        error = f"{type(exc).__name__}: {exc}"
        if not sha:
            try:
                sha = sha256_file(path)
            except Exception:
                sha = ""

    instance_id = f"file_{short_sha256_text(normalize_relative_path_for_id(relative))}"
    content_id = f"asset_{sha[:16]}" if sha else f"asset_error_{short_sha256_text(normalize_relative_path_for_id(relative))}"
    vision_domain = classify_vision_domain(relative)
    asset_role = classify_asset_role(relative)
    image_scope = classify_image_scope(relative, width, height, asset_role)
    return {
        "instance_id": instance_id,
        "content_id": content_id,
        "asset_id": content_id,
        "original_path": str(path),
        "relative_path": relative,
        "filename": path.name,
        "extension": path.suffix.lower(),
        "parent_directory": parent,
        "source_root": source.display,
        "width": width,
        "height": height,
        "file_size_bytes": size,
        "modified_time": modified,
        "sha256": sha,
        "duplicate_group": "",
        "vision_domain": vision_domain,
        "asset_role": asset_role,
        "image_scope": image_scope,
        "scan_status": status,
        "scan_error": error,
    }


def assign_duplicate_groups(rows: list[dict[str, Any]]) -> None:
    by_hash: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["sha256"]:
            by_hash[row["sha256"]].append(row)
    for sha, group in by_hash.items():
        if len(group) > 1:
            duplicate_group = f"dup_{sha[:16]}"
            for row in group:
                row["duplicate_group"] = duplicate_group


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def duplicate_groups_by_hash(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_hash: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["sha256"]:
            by_hash[row["sha256"]].append(row)
    return {sha: group for sha, group in by_hash.items() if len(group) > 1}


def redundant_instance_ids(rows: list[dict[str, Any]]) -> set[str]:
    redundant: set[str] = set()
    for group in duplicate_groups_by_hash(rows).values():
        sorted_group = sorted(group, key=lambda row: row["relative_path"].lower())
        for row in sorted_group[1:]:
            redundant.add(row["instance_id"])
    return redundant


def directory_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    redundant = redundant_instance_ids(rows)
    grouped: defaultdict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["source_root"], row["vision_domain"], row["asset_role"], row["image_scope"])].append(row)
    result = []
    for (source_root, vision_domain, asset_role, image_scope), group in sorted(grouped.items()):
        files_in_duplicate_groups = sum(1 for row in group if row["duplicate_group"])
        result.append(
            {
                "source_root": source_root,
                "vision_domain": vision_domain,
                "asset_role": asset_role,
                "image_scope": image_scope,
                "image_count": len(group),
                "total_size_bytes": sum(int(row["file_size_bytes"]) for row in group),
                "error_count": sum(1 for row in group if row["scan_status"] == "error"),
                "files_in_duplicate_groups": files_in_duplicate_groups,
                "redundant_copy_occurrences": sum(1 for row in group if row["instance_id"] in redundant),
            }
        )
    return result


def duplicate_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["duplicate_group"]:
            grouped[row["duplicate_group"]].append(row)
    result = []
    for duplicate_group, group in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        sorted_group = sorted(group, key=lambda r: r["relative_path"].lower())
        source_roots = sorted({row["source_root"] for row in group})
        vision_domains = sorted({row["vision_domain"] for row in group})
        asset_roles = sorted({row["asset_role"] for row in group})
        representative_size = int(sorted_group[0]["file_size_bytes"])
        total_size = sum(int(row["file_size_bytes"]) for row in group)
        result.append(
            {
                "duplicate_group": duplicate_group,
                "content_id": group[0]["content_id"],
                "sha256": group[0]["sha256"],
                "file_count": len(group),
                "redundant_copy_count": len(group) - 1,
                "total_size_bytes": total_size,
                "reclaimable_bytes": total_size - representative_size,
                "cross_source": len(source_roots) > 1,
                "cross_role": len(asset_roles) > 1,
                "source_roots": " | ".join(source_roots),
                "vision_domains": " | ".join(vision_domains),
                "asset_roles": " | ".join(asset_roles),
                "paths": " | ".join(row["relative_path"] for row in sorted_group),
            }
        )
    return result


def scan_summary(rows: list[dict[str, Any]], scan_time: str) -> dict[str, Any]:
    hashes = [row["sha256"] for row in rows if row["sha256"]]
    hash_counts = Counter(hashes)
    dup_groups = duplicate_groups_by_hash(rows)
    files_in_duplicate_groups = sum(len(group) for group in dup_groups.values())
    redundant_copies = sum(len(group) - 1 for group in dup_groups.values())
    reclaimable_bytes = 0
    cross_source_duplicate_groups = 0
    cross_role_duplicate_groups = 0
    for group in dup_groups.values():
        sorted_group = sorted(group, key=lambda row: row["relative_path"].lower())
        reclaimable_bytes += sum(int(row["file_size_bytes"]) for row in sorted_group[1:])
        if len({row["source_root"] for row in group}) > 1:
            cross_source_duplicate_groups += 1
        if len({row["asset_role"] for row in group}) > 1:
            cross_role_duplicate_groups += 1
    return {
        "scan_time": scan_time,
        "total_instances": len(rows),
        "unique_instance_ids": len({row["instance_id"] for row in rows}),
        "unique_content_ids": len({row["content_id"] for row in rows if row["sha256"]}),
        "total_images": len(rows),
        "total_size_bytes": sum(int(row["file_size_bytes"]) for row in rows),
        "successful_images": sum(1 for row in rows if row["scan_status"] == "ok"),
        "error_images": sum(1 for row in rows if row["scan_status"] == "error"),
        "unique_hashes": len(hash_counts),
        "files_in_duplicate_groups": files_in_duplicate_groups,
        "redundant_copies": redundant_copies,
        "duplicate_groups": len(dup_groups),
        "reclaimable_bytes": reclaimable_bytes,
        "cross_source_duplicate_groups": cross_source_duplicate_groups,
        "cross_role_duplicate_groups": cross_role_duplicate_groups,
        "counts_by_extension": dict(sorted(Counter(row["extension"] for row in rows).items())),
        "counts_by_vision_domain": dict(sorted(Counter(row["vision_domain"] for row in rows).items())),
        "counts_by_asset_role": dict(sorted(Counter(row["asset_role"] for row in rows).items())),
        "counts_by_image_scope": dict(sorted(Counter(row["image_scope"] for row in rows).items())),
        "counts_by_source_root": dict(sorted(Counter(row["source_root"] for row in rows).items())),
    }


def top_directories(rows: list[dict[str, Any]], limit: int = 20) -> list[tuple[str, int, int]]:
    counter: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        counter[row["parent_directory"]].append(row)
    ranked = sorted(counter.items(), key=lambda item: (-len(item[1]), item[0].lower()))[:limit]
    return [(path, len(group), sum(int(row["file_size_bytes"]) for row in group)) for path, group in ranked]


def write_markdown_summary(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Vision Asset Inventory Summary",
        "",
        "> `asset_id` is a legacy compatibility field. Prefer `instance_id` for a physical file path and `content_id` for identical image content.",
        "",
        f"- Scan time: `{summary['scan_time']}`",
        f"- Total instances: `{summary['total_instances']}`",
        f"- Unique image contents: `{summary['unique_content_ids']}`",
        f"- Total size: `{summary['total_size_bytes']}` bytes",
        f"- Successful images: `{summary['successful_images']}`",
        f"- Scan errors: `{summary['error_images']}`",
        f"- Files in duplicate groups: `{summary['files_in_duplicate_groups']}`",
        f"- Redundant copies: `{summary['redundant_copies']}`",
        f"- Duplicate groups: `{summary['duplicate_groups']}`",
        f"- Reclaimable bytes: `{summary['reclaimable_bytes']}`",
        f"- Cross-source duplicate groups: `{summary['cross_source_duplicate_groups']}`",
        f"- Cross-role duplicate groups: `{summary['cross_role_duplicate_groups']}`",
        "",
        "Duplicate images are not automatically safe to delete. The same content may be intentionally reused as a template, review asset, candidate crop, runtime evidence, or model artifact.",
        "",
        "## Counts By Source Root",
        "",
        "| Source root | Count |",
        "|---|---:|",
    ]
    for source_root, count in sorted(summary["counts_by_source_root"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| `{source_root}` | {count} |")
    lines.extend(["", "## Counts By Vision Domain", "", "| Vision domain | Count |", "|---|---:|"])
    for domain, count in sorted(summary["counts_by_vision_domain"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| `{domain}` | {count} |")
    lines.extend(["", "## Counts By Asset Role", "", "| Asset role | Count |", "|---|---:|"])
    for role, count in sorted(summary["counts_by_asset_role"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| `{role}` | {count} |")
    lines.extend(["", "## Counts By Image Scope", "", "| Image scope | Count |", "|---|---:|"])
    for scope, count in sorted(summary["counts_by_image_scope"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| `{scope}` | {count} |")
    lines.extend(["", "## Top 20 Directories", "", "| Directory | Count | Size bytes |", "|---|---:|---:|"])
    for directory, count, size in top_directories(rows):
        lines.append(f"| `{directory}` | {count} | {size} |")
    lines.extend(
        [
            "",
            "## Suggested Next Priorities",
            "",
            "1. Review `manual_screenshots/` and `ads2/assets/1_templates/` as curated human/template sources.",
            "2. Review `ads2/assets/review_crops/` and `close_x_classifier/data/review_batch_001/` as candidate/review data.",
            "3. Keep `log/` indexed only; do not copy it into review until a specific mining task needs it.",
            "4. Use `vision_domain` to split future review batches into ads, game, and domain triage queues before any model-specific labeling.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a stable image inventory for Vision Platform assets.")
    parser.add_argument("--project-root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument(
        "--config",
        default="vision_platform/vision_assets/inventory/scan_sources.json",
        help="Scan source config JSON, relative to project root unless absolute.",
    )
    parser.add_argument("--workers", type=int, default=default_workers(), help="Worker threads for file IO. Default is conservative.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = project_root / config_path

    inventory_dir = project_root / "vision_platform" / "vision_assets" / "inventory"
    reports_dir = project_root / "vision_platform" / "vision_assets" / "reports"
    inventory_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    sources = expand_sources(project_root, load_sources(config_path))
    print("scan sources:")
    for source in sources:
        print(f"  - {source.display}")

    jobs: list[tuple[SourceRoot, Path]] = []
    for source in sources:
        source_files = iter_image_files(source)
        print(f"source {source.display}: {len(source_files)} images")
        jobs.extend((source, path) for path in source_files)

    rows: list[dict[str, Any]] = []
    scanned = 0
    workers = max(1, args.workers)
    print(f"workers: {workers}")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(scan_one, project_root, source, path) for source, path in jobs]
        for future in as_completed(futures):
            rows.append(future.result())
            scanned += 1
            if scanned % 500 == 0 or scanned == len(futures):
                ok = sum(1 for row in rows if row["scan_status"] == "ok")
                err = len(rows) - ok
                print(f"scanned {scanned}/{len(futures)}; ok={ok}; errors={err}")

    rows.sort(key=lambda row: row["relative_path"].lower())
    assign_duplicate_groups(rows)

    scan_time = datetime.now(timezone.utc).isoformat()
    summary = scan_summary(rows, scan_time)
    dir_rows = directory_summary(rows)
    dup_rows = duplicate_summary(rows)

    assets_csv = inventory_dir / "assets.csv"
    directory_csv = reports_dir / "directory_summary.csv"
    duplicate_csv = reports_dir / "duplicate_summary.csv"
    summary_json = reports_dir / "scan_summary.json"
    summary_md = reports_dir / "inventory_summary.md"

    write_csv(assets_csv, rows, CSV_FIELDS)
    write_csv(
        directory_csv,
        dir_rows,
        [
            "source_root",
            "vision_domain",
            "asset_role",
            "image_scope",
            "image_count",
            "total_size_bytes",
            "error_count",
            "files_in_duplicate_groups",
            "redundant_copy_occurrences",
        ],
    )
    write_csv(
        duplicate_csv,
        dup_rows,
        [
            "duplicate_group",
            "content_id",
            "sha256",
            "file_count",
            "redundant_copy_count",
            "total_size_bytes",
            "reclaimable_bytes",
            "cross_source",
            "cross_role",
            "source_roots",
            "vision_domains",
            "asset_roles",
            "paths",
        ],
    )
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown_summary(summary_md, summary, rows)

    print(f"total instances: {summary['total_instances']}")
    print(f"successful images: {summary['successful_images']}")
    print(f"error images: {summary['error_images']}")
    print(f"files in duplicate groups: {summary['files_in_duplicate_groups']}")
    print(f"redundant copies: {summary['redundant_copies']}")
    print(f"duplicate groups: {summary['duplicate_groups']}")
    print("outputs:")
    for output in [assets_csv, directory_csv, duplicate_csv, summary_json, summary_md]:
        print(f"  - {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
