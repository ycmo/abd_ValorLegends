from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from src.config import ROOT_DIR
from src.profiler import profile_enabled, profile_load

_EASYOCR_READER_CACHE = {}
_EASYOCR_READER_CACHE_LOCK = threading.RLock()
EASYOCR_MODEL_DIR = ROOT_DIR / ".easyocr" / "model"


def _profile_load(message: str) -> None:
    profile_load(message)


class _ProfiledEasyOCRReader:
    def __init__(self, reader, languages: Tuple[str, ...]):
        self._reader = reader
        self._languages = languages

    def __getattr__(self, name):
        return getattr(self._reader, name)

    def readtext(self, *args, **kwargs):
        if not profile_enabled():
            return self._reader.readtext(*args, **kwargs)
        started = time.perf_counter()
        try:
            return self._reader.readtext(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - started
            _profile_load(
                f"easyocr readtext languages={','.join(self._languages)} elapsed={elapsed:.3f}s"
            )


def parse_power_value(text: str) -> int:
    cleaned = text.lower().replace(",", "").replace(" ", "")
    match = re.search(r"(\d+)([km])?", cleaned)
    if not match:
        return -1
    value = int(match.group(1))
    suffix = match.group(2)
    if suffix == "m":
        return value * 1000
    return value if suffix == "k" else value // 1000


def parse_compact_number(text: str) -> int:
    """解析帶有 k, m 單位後綴的資源數量字串，並返回實際的整數值"""
    cleaned = text.lower().replace(",", "").replace(" ", "")
    match = re.search(r"(\d+)([km])?", cleaned)
    if not match:
        return -1
    value = int(match.group(1))
    suffix = match.group(2)
    if suffix == "m":
        return value * 1000000
    elif suffix == "k":
        return value * 1000
    return value


def power_has_scale_suffix(text: str) -> bool:
    return re.search(r"[kKmM]", str(text)) is not None


def get_arena_hash_map() -> Dict[str, str]:
    return {
        "7507d180": "1",
        "a562d68e": "1",
        "d9e1978c": "1",
        "8bfdef99": "2",
        "cddb6d11": "2",
        "22fa0bf5": "3",
        "2cd0bbff": "4",
        "7ad3e45a": "4",
        "5d33125e": "4",
        "4e0994ce": "5",
        "c6fb5fbc": "5",
        "102414d0": "5",
        "0514a874": "6",
        "65578314": "7",
        "fcfbd7a3": "7",
        "98e8090e": "7",
        "820bef7d": "0",
        "1144e936": "0",
        "bb30d0aa": "8",
        "a216091f": "k",
        "9c4c9831": "k",
    }


def extract_arena_powers_hash(screen: np.ndarray) -> List[dict]:
    """Fast hash OCR for the current 960x540 arena opponent layout."""

    gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    hash_map = get_arena_hash_map()
    results = []

    y_centers = [146, 224, 302, 380]
    x_starts = [200, 575]

    for row_idx, y_center in enumerate(y_centers):
        for col_idx, x_start in enumerate(x_starts):
            row_img = thresh[y_center - 20 : y_center + 20, x_start : x_start + 150]
            contours, _ = cv2.findContours(row_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            boxes = []
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                if 4 < w < 25 and 8 < h < 25:
                    boxes.append((x, y, w, h))
            boxes.sort(key=lambda box: box[0])

            text = ""
            for x, y, w, h in boxes:
                char_img = row_img[y : y + h, x : x + w]
                key = hashlib.md5(char_img.tobytes()).hexdigest()[:8]
                text += hash_map.get(key, "")

            if text.endswith("k1"):
                text = text[:-1]

            results.append(
                {
                    "row": row_idx + 1,
                    "col": col_idx + 1,
                    "power_text": text,
                    "power_k": parse_power_value(text),
                }
            )
    return results


ARENA_POWER_COL_X_RANGES = ((214, 300), (592, 675))
ARENA_POWER_ROW_Y_RANGES = ((140, 180), (218, 258), (296, 336), (374, 414))
ARENA_POWER_OCR_SCALE = 2
ARENA_POWER_OCR_PAD = 20
ARENA_POWER_OCR_GAP = 20


def build_easyocr_reader(
    languages: Optional[Sequence[str]] = None,
    *,
    download_enabled: bool = True,
):
    normalized_languages = tuple(languages or ("en",))
    import_started = time.perf_counter()
    import easyocr
    _profile_load(
        f"easyocr import languages={','.join(normalized_languages)} "
        f"elapsed={time.perf_counter() - import_started:.3f}s"
    )

    reader_started = time.perf_counter()
    EASYOCR_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    reader = easyocr.Reader(
        list(normalized_languages),
        gpu=False,
        verbose=False,
        download_enabled=download_enabled,
        model_storage_directory=str(EASYOCR_MODEL_DIR),
    )
    _profile_load(
        f"easyocr reader initialized languages={','.join(normalized_languages)} "
        f"elapsed={time.perf_counter() - reader_started:.3f}s"
    )
    return reader


def get_cached_easyocr_reader(
    languages: Sequence[str] = ("en",),
    *,
    download_enabled: bool = False,
):
    normalized_languages = tuple(languages)
    key = (normalized_languages, bool(download_enabled))
    with _EASYOCR_READER_CACHE_LOCK:
        cached = _EASYOCR_READER_CACHE.get(key)
        if cached is not None:
            _profile_load(f"easyocr cache hit languages={','.join(normalized_languages)}")
            return cached

        _profile_load(f"easyocr cache miss languages={','.join(normalized_languages)}")
        reader = build_easyocr_reader(normalized_languages, download_enabled=download_enabled)
        profiled = _ProfiledEasyOCRReader(reader, normalized_languages)
        _EASYOCR_READER_CACHE[key] = profiled
        return profiled


def clear_easyocr_reader_cache() -> None:
    with _EASYOCR_READER_CACHE_LOCK:
        _EASYOCR_READER_CACHE.clear()


@dataclass(frozen=True)
class DigitOcrResult:
    value: Optional[int]
    confidence: float
    text: str = ""
    scale: Optional[float] = None
    source: str = "none"
    agreement_count: int = 0
    accepted: bool = False


OcrParser = Callable[[str], Optional[int]]
OcrPreprocessor = Callable[[np.ndarray], np.ndarray]


def parse_digits_ocr_text(text: str) -> Optional[int]:
    digits = "".join(char for char in str(text) if char.isdigit())
    return int(digits) if digits else None


def parse_time_hhmmss_ocr_text(text: str) -> Optional[int]:
    compact = re.sub(r"\s+", "", str(text))
    match = re.search(r"(?<!\d)(\d{1,2}):([0-5]\d):([0-5]\d)(?!\d)", compact)
    if match is None:
        return None
    hours, minutes, seconds = (int(value) for value in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def parse_power_ocr_text(text: str) -> Optional[int]:
    cleaned = re.sub(r"[^0-9kKmM,]", "", str(text))
    if not cleaned:
        return None
    match = re.search(r"(\d+)([kKmM])?", cleaned.replace(",", ""))
    if match is None:
        return None
    value = int(match.group(1))
    suffix = (match.group(2) or "").lower()
    if suffix == "m":
        return value * 1000
    return value


def read_digits_easyocr_multiscale(
    image: np.ndarray,
    *,
    reader,
    scales: Sequence[int] = (2, 3, 4, 5),
    fast_accept_confidence: float = 0.85,
    min_agreement_count: int = 2,
    pad_pixels: int = 12,
    border_value: Sequence[int] = (255, 255, 255),
    agreement_accept_confidence: float = 0.50,
) -> DigitOcrResult:
    """Read a small pure-digit ROI with resize fallback."""
    return read_pattern_easyocr_multiscale(
        image,
        reader=reader,
        parser=parse_digits_ocr_text,
        allowlist="0123456789",
        scales=scales,
        fast_accept_confidence=fast_accept_confidence,
        min_agreement_count=min_agreement_count,
        pad_pixels=pad_pixels,
        border_value=border_value,
        agreement_accept_confidence=agreement_accept_confidence,
    )


def read_pattern_easyocr_multiscale(
    image: np.ndarray,
    *,
    reader,
    parser: OcrParser,
    allowlist: str,
    scales: Sequence[float] = (2, 3, 4, 5),
    fast_accept_confidence: float = 0.85,
    min_agreement_count: int = 2,
    pad_pixels: int = 12,
    border_value: Sequence[int] = (255, 255, 255),
    agreement_accept_confidence: float = 0.50,
    preprocess: Optional[OcrPreprocessor] = None,
    interpolation: int = cv2.INTER_CUBIC,
) -> DigitOcrResult:
    """Read a fixed-format OCR ROI with resize fallback and parsed-value agreement."""
    if image.size == 0:
        return DigitOcrResult(value=None, confidence=0.0)

    source_image = preprocess(image) if preprocess is not None else image
    observations: list[DigitOcrResult] = []
    best = DigitOcrResult(value=None, confidence=0.0)
    for scale in scales:
        prepared = cv2.resize(
            source_image,
            None,
            fx=float(scale),
            fy=float(scale),
            interpolation=interpolation,
        )
        if pad_pixels > 0:
            prepared = cv2.copyMakeBorder(
                prepared,
                pad_pixels,
                pad_pixels,
                pad_pixels,
                pad_pixels,
                cv2.BORDER_CONSTANT,
                value=list(border_value),
            )

        text, confidence = _read_fixed_text_easyocr(prepared, reader, allowlist=allowlist)
        if not text:
            continue
        value = parser(text)
        if value is None:
            result = DigitOcrResult(
                value=None,
                confidence=confidence,
                text=text,
                scale=float(scale),
                source="unparsed",
                agreement_count=1,
            )
            observations.append(result)
            if result.confidence > best.confidence:
                best = result
            continue

        result = DigitOcrResult(
            value=value,
            confidence=confidence,
            text=text,
            scale=float(scale),
            source="single_scale",
            agreement_count=1,
        )
        observations.append(result)
        if result.confidence > best.confidence:
            best = result

        parsed_observations = [item for item in observations if item.value is not None]
        observed_values = {item.value for item in parsed_observations}
        if len(observed_values) > 1:
            continue

        if result.confidence >= fast_accept_confidence:
            return DigitOcrResult(
                value=result.value,
                confidence=result.confidence,
                text=result.text,
                scale=result.scale,
                source="fast_accept",
                agreement_count=1,
                accepted=True,
            )

        if len(parsed_observations) >= min_agreement_count:
            agreed_best = max(parsed_observations, key=lambda item: item.confidence)
            if agreed_best.confidence < agreement_accept_confidence:
                continue
            return DigitOcrResult(
                value=agreed_best.value,
                confidence=agreed_best.confidence,
                text=agreed_best.text,
                scale=agreed_best.scale,
                source="multiscale_agreement",
                agreement_count=len(parsed_observations),
                accepted=True,
            )

    parsed_observations = [item for item in observations if item.value is not None]
    if len({item.value for item in parsed_observations}) > 1:
        return DigitOcrResult(
            value=None,
            confidence=0.0,
            source="conflict",
            agreement_count=len(parsed_observations),
        )
    return best


def _read_fixed_text_easyocr(image: np.ndarray, reader, *, allowlist: str) -> tuple[str, float]:
    try:
        results = reader.readtext(image, detail=1, allowlist=allowlist)
    except TypeError:
        results = reader.readtext(image, allowlist=allowlist)

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
    text = "".join(piece[1] for piece in pieces).replace(" ", "")
    confidence = min(piece[2] for piece in pieces)
    return text, confidence


def read_texts_easyocr(
    screen: np.ndarray,
    *,
    roi: Optional[Tuple[int, int, int, int]] = None,
    reader=None,
    languages: Optional[Sequence[str]] = None,
    download_enabled: bool = False,
    allowlist: Optional[str] = None,
) -> List[dict]:
    """Read text fragments in a fixed ROI.

    This is for page/state confirmation only. Callers should use fuzzy keyword
    checks because stylized Chinese UI text can be misread, e.g. `高級契約` as
    `高紐契約`.
    """

    if reader is None:
        reader = get_cached_easyocr_reader(
            languages or ("ch_tra", "en"),
            download_enabled=download_enabled,
        )

    image = screen
    offset_x = 0
    offset_y = 0
    if roi is not None:
        x, y, w, h = roi
        height, width = screen.shape[:2]
        x1 = max(0, int(x))
        y1 = max(0, int(y))
        x2 = min(width, x1 + max(0, int(w)))
        y2 = min(height, y1 + max(0, int(h)))
        image = screen[y1:y2, x1:x2]
        offset_x = x1
        offset_y = y1

    if image.size == 0:
        return []

    if allowlist:
        ocr_results = reader.readtext(image, detail=1, allowlist=allowlist)
    else:
        ocr_results = reader.readtext(image, detail=1)

    fragments = []
    for box, text, confidence in ocr_results:
        fragments.append(
            {
                "text": str(text),
                "confidence": float(confidence),
                "box": _offset_box(box, offset_x, offset_y),
            }
        )
    return fragments


def normalize_ocr_text(text: str) -> str:
    return "".join(char for char in str(text) if char.isalnum() or "\u4e00" <= char <= "\u9fff")


def fuzzy_text_score(observed: str, expected: str) -> float:
    observed_norm = normalize_ocr_text(observed)
    expected_norm = normalize_ocr_text(expected)
    if not observed_norm or not expected_norm:
        return 0.0
    return float(SequenceMatcher(None, observed_norm, expected_norm).ratio())


def contains_core_keywords(observed: str, expected: str) -> bool:
    observed_norm = normalize_ocr_text(observed)
    expected_norm = normalize_ocr_text(expected)
    keywords = [char for char in expected_norm if "\u4e00" <= char <= "\u9fff"]
    if len(keywords) <= 4:
        required = keywords
    else:
        required = keywords[:2] + keywords[-2:]
    return all(char in observed_norm for char in required)


def extract_arena_powers_easyocr(screen: np.ndarray, reader=None) -> List[dict]:
    """Read the 8 fixed-position Arena opponent power values with EasyOCR.

    The ROI intentionally includes only the power text area. EasyOCR sometimes
    also sees score text farther right, so boxes near the far-right edge are
    ignored before combining text fragments.
    """

    if reader is None:
        reader = get_cached_easyocr_reader(("en",), download_enabled=False)

    results = []
    for row_idx, (y0, y1) in enumerate(ARENA_POWER_ROW_Y_RANGES):
        for col_idx, (x0, x1) in enumerate(ARENA_POWER_COL_X_RANGES):
            roi = screen[y0:y1, x0:x1]
            roi_large = cv2.resize(roi, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            roi_pad = cv2.copyMakeBorder(
                roi_large,
                20,
                20,
                20,
                20,
                cv2.BORDER_CONSTANT,
                value=[255, 255, 255],
            )
            ocr_results = reader.readtext(roi_pad, allowlist="0123456789kK,")
            text, confidence = _combine_arena_power_ocr_results(ocr_results)
            results.append(
                {
                    "row": row_idx + 1,
                    "col": col_idx + 1,
                    "power_text": text,
                    "power_k": parse_power_value(text),
                    "has_scale_suffix": power_has_scale_suffix(text),
                    "confidence": confidence,
                }
            )
    return results


def extract_arena_powers_easyocr_batch(screen: np.ndarray, reader=None) -> List[dict]:
    """Read all 8 Arena power values with one EasyOCR call.

    The 8 fixed power ROIs are copied into a white composite image, preserving
    each ROI's local coordinate system. This avoids 8 separate EasyOCR calls
    while keeping the same score-text filtering used by the per-slot reader.
    """

    if reader is None:
        reader = get_cached_easyocr_reader(("en",), download_enabled=False)

    canvas, slots = _build_arena_power_ocr_canvas(screen)
    try:
        ocr_results = reader.readtext(canvas, detail=1, allowlist="0123456789kK,")
    except TypeError:
        ocr_results = reader.readtext(canvas, allowlist="0123456789kK,")

    grouped = {(row, col): [] for row, col, *_ in slots}
    for box, text, confidence in ocr_results:
        xs = _box_x_values(box)
        ys = _box_y_values(box)
        if not xs or not ys:
            continue
        center_x = sum(xs) / len(xs)
        center_y = sum(ys) / len(ys)
        for row, col, left, top, width, height in slots:
            if left <= center_x <= left + width and top <= center_y <= top + height:
                local_box = [[point[0] - left, point[1] - top] for point in box]
                grouped[(row, col)].append((local_box, text, confidence))
                break

    results = []
    for row, col, *_ in slots:
        text, confidence = _combine_arena_power_ocr_results(grouped[(row, col)])
        results.append(
            {
                "row": row,
                "col": col,
                "power_text": text,
                "power_k": parse_power_value(text),
                "has_scale_suffix": power_has_scale_suffix(text),
                "confidence": confidence,
            }
        )
    return results


def _build_arena_power_ocr_canvas(screen: np.ndarray):
    sample_y0, sample_y1 = ARENA_POWER_ROW_Y_RANGES[0]
    sample_x0, sample_x1 = ARENA_POWER_COL_X_RANGES[0]
    crop_h = (sample_y1 - sample_y0) * ARENA_POWER_OCR_SCALE
    crop_w = (sample_x1 - sample_x0) * ARENA_POWER_OCR_SCALE
    cell_h = crop_h + ARENA_POWER_OCR_PAD * 2
    cell_w = crop_w + ARENA_POWER_OCR_PAD * 2
    rows = len(ARENA_POWER_ROW_Y_RANGES)
    cols = len(ARENA_POWER_COL_X_RANGES)
    canvas_h = rows * cell_h + (rows - 1) * ARENA_POWER_OCR_GAP
    canvas_w = cols * cell_w + (cols - 1) * ARENA_POWER_OCR_GAP
    canvas = np.full((canvas_h, canvas_w, 3), 255, dtype=np.uint8)
    slots = []

    for row_idx, (y0, y1) in enumerate(ARENA_POWER_ROW_Y_RANGES):
        for col_idx, (x0, x1) in enumerate(ARENA_POWER_COL_X_RANGES):
            roi = screen[y0:y1, x0:x1]
            roi_large = cv2.resize(
                roi,
                None,
                fx=ARENA_POWER_OCR_SCALE,
                fy=ARENA_POWER_OCR_SCALE,
                interpolation=cv2.INTER_CUBIC,
            )
            roi_pad = cv2.copyMakeBorder(
                roi_large,
                ARENA_POWER_OCR_PAD,
                ARENA_POWER_OCR_PAD,
                ARENA_POWER_OCR_PAD,
                ARENA_POWER_OCR_PAD,
                cv2.BORDER_CONSTANT,
                value=[255, 255, 255],
            )
            top = row_idx * (cell_h + ARENA_POWER_OCR_GAP)
            left = col_idx * (cell_w + ARENA_POWER_OCR_GAP)
            height, width = roi_pad.shape[:2]
            canvas[top : top + height, left : left + width] = roi_pad
            slots.append((row_idx + 1, col_idx + 1, left, top, width, height))

    return canvas, slots


def _combine_arena_power_ocr_results(ocr_results) -> tuple[str, float]:
    pieces = []
    for box, text, confidence in ocr_results:
        clean = str(text).lower().replace(" ", "")
        if not any(char.isdigit() for char in clean):
            continue
        xs = _box_x_values(box)
        if not xs:
            continue
        left = min(xs)
        center = sum(xs) / len(xs)
        if center > 240:
            continue
        pieces.append((left, clean, float(confidence)))

    if not pieces:
        return "", 0.0

    pieces.sort(key=lambda item: item[0])
    text = "".join(piece[1] for piece in pieces)
    if "k" in text:
        text = text[: text.index("k") + 1]
    confidence = min(piece[2] for piece in pieces)
    return text, confidence


def _box_x_values(box) -> List[float]:
    values = []
    for point in box:
        try:
            values.append(float(point[0]))
        except (TypeError, ValueError, IndexError):
            continue
    return values


def _box_y_values(box) -> List[float]:
    values = []
    for point in box:
        try:
            values.append(float(point[1]))
        except (TypeError, ValueError, IndexError):
            continue
    return values


def _offset_box(box, offset_x: int, offset_y: int) -> List[Tuple[float, float]]:
    points = []
    for point in box:
        try:
            points.append((float(point[0]) + offset_x, float(point[1]) + offset_y))
        except (TypeError, ValueError, IndexError):
            continue
    return points
