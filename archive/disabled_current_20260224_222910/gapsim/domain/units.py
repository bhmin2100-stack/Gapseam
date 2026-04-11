from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class LengthUnit(str, Enum):
    ANGSTROM = "A"
    NM = "nm"

@dataclass(frozen=True)
class Length:
    value: float
    unit: LengthUnit = LengthUnit.ANGSTROM

def to_angstrom(x: float, unit: LengthUnit) -> float:
    if unit == LengthUnit.ANGSTROM:
        return x
    if unit == LengthUnit.NM:
        return x * 10.0
    raise ValueError(f"Unsupported unit: {unit}")

def from_angstrom(a: float, unit: LengthUnit) -> float:
    if unit == LengthUnit.ANGSTROM:
        return a
    if unit == LengthUnit.NM:
        return a / 10.0
    raise ValueError(f"Unsupported unit: {unit}")
