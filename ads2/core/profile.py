from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


Roi = Tuple[int, int, int, int]


@dataclass(frozen=True)
class FinishTemplate:
    name: str
    template_path: Path
    roi: Roi
    threshold: float = 0.85
    description: str = ""


@dataclass(frozen=True)
class AdsProfile:
    name: str
    description: str
    ad_wait: Optional[int]
    finish_templates: List[FinishTemplate]


def load_ads_profile(profile: Optional[str | Path], *, project_root: Path, ads2_dir: Path) -> Optional[AdsProfile]:
    if profile is None:
        return None

    profile_path = _resolve_profile_path(profile, ads2_dir)
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    base_dir = profile_path.parent

    finish_templates: List[FinishTemplate] = []
    for item in data.get("finish_templates", []):
        roi = item.get("roi")
        if not isinstance(roi, list) or len(roi) != 4:
            raise ValueError(f"Invalid finish template ROI in {profile_path}: {item!r}")
        template_path = _resolve_path(item["template"], base_dir=base_dir, project_root=project_root)
        finish_templates.append(
            FinishTemplate(
                name=item.get("name", template_path.stem),
                template_path=template_path,
                roi=tuple(int(v) for v in roi),
                threshold=float(item.get("threshold", 0.85)),
                description=item.get("description", ""),
            )
        )

    return AdsProfile(
        name=data.get("name", profile_path.stem),
        description=data.get("description", ""),
        ad_wait=data.get("ad_wait"),
        finish_templates=finish_templates,
    )


def _resolve_profile_path(profile: str | Path, ads2_dir: Path) -> Path:
    path = Path(profile)
    if path.suffix:
        candidates = [path]
    else:
        candidates = [ads2_dir / "profiles" / f"{path}.json", path]

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"ADS2 profile not found: {profile}")


def _resolve_path(path_text: str, *, base_dir: Path, project_root: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path

    base_candidate = (base_dir / path).resolve()
    if base_candidate.exists():
        return base_candidate

    return (project_root / path).resolve()
