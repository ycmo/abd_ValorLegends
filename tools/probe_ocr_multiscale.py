from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ocr_utils import get_cached_easyocr_reader


def parse_roi(text: str) -> tuple[int, int, int, int]:
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("ROI must be x,y,w,h")
    try:
        return tuple(int(part) for part in parts)  # type: ignore[return-value]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ROI must contain integers") from exc


def parse_scales(text: str) -> tuple[float, ...]:
    try:
        scales = tuple(float(part.strip()) for part in text.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("scales must be comma-separated numbers") from exc
    if not scales:
        raise argparse.ArgumentTypeError("at least one scale is required")
    return scales


def parse_digits(text: str) -> Optional[int]:
    digits = re.sub(r"\D+", "", text)
    return int(digits) if digits else None


def parse_power(text: str) -> Optional[int]:
    cleaned = re.sub(r"[^0-9kKmM,]", "", text)
    if not cleaned:
        return None
    no_commas = cleaned.replace(",", "")
    match = re.search(r"(\d+)([kKmM])?", no_commas)
    if not match:
        return None
    value = int(match.group(1))
    suffix = (match.group(2) or "").lower()
    if suffix == "m":
        return value * 1000
    if suffix == "k":
        return value
    return value


def parse_time_seconds(text: str) -> Optional[int]:
    compact = re.sub(r"\s+", "", text)
    match = re.search(r"(?<!\d)(\d{1,2}):([0-5]\d):([0-5]\d)(?!\d)", compact)
    if not match:
        return None
    hours, minutes, seconds = (int(value) for value in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def parser_for_kind(kind: str) -> Callable[[str], Optional[int]]:
    if kind in {"digits", "green-digits"}:
        return parse_digits
    if kind == "time":
        return parse_time_seconds
    if kind == "power":
        return parse_power
    raise ValueError(f"unsupported kind: {kind}")


def allowlist_for_kind(kind: str) -> str:
    if kind in {"digits", "green-digits"}:
        return "0123456789"
    if kind == "time":
        return "0123456789:"
    if kind == "power":
        return "0123456789,kKmM"
    raise ValueError(f"unsupported kind: {kind}")


def preprocess(image: np.ndarray, *, kind: str, scale: float, pad: int, border: tuple[int, int, int]) -> np.ndarray:
    source = image
    interpolation = cv2.INTER_CUBIC
    if kind == "green-digits":
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (35, 80, 80), (95, 255, 255))
        source = np.full(image.shape, 255, dtype=np.uint8)
        source[mask > 0] = (0, 0, 0)
        interpolation = cv2.INTER_NEAREST
    resized = cv2.resize(source, None, fx=scale, fy=scale, interpolation=interpolation)
    if pad <= 0:
        return resized
    return cv2.copyMakeBorder(
        resized,
        pad,
        pad,
        pad,
        pad,
        cv2.BORDER_CONSTANT,
        value=list(border),
    )


def combine_results(results) -> tuple[str, float]:
    pieces = []
    for box, text, confidence in results:
        cleaned = str(text).strip()
        if not cleaned:
            continue
        left_values = []
        for point in box:
            try:
                left_values.append(float(point[0]))
            except (TypeError, ValueError, IndexError):
                continue
        pieces.append((min(left_values) if left_values else 0.0, cleaned, float(confidence)))
    if not pieces:
        return "", 0.0
    pieces.sort(key=lambda item: item[0])
    return "".join(piece[1] for piece in pieces).replace(" ", ""), min(piece[2] for piece in pieces)


def probe_image(
    image_path: Path,
    *,
    kind: str,
    roi: Optional[tuple[int, int, int, int]],
    scales: tuple[float, ...],
    pad: int,
    border: tuple[int, int, int],
) -> list[dict]:
    raw = np.fromfile(str(image_path), dtype=np.uint8)
    screen = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if screen is None:
        raise RuntimeError(f"cannot read image: {image_path}")
    image = screen
    if roi is not None:
        x, y, w, h = roi
        image = screen[y : y + h, x : x + w]
    if image.size == 0:
        raise RuntimeError(f"empty image/roi: {image_path}")

    reader = get_cached_easyocr_reader(("en",), download_enabled=False)
    parser = parser_for_kind(kind)
    allowlist = allowlist_for_kind(kind)
    rows = []
    for scale in scales:
        prepared = preprocess(image, kind=kind, scale=scale, pad=pad, border=border)
        try:
            ocr_results = reader.readtext(prepared, detail=1, allowlist=allowlist)
        except TypeError:
            ocr_results = reader.readtext(prepared, allowlist=allowlist)
        text, confidence = combine_results(ocr_results)
        rows.append(
            {
                "scale": scale,
                "text": text,
                "parsed": parser(text),
                "confidence": confidence,
            }
        )
    return rows


def decision(rows: list[dict], *, fast_accept: float) -> str:
    parsed_rows = [row for row in rows if row["parsed"] is not None]
    if not parsed_rows:
        return "no_parse"
    first = parsed_rows[0]
    if first["confidence"] >= fast_accept:
        return f"fast_accept parsed={first['parsed']} scale={first['scale']} confidence={first['confidence']:.4f}"
    values = Counter(row["parsed"] for row in parsed_rows)
    if len(values) == 1 and len(parsed_rows) >= 2:
        best = max(parsed_rows, key=lambda row: row["confidence"])
        return (
            f"agreement parsed={best['parsed']} scale={best['scale']} "
            f"confidence={best['confidence']:.4f} count={len(parsed_rows)}"
        )
    return "conflict " + ", ".join(f"{value}:{count}" for value, count in values.items())


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe EasyOCR confidence across image scales.")
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--kind", choices=("digits", "time", "power", "green-digits"), required=True)
    parser.add_argument("--roi", type=parse_roi)
    parser.add_argument("--scales", type=parse_scales, default=(2.0, 3.0, 4.0, 5.0))
    parser.add_argument("--pad", type=int, default=12)
    parser.add_argument("--border", type=parse_roi, default=(255, 255, 255, 0), help="b,g,r,ignored")
    parser.add_argument("--fast-accept", type=float, default=0.85)
    args = parser.parse_args()

    border = tuple(args.border[:3])
    for image in args.images:
        rows = probe_image(
            image,
            kind=args.kind,
            roi=args.roi,
            scales=args.scales,
            pad=args.pad,
            border=border,
        )
        print(f"image={image}")
        print(f"kind={args.kind} roi={args.roi or 'full'} scales={','.join(str(scale) for scale in args.scales)}")
        print("scale\ttext\tparsed\tconfidence")
        for row in rows:
            print(f"{row['scale']:g}\t{row['text'] or '<empty>'}\t{row['parsed']}\t{row['confidence']:.4f}")
        print("decision=" + decision(rows, fast_accept=args.fast_accept))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
