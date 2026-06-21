from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

Point = Tuple[float, float]


@dataclass(frozen=True)
class DentRegion:
    x0: float
    y0: float
    x1: float
    y1: float

    def normalized(self) -> "DentRegion":
        return DentRegion(
            min(float(self.x0), float(self.x1)),
            min(float(self.y0), float(self.y1)),
            max(float(self.x0), float(self.x1)),
            max(float(self.y0), float(self.y1)),
        )


@dataclass(frozen=True)
class DentLine:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class DentSample:
    frame_index: int
    cycle: int
    thickness_a: float
    dent_depth_a: Optional[float]
    slope_delta_deg: Optional[float]
    film_angle_deg: Optional[float]
    reference_angle_deg: Optional[float]


def _contains(region: DentRegion, point: Point) -> bool:
    reg = region.normalized()
    x, y = float(point[0]), float(point[1])
    return reg.x0 <= x <= reg.x1 and reg.y0 <= y <= reg.y1


def _points_in_region(profile: Sequence[Point], region: DentRegion) -> List[Point]:
    return [(float(x), float(y)) for x, y in profile if _contains(region, (float(x), float(y)))]


def _angle_deg(p0: Point, p1: Point) -> Optional[float]:
    dx = float(p1[0]) - float(p0[0])
    dy = float(p1[1]) - float(p0[1])
    if math.hypot(dx, dy) <= 1e-12:
        return None
    return math.degrees(math.atan2(dy, dx))


def _fold_angle_delta_deg(angle: float, reference: float) -> float:
    delta = (float(angle) - float(reference) + 180.0) % 360.0 - 180.0
    if delta > 90.0:
        delta -= 180.0
    elif delta < -90.0:
        delta += 180.0
    return delta


def measure_dent_depth(
    profile: Sequence[Point],
    region: DentRegion,
    orientation: str,
) -> Optional[float]:
    pts = _points_in_region(profile, region)
    if not pts:
        return None
    axis = str(orientation or "").strip().lower()
    if axis == "horizontal":
        values = [x for x, _ in pts]
    else:
        values = [y for _, y in pts]
    return max(values) - min(values)


def _point_segment_distance(point: Point, a: Point, b: Point) -> float:
    px, py = float(point[0]), float(point[1])
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    vv = vx * vx + vy * vy
    if vv <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / vv))
    cx, cy = ax + t * vx, ay + t * vy
    return math.hypot(px - cx, py - cy)


def _principal_axis_angle_deg(points: Sequence[Point]) -> Optional[float]:
    if len(points) < 2:
        return None
    xs = [float(x) for x, _ in points]
    ys = [float(y) for _, y in points]
    mx = sum(xs) / float(len(xs))
    my = sum(ys) / float(len(ys))
    sxx = sum((x - mx) * (x - mx) for x in xs)
    syy = sum((y - my) * (y - my) for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if abs(sxx) + abs(syy) <= 1e-12:
        return None
    return math.degrees(0.5 * math.atan2(2.0 * sxy, sxx - syy))


def measure_profile_slope(
    profile: Sequence[Point],
    region: DentRegion,
    reference_line: DentLine,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    reference_angle = _angle_deg(
        (reference_line.x0, reference_line.y0),
        (reference_line.x1, reference_line.y1),
    )
    if reference_angle is None:
        return None, None, None

    reg = region.normalized()
    candidates: List[Tuple[float, float]] = []
    ref_mid = (
        (float(reference_line.x0) + float(reference_line.x1)) * 0.5,
        (float(reference_line.y0) + float(reference_line.y1)) * 0.5,
    )
    for p0, p1 in zip(profile, profile[1:]):
        a = (float(p0[0]), float(p0[1]))
        b = (float(p1[0]), float(p1[1]))
        mid = ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)
        if not _contains(reg, mid):
            continue
        angle = _angle_deg(a, b)
        if angle is None:
            continue
        candidates.append((_point_segment_distance(ref_mid, a, b), angle))

    if candidates:
        _, film_angle = min(candidates, key=lambda item: item[0])
    else:
        film_angle = _principal_axis_angle_deg(_points_in_region(profile, reg))
    if film_angle is None:
        return None, None, reference_angle
    return _fold_angle_delta_deg(film_angle, reference_angle), film_angle, reference_angle


def analyze_dent_frames(
    frame_profiles: Sequence[Sequence[Point]],
    frame_steps: Sequence[int],
    region: DentRegion,
    orientation: str,
    *,
    slope_line: Optional[DentLine] = None,
    angstrom_per_cycle: float = 0.0,
) -> List[DentSample]:
    samples: List[DentSample] = []
    rate = max(0.0, float(angstrom_per_cycle))
    for frame_index, profile in enumerate(frame_profiles):
        if not profile:
            continue
        cycle = int(frame_steps[frame_index]) if frame_index < len(frame_steps) else frame_index
        depth = measure_dent_depth(profile, region, orientation)
        slope_delta = None
        film_angle = None
        reference_angle = None
        if slope_line is not None:
            slope_delta, film_angle, reference_angle = measure_profile_slope(profile, region, slope_line)
        samples.append(
            DentSample(
                frame_index=int(frame_index),
                cycle=cycle,
                thickness_a=float(cycle) * rate,
                dent_depth_a=depth,
                slope_delta_deg=slope_delta,
                film_angle_deg=film_angle,
                reference_angle_deg=reference_angle,
            )
        )
    return samples


def dent_samples_to_payload(samples: Iterable[DentSample]) -> List[dict]:
    return [asdict(sample) for sample in samples]
