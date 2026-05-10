from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional


def _default_research_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "emulator_research"
    return Path("emulator_research")


DEFAULT_RESEARCH_ROOT = _default_research_root()
PRESENTATIONS_DIRNAME = "presentations"
RESEARCH_MANIFEST_FILENAME = "research_manifest.json"
MAX_EMULATOR_NUMBER = 6
DEFAULT_CREATED_EMULATOR_NUMBERS = tuple(range(0, MAX_EMULATOR_NUMBER + 1))


@dataclass(frozen=True)
class EmulatorResearchSlot:
    number: int
    slug: str
    title_ko: str
    title_en: str
    status_ko: str
    module: Optional[str] = None

    @property
    def directory_name(self) -> str:
        return f"emulator_{self.number:02d}_{self.slug}"

    @property
    def presentation_filename(self) -> str:
        return f"에뮬레이터{self.number:02d}_{self.title_ko}.pptx"


EMULATOR_RESEARCH_SLOTS = (
    EmulatorResearchSlot(
        number=0,
        slug="integrated_depo_etch_depth_inhibition",
        title_ko="통합_데포_에치_감쇠_인히비션",
        title_en="Integrated Depo Etch Depth Inhibition",
        status_ko="통합: conformal deposition + direct/ion etch + depth/inhibition deposition, redepo 제외",
        module="gapsim.emulation.trench_depo",
    ),
    EmulatorResearchSlot(
        number=1,
        slug="conformal_depo_baseline",
        title_ko="컨포멀_데포_기준",
        title_en="Conformal Deposition Baseline",
        status_ko="기준: etch 없는 conformal deposition 기본 UI",
        module="gapsim.emulation.trench_depo",
    ),
    EmulatorResearchSlot(
        number=2,
        slug="direct_angle_sputter_etch",
        title_ko="각도기반_직접_스퍼터_에치",
        title_en="Direct Angle Sputter Etch",
        status_ko="진행중: trench conformal depo 위에 angle-dependent sputter etch 검증",
        module="gapsim.emulation.trench_depo",
    ),
    EmulatorResearchSlot(
        number=3,
        slug="ion_transmission_shadowing",
        title_ko="이온_도달률_섀도잉",
        title_en="Ion Transmission Shadowing",
        status_ko="진행중: direct sputter 출력에 depth/opening 기반 ion transmission 계수 결합",
        module="gapsim.emulation.trench_depo",
    ),
    EmulatorResearchSlot(
        number=4,
        slug="depth_dependent_depo_fill",
        title_ko="깊이감쇠_데포_잔류충전",
        title_en="Depth-Dependent Deposition Fill",
        status_ko="진행중: redepo 없이 depth-dependent deposition과 closure 후 내부 잔류 fill 검증",
        module="gapsim.emulation.trench_depo",
    ),
    EmulatorResearchSlot(
        number=5,
        slug="inhibition_deposition_fill",
        title_ko="인히비션_증착_필",
        title_en="Inhibition Deposition Fill",
        status_ko="진행중: PECVD/PEALD inhibition coverage field 기반 top/opening suppression fill",
        module="gapsim.emulation.trench_depo",
    ),
    EmulatorResearchSlot(
        number=6,
        slug="reflection_gaussian_ballistic_redeposition",
        title_ko="반사_가우시안_볼리스틱_리데포",
        title_en="Reflection Gaussian Ballistic Redeposition",
        status_ko="진행중: etch source의 specular reflection hit 최대점을 기준으로 Gaussian redepo 후 ballistic correction",
        module="gapsim.emulation.trench_depo",
    ),
)


def iter_emulator_research_slots() -> Iterable[EmulatorResearchSlot]:
    return iter(EMULATOR_RESEARCH_SLOTS)


def get_emulator_research_slot(number: int) -> EmulatorResearchSlot:
    try:
        slot_number = int(number)
    except Exception as exc:
        raise ValueError("emulator number must be an integer from 0 to 6") from exc

    for slot in EMULATOR_RESEARCH_SLOTS:
        if slot.number == slot_number:
            return slot
    raise ValueError("emulator number must be an integer from 0 to 6")


def next_emulator_number(existing_numbers: Iterable[int]) -> Optional[int]:
    existing = {int(number) for number in existing_numbers}
    for number in range(0, MAX_EMULATOR_NUMBER + 1):
        if number not in existing:
            return number
    return None


def _normalized_emulator_numbers(numbers: Iterable[int]) -> list[int]:
    normalized = {
        max(0, min(MAX_EMULATOR_NUMBER, int(number)))
        for number in numbers
    }
    normalized.update(DEFAULT_CREATED_EMULATOR_NUMBERS)
    return sorted(normalized)


def load_created_emulator_numbers(
    *,
    root: Path | str = DEFAULT_RESEARCH_ROOT,
) -> list[int]:
    manifest_path = Path(root) / RESEARCH_MANIFEST_FILENAME
    if not manifest_path.exists():
        return list(DEFAULT_CREATED_EMULATOR_NUMBERS)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return list(DEFAULT_CREATED_EMULATOR_NUMBERS)
    if not isinstance(payload, dict):
        return list(DEFAULT_CREATED_EMULATOR_NUMBERS)
    raw_numbers = payload.get("created_numbers")
    if not isinstance(raw_numbers, list):
        return list(DEFAULT_CREATED_EMULATOR_NUMBERS)
    try:
        return _normalized_emulator_numbers(raw_numbers)
    except (TypeError, ValueError):
        return list(DEFAULT_CREATED_EMULATOR_NUMBERS)


def save_created_emulator_numbers(
    numbers: Iterable[int],
    *,
    root: Path | str = DEFAULT_RESEARCH_ROOT,
) -> Path:
    root_path = Path(root)
    manifest_path = root_path / RESEARCH_MANIFEST_FILENAME
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    payload.setdefault("version", 1)
    payload.setdefault("root", str(root_path))
    payload["created_numbers"] = _normalized_emulator_numbers(numbers)
    root_path.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def emulator_research_paths(
    number: int,
    *,
    root: Path | str = DEFAULT_RESEARCH_ROOT,
) -> Dict[str, Path]:
    slot = get_emulator_research_slot(number)
    root_path = Path(root)
    slot_dir = root_path / slot.directory_name
    return {
        "root": root_path,
        "slot_dir": slot_dir,
        "updates_dir": slot_dir / "updates",
        "presentations_dir": root_path / PRESENTATIONS_DIRNAME,
        "presentation": root_path / PRESENTATIONS_DIRNAME / slot.presentation_filename,
    }


def ensure_emulator_research_slot(
    number: int,
    *,
    root: Path | str = DEFAULT_RESEARCH_ROOT,
) -> Dict[str, Path]:
    paths = emulator_research_paths(number, root=root)
    paths["updates_dir"].mkdir(parents=True, exist_ok=True)
    paths["presentations_dir"].mkdir(parents=True, exist_ok=True)
    return paths


def ensure_emulator_research_tree(
    *,
    root: Path | str = DEFAULT_RESEARCH_ROOT,
    numbers: Optional[Iterable[int]] = None,
) -> Dict[int, Dict[str, Path]]:
    created: Dict[int, Dict[str, Path]] = {}
    slot_numbers = [slot.number for slot in EMULATOR_RESEARCH_SLOTS] if numbers is None else list(numbers)
    for number in slot_numbers:
        paths = ensure_emulator_research_slot(number, root=root)
        created[int(number)] = paths
    return created
