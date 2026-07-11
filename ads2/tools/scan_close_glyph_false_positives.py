from __future__ import annotations

import argparse
import os
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import cv2
import numpy as np


def read_bgr(path: Path):
    raw = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if raw is None:
        return None
    if raw.ndim == 2:
        return cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
    return raw[:, :, :3]


def write_png(path: Path, image) -> None:
    ok, buffer = cv2.imencode(".png", image)
    if ok:
        buffer.tofile(str(path))


def color_edge_from_bgr(bgr, *, saturation_max: int, value_min: int):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] <= saturation_max) & (hsv[:, :, 2] >= value_min)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    edge = cv2.Canny(mask, 40, 120)
    return cv2.dilate(edge, np.ones((2, 2), np.uint8), iterations=1)


def bbox_from_mask(mask):
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


def crop_bbox(image, bbox, *, pad: int):
    h, w = image.shape[:2]
    x, y, bw, bh = bbox
    return image[
        max(0, y - pad) : min(h, y + bh + pad),
        max(0, x - pad) : min(w, x + bw + pad),
    ]


def build_template(
    close_icons_dir: Path,
    *,
    source_name: str,
    padding: int,
    saturation_max: int,
    value_min: int,
):
    source = read_bgr(close_icons_dir / source_name)
    if source is None:
        raise FileNotFoundError(close_icons_dir / source_name)
    padded = cv2.copyMakeBorder(source, padding, padding, padding, padding, cv2.BORDER_REPLICATE)
    edge = color_edge_from_bgr(padded, saturation_max=saturation_max, value_min=value_min)
    bbox = bbox_from_mask(edge)
    if bbox is None:
        raise ValueError(f"Cannot build glyph template from {source_name}")
    return crop_bbox(edge, bbox, pad=1)


