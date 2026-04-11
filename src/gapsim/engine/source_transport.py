from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class SourceTransportPreset:
    source_id: str
    name_ko: str
    name_en: str
    onset_width_a: float
    decay_pct: float


SOURCE_TRANSPORT_PRESETS: Dict[str, SourceTransportPreset] = {
    "none": SourceTransportPreset(
        source_id="none",
        name_ko="제한 없음",
        name_en="No limit",
        onset_width_a=0.0,
        decay_pct=0.0,
    ),
    "dipas": SourceTransportPreset(
        source_id="dipas",
        name_ko="DIPAS",
        name_en="DIPAS",
        onset_width_a=60.0,
        decay_pct=98.0,
    ),
    "btbas": SourceTransportPreset(
        source_id="btbas",
        name_ko="BTBAS",
        name_en="BTBAS",
        onset_width_a=78.0,
        decay_pct=98.8,
    ),
    "teos": SourceTransportPreset(
        source_id="teos",
        name_ko="TEOS",
        name_en="TEOS",
        onset_width_a=90.0,
        decay_pct=99.2,
    ),
    "silane": SourceTransportPreset(
        source_id="silane",
        name_ko="Silane",
        name_en="Silane",
        onset_width_a=45.0,
        decay_pct=97.0,
    ),
}


def list_source_type_ids() -> List[str]:
    return list(SOURCE_TRANSPORT_PRESETS.keys())


def get_source_preset(source_id: str) -> SourceTransportPreset:
    key = str(source_id or "none").strip().lower()
    return SOURCE_TRANSPORT_PRESETS.get(key, SOURCE_TRANSPORT_PRESETS["none"])


def resolve_source_transport(
    *,
    source_id: str,
    onset_width_a: float | None = None,
    decay_pct: float | None = None,
    block_width_a: float | None = None,  # legacy key (ignored unless onset is unset)
    gamma: float | None = None,  # legacy key (coarse fallback only)
) -> tuple[str, float, float]:
    preset = get_source_preset(source_id)

    sid = str(source_id or "none").strip().lower()
    if sid not in SOURCE_TRANSPORT_PRESETS:
        sid = "none"

    ow = float(onset_width_a) if onset_width_a is not None else 0.0
    if ow <= 0.0:
        # Legacy fallback path for old recipes.
        legacy_bw = float(block_width_a) if block_width_a is not None else 0.0
        ow = max(float(preset.onset_width_a), legacy_bw)
    ow = max(0.0, ow)

    if decay_pct is None:
        # Legacy gamma fallback (coarse mapping): gamma 1.0 ~= 70%.
        if gamma is not None and float(gamma) > 0.0:
            dp = min(100.0, max(0.0, float(gamma) * 70.0))
        else:
            dp = float(preset.decay_pct)
    else:
        dp = float(decay_pct)
    dp = min(100.0, max(0.0, dp))

    return sid, ow, dp