def best_match(screen_bgr, template, *, scales, roi_top_ratio, saturation_max, value_min):
    h, w = screen_bgr.shape[:2]
    roi = screen_bgr[: int(h * roi_top_ratio), :]
    edge = color_edge_from_bgr(roi, saturation_max=saturation_max, value_min=value_min)
    best = (0.0, None, None)
    for scale in scales:
        tw = max(4, int(round(template.shape[1] * scale)))
        th = max(4, int(round(template.shape[0] * scale)))
        if tw > edge.shape[1] or th > edge.shape[0]:
            continue
        resized = cv2.resize(template, (tw, th), interpolation=cv2.INTER_NEAREST)
        result = cv2.matchTemplate(edge, resized, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(result)
        if score > best[0]:
            best = (float(score), scale, (loc[0], loc[1], tw, th))
    return best


def is_ad_path(path: Path) -> bool:
    text = str(path).lower()
    return any(term.lower() in text for term in ("看廣告", "廣告", "ads", "ad_", "weekly_minigame"))


def is_tap_debug_path(path: Path) -> bool:
    name = path.name.lower()
    return (
        "_before_tap_" in name
        or "_after_tap_" in name
        or re.search(r"(?:^|_)tap_\d+_\d+(?:_|\.png$)", name) is not None
    )


def scan_one_path(path: Path, template, *, scales, args):
    image = read_bgr(path)
    if image is None:
        return None
    score, scale, box = best_match(
        image,
        template,
        scales=scales,
        roi_top_ratio=args.roi_top_ratio,
        saturation_max=args.saturation_max,
        value_min=args.value_min,
    )
    if score < args.threshold:
        return None
    return {
        "score": score,
        "scale": scale,
        "box": box,
        "ad_path": is_ad_path(path),
        "path": path,
    }


def make_sheet(
    rows,
    output_path: Path,
    *,
    max_items: int,
    roi_top_ratio: float,
    box_margin: int,
    box_thickness: int,
) -> None:
    tiles = []
    for row in rows[:max_items]:
        img = read_bgr(row["path"])
        if img is None or row["box"] is None:
            continue
        h, w = img.shape[:2]
        x, y, bw, bh = row["box"]
        pad = 55
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(w, x + bw + pad), min(int(h * roi_top_ratio), y + bh + pad)
        crop = img[y0:y1, x0:x1].copy()
        rx0 = max(0, x - x0 - box_margin)
        ry0 = max(0, y - y0 - box_margin)
        rx1 = min(crop.shape[1] - 1, x - x0 + bw + box_margin)
        ry1 = min(crop.shape[0] - 1, y - y0 + bh + box_margin)
        cv2.rectangle(crop, (rx0, ry0), (rx1, ry1), (0, 0, 255), box_thickness)
        tile = cv2.resize(crop, (230, 125), interpolation=cv2.INTER_AREA)
        tile = cv2.copyMakeBorder(tile, 38, 32, 6, 6, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        cv2.putText(
            tile,
            f"{row['score']:.3f} {row['scale']:.2f} ad={row['ad_path']}",
            (8, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            tile,
            row["path"].parent.name[:38],
            (8, 150),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.36,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
        tiles.append(tile)
    if not tiles:
        return
    cols = 4
    blank = np.full_like(tiles[0], 255)
    while len(tiles) % cols:
        tiles.append(blank.copy())
    sheet = np.vstack([np.hstack(tiles[i : i + cols]) for i in range(0, len(tiles), cols)])
    write_png(output_path, sheet)


def scan_paths_threaded(paths, template, *, scales, args, worker_count: int):
    rows = []
    completed = 0
    next_index = 0
    in_flight_limit = max(worker_count, worker_count * 2)

    def submit_more(executor, futures):
        nonlocal next_index
        while next_index < len(paths) and len(futures) < in_flight_limit:
            path = paths[next_index]
            next_index += 1
            futures.add(executor.submit(scan_one_path, path, template, scales=scales, args=args))

    print(f"workers: {worker_count}; opencv_threads: {cv2.getNumThreads()}")
    executor = ThreadPoolExecutor(max_workers=worker_count)
    futures = set()
    try:
        submit_more(executor, futures)
        while futures:
            done, futures = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                row = future.result()
                completed += 1
                if row is not None:
                    rows.append(row)
                if completed % 500 == 0:
                    print(f"scanned {completed}/{len(paths)}; hits={len(rows)}")
            submit_more(executor, futures)
    except KeyboardInterrupt:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        print(f"interrupted after {completed}/{len(paths)} completed; writing partial results")
        return rows, completed, True

    executor.shutdown(wait=True)
    return rows, completed, False


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan log screenshots for close-glyph false positives.")
    parser.add_argument("--log-dir", type=Path, default=Path("log"))
    parser.add_argument("--close-icons-dir", type=Path, default=Path("ads2/assets/1_templates/close_icons"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ads2/assets/review_crops/close_glyph_candidates/color_gated_log_scan_all"),
    )
    parser.add_argument("--threshold", type=float, default=0.60)
    parser.add_argument("--source", default="close_5.png")
    parser.add_argument("--padding", type=int, default=12)
    parser.add_argument("--saturation-max", type=int, default=30)
    parser.add_argument("--value-min", type=int, default=230)
    parser.add_argument("--roi-top-ratio", type=float, default=0.40)
    parser.add_argument("--sheet-items", type=int, default=80)
    parser.add_argument("--limit", type=int, default=0, help="Optional max screenshots to scan; 0 means all.")
    parser.add_argument("--scale-min", type=float, default=None, help="Optional minimum template scale to test.")
    parser.add_argument("--scale-max", type=float, default=None, help="Optional maximum template scale to test.")
    parser.add_argument("--box-margin", type=int, default=8, help="Pixels between the matched box and review rectangle.")
    parser.add_argument("--box-thickness", type=int, default=2, help="Review rectangle line thickness.")
    parser.add_argument(
        "--exclude-tap-debug",
        action="store_true",
        help="Exclude before_tap/after_tap debug screenshots that may contain click crosshair markers.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Parallel worker count. 0 means auto; 1 disables multi-threading.",
    )
    parser.add_argument(
        "--opencv-threads",
        type=int,
        default=1,
        help="OpenCV internal thread count per worker. Keep this low when --workers is high.",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.opencv_threads > 0:
        cv2.setNumThreads(args.opencv_threads)
    base_scales = (0.65, 0.75, 0.85, 0.95, 1.0, 1.1, 1.2, 1.35, 1.5)
    scales = tuple(
        scale
        for scale in base_scales
        if (args.scale_min is None or scale >= args.scale_min)
        and (args.scale_max is None or scale <= args.scale_max)
    )
    if not scales:
        raise SystemExit(
            "No template scales selected. Adjust --scale-min/--scale-max or omit them."
        )
    template = build_template(
        args.close_icons_dir,
        source_name=args.source,
        padding=args.padding,
        saturation_max=args.saturation_max,
        value_min=args.value_min,
    )

    all_paths = sorted(args.log_dir.rglob("*.png"))
    paths = [path for path in all_paths if not is_tap_debug_path(path)] if args.exclude_tap_debug else all_paths
    if args.limit > 0:
        paths = paths[: args.limit]

    rows = []
    completed_count = 0
    interrupted = False
    worker_count = args.workers
    if worker_count <= 0:
        worker_count = min(8, max(1, (os.cpu_count() or 4) - 1))

    if worker_count == 1:
        try:
            for index, path in enumerate(paths, 1):
                row = scan_one_path(path, template, scales=scales, args=args)
                completed_count = index
                if row is not None:
                    rows.append(row)
                if index % 500 == 0:
                    print(f"scanned {index}/{len(paths)}; hits={len(rows)}")
        except KeyboardInterrupt:
            interrupted = True
            print(f"interrupted after {completed_count}/{len(paths)} completed; writing partial results")
    else:
        rows, completed_count, interrupted = scan_paths_threaded(
            paths,
            template,
            scales=scales,
            args=args,
            worker_count=worker_count,
        )

    rows.sort(key=lambda row: row["score"], reverse=True)
    report_lines = [
        "# Full log color-gated edge scan",
        "",
        f"Images discovered: {len(all_paths)}",
        f"Tap debug images excluded: {len(all_paths) - len(paths)}",
        f"Exclude tap debug: {args.exclude_tap_debug}",
        f"Images selected: {len(paths)}",
        f"Images completed: {completed_count}",
        f"Interrupted: {interrupted}",
        f"Threshold: >= {args.threshold:.2f}",
        f"Hits: {len(rows)}",
        f"Non-ad path hits: {sum(1 for row in rows if not row['ad_path'])}",
        f"Color mask: HSV S <= {args.saturation_max}, V >= {args.value_min}",
        f"ROI: top {args.roi_top_ratio:.0%} of each screenshot",
        f"Scales tested: {', '.join(f'{scale:.2f}' for scale in scales)}",
        f"Workers: {worker_count}",
        f"OpenCV threads per worker: {cv2.getNumThreads()}",
        f"Review box margin: {args.box_margin}px",
        f"Review box thickness: {args.box_thickness}px",
        "",
        "| score | scale | box | ad_path | file |",
        "|---:|---:|---|---|---|",
    ]
    for row in rows:
        report_lines.append(
            f"| {row['score']:.3f} | {row['scale']:.2f} | `{row['box']}` | "
            f"{row['ad_path']} | `{row['path'].as_posix()}` |"
        )
    (args.output_dir / "scan_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    make_sheet(
        rows,
        args.output_dir / "hits_all_top80.png",
        max_items=args.sheet_items,
        roi_top_ratio=args.roi_top_ratio,
        box_margin=args.box_margin,
        box_thickness=args.box_thickness,
    )
    make_sheet(
        [row for row in rows if not row["ad_path"]],
        args.output_dir / "hits_non_ad_top80.png",
        max_items=args.sheet_items,
        roi_top_ratio=args.roi_top_ratio,
        box_margin=args.box_margin,
        box_thickness=args.box_thickness,
    )
    make_sheet(
        [row for row in rows if row["ad_path"]],
        args.output_dir / "hits_ad_top80.png",
        max_items=args.sheet_items,
        roi_top_ratio=args.roi_top_ratio,
        box_margin=args.box_margin,
        box_thickness=args.box_thickness,
    )

    print(args.output_dir.resolve())
    print("report:", (args.output_dir / "scan_report.md").resolve())
    print("non-ad sheet:", (args.output_dir / "hits_non_ad_top80.png").resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
