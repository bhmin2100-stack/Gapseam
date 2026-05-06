from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Optional, Tuple

from gapsim.ui_qt.switch_schema import default_switch_state

Point = Tuple[float, float]

_EPS = 1e-9


def _as_points(points: List[Point]) -> List[Point]:
    out: List[Point] = []
    for x, y in points or []:
        out.append((float(x), float(y)))
    return out


def _turn_strength(points: List[Point], idx: int) -> float:
    if idx <= 0 or idx >= len(points) - 1:
        return 0.0
    ax = float(points[idx][0] - points[idx - 1][0])
    ay = float(points[idx][1] - points[idx - 1][1])
    bx = float(points[idx + 1][0] - points[idx][0])
    by = float(points[idx + 1][1] - points[idx][1])
    la = math.hypot(ax, ay)
    lb = math.hypot(bx, by)
    if la <= _EPS or lb <= _EPS:
        return 0.0
    cross = ax * by - ay * bx
    dot = ax * bx + ay * by
    return abs(math.atan2(cross, dot)) / math.pi


def _profile_bounds(points: List[Point]) -> Dict[str, float]:
    pts = _as_points(points)
    if not pts:
        return {
            "min_x": -1.0,
            "max_x": 1.0,
            "top_y": 0.0,
            "bottom_y": -1.0,
            "center_x": 0.0,
            "depth": 1.0,
            "width": 2.0,
        }
    xs = [x for x, _y in pts]
    ys = [y for _x, y in pts]
    min_x = min(xs)
    max_x = max(xs)
    top_y = max(ys)
    bottom_y = min(ys)
    return {
        "min_x": min_x,
        "max_x": max_x,
        "top_y": top_y,
        "bottom_y": bottom_y,
        "center_x": 0.5 * (min_x + max_x),
        "depth": max(1.0, top_y - bottom_y),
        "width": max(1.0, max_x - min_x),
    }


def _choose_side_lip(points: List[Point], side: str) -> Optional[Tuple[int, Point]]:
    pts = _as_points(points)
    if len(pts) < 2:
        return None
    bounds = _profile_bounds(pts)
    center_x = bounds["center_x"]
    top_y = bounds["top_y"]
    depth = bounds["depth"]
    top_band = top_y - (0.20 * depth)

    candidates: List[Tuple[float, int, Point]] = []
    for idx in range(1, len(pts) - 1):
        x, y = pts[idx]
        if side == "left" and x > center_x + _EPS:
            continue
        if side == "right" and x < center_x - _EPS:
            continue
        if y < top_band:
            continue
        turn = _turn_strength(pts, idx)
        if turn <= 0.01:
            continue
        center_gain = 1.0 / (abs(x - center_x) + 1.0)
        score = (2.0 * turn) + center_gain
        candidates.append((score, idx, (x, y)))

    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1], candidates[0][2]

    seg_candidates: List[Point] = []
    for idx in range(len(pts) - 1):
        a = pts[idx]
        b = pts[idx + 1]
        dy = abs(b[1] - a[1])
        if dy < 0.08 * depth:
            continue
        top_point = a if a[1] >= b[1] else b
        deep_point = b if a[1] >= b[1] else a
        if top_point[1] < top_band:
            continue
        if deep_point[1] > top_y - (0.30 * depth):
            continue
        if side == "left" and top_point[0] <= center_x:
            seg_candidates.append(top_point)
        if side == "right" and top_point[0] >= center_x:
            seg_candidates.append(top_point)

    if seg_candidates:
        if side == "left":
            point = max(seg_candidates, key=lambda item: item[0])
        else:
            point = min(seg_candidates, key=lambda item: item[0])
        return 0, point

    fallback = [pt for pt in pts if (pt[0] <= center_x if side == "left" else pt[0] >= center_x)]
    if not fallback:
        return None
    if side == "left":
        point = max(fallback, key=lambda item: item[0])
    else:
        point = min(fallback, key=lambda item: item[0])
    return 0, point


def detect_lip_points(points: List[Point]) -> Dict[str, Dict[str, float]]:
    pts = _as_points(points)
    if len(pts) < 2:
        bounds = _profile_bounds(pts)
        return {
            "left": {"x": bounds["min_x"], "y": bounds["top_y"]},
            "right": {"x": bounds["max_x"], "y": bounds["top_y"]},
        }

    left = _choose_side_lip(pts, "left")
    right = _choose_side_lip(pts, "right")
    bounds = _profile_bounds(pts)

    left_point = left[1] if left is not None else (bounds["min_x"], bounds["top_y"])
    right_point = right[1] if right is not None else (bounds["max_x"], bounds["top_y"])
    if left_point[0] >= right_point[0]:
        mid = bounds["center_x"]
        left_point = (min(left_point[0], mid - 0.5), left_point[1])
        right_point = (max(right_point[0], mid + 0.5), right_point[1])

    return {
        "left": {"x": float(left_point[0]), "y": float(left_point[1])},
        "right": {"x": float(right_point[0]), "y": float(right_point[1])},
    }


def _sections_from_count(
    division_count: int,
    lip_y: float,
    bottom_y: float,
    *,
    existing_sections: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    count = max(1, int(division_count))
    out: List[Dict[str, Any]] = []
    for idx in range(count):
        t = float(idx + 1) / float(count + 1)
        y = float(lip_y + (bottom_y - lip_y) * t)
        prev = existing_sections[idx] if isinstance(existing_sections, list) and idx < len(existing_sections) else {}
        out.append(
            {
                "id": str(prev.get("id") or f"section_{idx + 1:02d}"),
                "y": float(prev.get("y", y)),
                "enabled": bool(prev.get("enabled", True)),
                "weight": max(0.0, float(prev.get("weight", 1.0))),
            }
        )
    out.sort(key=lambda item: item["y"], reverse=True)
    return out


def auto_anchor_spec(
    pre_points: List[Point],
    post_points: List[Point],
    *,
    division_count: int = 10,
) -> Dict[str, Any]:
    pre = _as_points(pre_points)
    post = _as_points(post_points)
    pre_bounds = _profile_bounds(pre)
    post_bounds = _profile_bounds(post)
    lips = detect_lip_points(pre)
    left_lip = lips["left"]
    right_lip = lips["right"]
    top_y = max(pre_bounds["top_y"], post_bounds["top_y"])
    bottom_y = min(pre_bounds["bottom_y"], post_bounds["bottom_y"])

    left_outer = min(pre_bounds["min_x"], post_bounds["min_x"])
    right_outer = max(pre_bounds["max_x"], post_bounds["max_x"])
    left_top_span = max(1.0, abs(left_lip["x"] - left_outer))
    right_top_span = max(1.0, abs(right_outer - right_lip["x"]))
    top_left_x = max(left_outer, left_lip["x"] - (0.5 * left_top_span))
    top_right_x = min(right_outer, right_lip["x"] + (0.5 * right_top_span))

    lip_y = 0.5 * (left_lip["y"] + right_lip["y"])
    sections = _sections_from_count(division_count, lip_y, bottom_y)
    return {
        "division_count": max(1, int(division_count)),
        "left_lip": {"x": float(left_lip["x"]), "y": float(left_lip["y"])},
        "right_lip": {"x": float(right_lip["x"]), "y": float(right_lip["y"])},
        "bottom": {"x": float(0.5 * (left_lip["x"] + right_lip["x"])), "y": float(bottom_y)},
        "top": {
            "left_x": float(top_left_x),
            "right_x": float(top_right_x),
        },
        "weights": {
            "top": 1.0,
            "lip": 1.0,
            "sidewall": 1.0,
            "bottom": 1.0,
        },
        "sections": sections,
    }


def sanitize_anchor_spec(
    pre_points: List[Point],
    post_points: List[Point],
    anchor_spec: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    auto = auto_anchor_spec(
        pre_points,
        post_points,
        division_count=int((anchor_spec or {}).get("division_count", 10) or 10),
    )
    raw = dict(anchor_spec or {})

    bounds = _profile_bounds(_as_points(pre_points) + _as_points(post_points))
    min_x = bounds["min_x"]
    max_x = bounds["max_x"]
    top_y = bounds["top_y"]
    bottom_limit = bounds["bottom_y"]

    def _point(name: str) -> Dict[str, float]:
        base = auto.get(name, {})
        user = raw.get(name) if isinstance(raw.get(name), dict) else {}
        x = float(user.get("x", base.get("x", 0.0)))
        y = float(user.get("y", base.get("y", 0.0)))
        return {"x": x, "y": y}

    left_lip = _point("left_lip")
    right_lip = _point("right_lip")
    if left_lip["x"] >= right_lip["x"]:
        left_lip = dict(auto["left_lip"])
        right_lip = dict(auto["right_lip"])

    left_lip["x"] = max(min_x, min(right_lip["x"] - 0.5, left_lip["x"]))
    right_lip["x"] = min(max_x, max(left_lip["x"] + 0.5, right_lip["x"]))
    left_lip["y"] = max(bottom_limit, min(top_y, left_lip["y"]))
    right_lip["y"] = max(bottom_limit, min(top_y, right_lip["y"]))

    bottom_raw = raw.get("bottom") if isinstance(raw.get("bottom"), dict) else {}
    bottom = {
        "x": float(bottom_raw.get("x", auto["bottom"]["x"])),
        "y": float(bottom_raw.get("y", auto["bottom"]["y"])),
    }
    bottom["x"] = max(left_lip["x"], min(right_lip["x"], bottom["x"]))
    bottom["y"] = max(bottom_limit, min(top_y, bottom["y"]))

    top_raw = raw.get("top") if isinstance(raw.get("top"), dict) else {}
    top = {
        "left_x": float(top_raw.get("left_x", auto["top"]["left_x"])),
        "right_x": float(top_raw.get("right_x", auto["top"]["right_x"])),
    }
    top["left_x"] = max(min_x, min(left_lip["x"] - 0.5, top["left_x"]))
    top["right_x"] = min(max_x, max(right_lip["x"] + 0.5, top["right_x"]))

    weights_raw = raw.get("weights") if isinstance(raw.get("weights"), dict) else {}
    weights = {
        "top": max(0.0, float(weights_raw.get("top", auto["weights"]["top"]))),
        "lip": max(0.0, float(weights_raw.get("lip", auto["weights"]["lip"]))),
        "sidewall": max(0.0, float(weights_raw.get("sidewall", auto["weights"]["sidewall"]))),
        "bottom": max(0.0, float(weights_raw.get("bottom", auto["weights"]["bottom"]))),
    }

    division_count = max(1, int(raw.get("division_count", auto["division_count"])))
    lip_y = 0.5 * (left_lip["y"] + right_lip["y"])
    sections = _sections_from_count(
        division_count,
        lip_y,
        bottom["y"],
        existing_sections=raw.get("sections") if isinstance(raw.get("sections"), list) else None,
    )
    upper_y = min(left_lip["y"], right_lip["y"])
    lower_y = bottom["y"]
    top_clamp = max(upper_y, lower_y)
    bottom_clamp = min(upper_y, lower_y)
    for section in sections:
        section["y"] = max(bottom_clamp, min(top_clamp, float(section["y"])))
        section["enabled"] = bool(section.get("enabled", True))
        section["weight"] = max(0.0, float(section.get("weight", 1.0)))

    sections.sort(key=lambda item: item["y"], reverse=True)
    return {
        "division_count": division_count,
        "left_lip": left_lip,
        "right_lip": right_lip,
        "bottom": bottom,
        "top": top,
        "weights": weights,
        "sections": sections,
    }


def _vertical_sample_y(points: List[Point], x: float) -> Optional[float]:
    pts = _as_points(points)
    values: List[float] = []
    for idx in range(len(pts) - 1):
        x1, y1 = pts[idx]
        x2, y2 = pts[idx + 1]
        if abs(x2 - x1) <= _EPS:
            if abs(x - x1) <= _EPS:
                values.extend([y1, y2])
            continue
        if (min(x1, x2) - _EPS) <= x <= (max(x1, x2) + _EPS):
            t = (x - x1) / (x2 - x1)
            if -_EPS <= t <= 1.0 + _EPS:
                values.append(y1 + (y2 - y1) * t)
    if not values:
        return None
    return max(values)


def _horizontal_intersections(points: List[Point], y: float) -> List[float]:
    pts = _as_points(points)
    xs: List[float] = []
    for idx in range(len(pts) - 1):
        x1, y1 = pts[idx]
        x2, y2 = pts[idx + 1]
        if abs(y2 - y1) <= _EPS:
            if abs(y - y1) <= _EPS:
                xs.extend([x1, x2])
            continue
        if (min(y1, y2) - _EPS) <= y <= (max(y1, y2) + _EPS):
            t = (y - y1) / (y2 - y1)
            if -_EPS <= t <= 1.0 + _EPS:
                xs.append(x1 + (x2 - x1) * t)
    xs.sort()
    deduped: List[float] = []
    for x in xs:
        if not deduped or abs(x - deduped[-1]) > 1e-6:
            deduped.append(x)
    return deduped


def _wall_positions(points: List[Point], y: float, center_x: float) -> Tuple[Optional[float], Optional[float]]:
    xs = _horizontal_intersections(points, y)
    if len(xs) < 2:
        return None, None
    left_candidates = [x for x in xs if x <= center_x + _EPS]
    right_candidates = [x for x in xs if x >= center_x - _EPS]
    left = max(left_candidates) if left_candidates else min(xs)
    right = min(right_candidates) if right_candidates else max(xs)
    if left > right:
        left, right = min(xs), max(xs)
    return float(left), float(right)


def _minimum_opening(points: List[Point], anchor_spec: Dict[str, Any]) -> float:
    bounds = _profile_bounds(points)
    center_x = 0.5 * (
        float(anchor_spec["left_lip"]["x"]) + float(anchor_spec["right_lip"]["x"])
    )
    lip_y = 0.5 * (
        float(anchor_spec["left_lip"]["y"]) + float(anchor_spec["right_lip"]["y"])
    )
    bottom_y = float(anchor_spec["bottom"]["y"])
    ys: List[float] = []
    for idx in range(21):
        t = float(idx) / 20.0
        ys.append(lip_y + (bottom_y - lip_y) * t)
    ys.extend(float(section["y"]) for section in anchor_spec.get("sections", []) if section.get("enabled", True))
    best = bounds["width"]
    for y in ys:
        left, right = _wall_positions(points, y, center_x)
        if left is None or right is None:
            continue
        best = min(best, max(0.0, right - left))
    return float(best)


def build_feature_entries(
    pre_points: List[Point],
    post_points: List[Point],
    anchor_spec: Dict[str, Any],
) -> List[Dict[str, Any]]:
    pre = _as_points(pre_points)
    post = _as_points(post_points)
    anchor = sanitize_anchor_spec(pre, post, anchor_spec)
    bounds = _profile_bounds(pre + post)
    center_x = 0.5 * (anchor["left_lip"]["x"] + anchor["right_lip"]["x"])
    depth = max(1.0, bounds["top_y"] - anchor["bottom"]["y"])
    opening = max(1.0, anchor["right_lip"]["x"] - anchor["left_lip"]["x"])
    weights = anchor.get("weights", {})

    entries: List[Dict[str, Any]] = []

    def add(name: str, group: str, value: Optional[float], weight: float, scale: float) -> None:
        entries.append(
            {
                "name": name,
                "group": group,
                "value": None if value is None else float(value),
                "weight": max(0.0, float(weight)),
                "scale": max(1.0, float(scale)),
            }
        )

    top_left_x = float(anchor["top"]["left_x"])
    top_right_x = float(anchor["top"]["right_x"])
    top_pre_left = _vertical_sample_y(pre, top_left_x)
    top_pre_right = _vertical_sample_y(pre, top_right_x)
    top_post_left = _vertical_sample_y(post, top_left_x)
    top_post_right = _vertical_sample_y(post, top_right_x)
    top_weight = float(weights.get("top", 1.0))
    add("top_left_thickness", "top", None if top_pre_left is None or top_post_left is None else top_post_left - top_pre_left, top_weight, depth)
    add("top_right_thickness", "top", None if top_pre_right is None or top_post_right is None else top_post_right - top_pre_right, top_weight, depth)

    lip_weight = float(weights.get("lip", 1.0))
    post_lips = detect_lip_points(post)
    add("left_lip_dx", "lip", float(post_lips["left"]["x"] - anchor["left_lip"]["x"]), lip_weight, opening)
    add("left_lip_dy", "lip", float(post_lips["left"]["y"] - anchor["left_lip"]["y"]), lip_weight, depth)
    add("right_lip_dx", "lip", float(post_lips["right"]["x"] - anchor["right_lip"]["x"]), lip_weight, opening)
    add("right_lip_dy", "lip", float(post_lips["right"]["y"] - anchor["right_lip"]["y"]), lip_weight, depth)
    lip_pre_width = max(0.0, float(anchor["right_lip"]["x"] - anchor["left_lip"]["x"]))
    lip_post_width = max(0.0, float(post_lips["right"]["x"] - post_lips["left"]["x"]))
    add("lip_opening_change", "lip", lip_pre_width - lip_post_width, lip_weight, opening)

    side_weight = float(weights.get("sidewall", 1.0))
    for section in anchor.get("sections", []):
        if not section.get("enabled", True):
            continue
        section_weight = side_weight * max(0.0, float(section.get("weight", 1.0)))
        y = float(section["y"])
        pre_left, pre_right = _wall_positions(pre, y, center_x)
        post_left, post_right = _wall_positions(post, y, center_x)
        prefix = str(section.get("id") or "section")
        add(
            f"{prefix}_left_gain",
            "sidewall",
            None if pre_left is None or post_left is None else post_left - pre_left,
            section_weight,
            opening,
        )
        add(
            f"{prefix}_right_gain",
            "sidewall",
            None if pre_right is None or post_right is None else pre_right - post_right,
            section_weight,
            opening,
        )

    bottom_weight = float(weights.get("bottom", 1.0))
    pre_bottom = min((y for _x, y in pre), default=anchor["bottom"]["y"])
    post_bottom = min((y for _x, y in post), default=anchor["bottom"]["y"])
    add("bottom_rise", "bottom", post_bottom - pre_bottom, bottom_weight, depth)

    near_bottom_y = float(anchor["bottom"]["y"] + (0.05 * depth))
    rounding_y = float(anchor["bottom"]["y"] + (0.15 * depth))
    pre_bottom_left, pre_bottom_right = _wall_positions(pre, near_bottom_y, center_x)
    post_bottom_left, post_bottom_right = _wall_positions(post, near_bottom_y, center_x)
    pre_round_left, pre_round_right = _wall_positions(pre, rounding_y, center_x)
    post_round_left, post_round_right = _wall_positions(post, rounding_y, center_x)

    pre_bottom_width = None if pre_bottom_left is None or pre_bottom_right is None else pre_bottom_right - pre_bottom_left
    post_bottom_width = None if post_bottom_left is None or post_bottom_right is None else post_bottom_right - post_bottom_left
    pre_round_width = None if pre_round_left is None or pre_round_right is None else pre_round_right - pre_round_left
    post_round_width = None if post_round_left is None or post_round_right is None else post_round_right - post_round_left

    add(
        "bottom_fill",
        "bottom",
        None if pre_bottom_width is None or post_bottom_width is None else pre_bottom_width - post_bottom_width,
        bottom_weight,
        opening,
    )
    add(
        "bottom_corner_rounding",
        "bottom",
        None
        if pre_round_width is None or post_round_width is None or pre_bottom_width is None or post_bottom_width is None
        else (post_round_width - post_bottom_width) - (pre_round_width - pre_bottom_width),
        bottom_weight,
        opening,
    )
    add(
        "minimum_opening_change",
        "bottom",
        _minimum_opening(pre, anchor) - _minimum_opening(post, anchor),
        bottom_weight,
        opening,
    )

    return entries


def feature_loss(
    target_entries: List[Dict[str, Any]],
    candidate_entries: List[Dict[str, Any]],
) -> float:
    target_by_name = {str(entry["name"]): entry for entry in target_entries}
    candidate_by_name = {str(entry["name"]): entry for entry in candidate_entries}
    total = 0.0
    missing_penalty = 0.0
    for name, target in target_by_name.items():
        weight = max(0.0, float(target.get("weight", 1.0)))
        if weight <= 0.0:
            continue
        candidate = candidate_by_name.get(name)
        target_value = target.get("value")
        candidate_value = None if candidate is None else candidate.get("value")
        scale = max(1.0, float(target.get("scale", 1.0)))
        if target_value is None or candidate_value is None:
            missing_penalty += 25.0 * weight
            continue
        delta = (float(candidate_value) - float(target_value)) / scale
        total += weight * delta * delta
    return total + missing_penalty


def _clamp_float(value: float, lo: float, hi: float) -> float:
    return max(float(lo), min(float(hi), float(value)))


def _finite_median(values: List[float]) -> Optional[float]:
    vals: List[float] = []
    for value in values:
        try:
            fv = float(value)
        except Exception:
            continue
        if math.isfinite(fv):
            vals.append(fv)
    if not vals:
        return None
    vals.sort()
    mid = len(vals) // 2
    if len(vals) % 2 == 1:
        return float(vals[mid])
    return 0.5 * (float(vals[mid - 1]) + float(vals[mid]))


def _vertical_delta_at_x(pre: List[Point], post: List[Point], x: float) -> Optional[float]:
    pre_y = _vertical_sample_y(pre, float(x))
    post_y = _vertical_sample_y(post, float(x))
    if pre_y is None or post_y is None:
        return None
    return float(post_y) - float(pre_y)


def _entry_float(entries: List[Dict[str, Any]], name: str) -> Optional[float]:
    for entry in entries:
        if str(entry.get("name")) != name:
            continue
        value = entry.get("value")
        if value is None:
            return None
        try:
            fv = float(value)
        except Exception:
            return None
        return fv if math.isfinite(fv) else None
    return None


def _sidewall_thickness_samples(
    pre: List[Point],
    post: List[Point],
    anchor: Dict[str, Any],
) -> List[Tuple[float, float, float]]:
    center_x = 0.5 * (float(anchor["left_lip"]["x"]) + float(anchor["right_lip"]["x"]))
    lip_y = 0.5 * (float(anchor["left_lip"]["y"]) + float(anchor["right_lip"]["y"]))
    bottom_y = float(anchor["bottom"]["y"])
    span = max(1.0, abs(lip_y - bottom_y))
    out: List[Tuple[float, float, float]] = []
    for section in anchor.get("sections", []):
        if not isinstance(section, dict) or not section.get("enabled", True):
            continue
        try:
            y = float(section["y"])
        except Exception:
            continue
        pre_left, pre_right = _wall_positions(pre, y, center_x)
        post_left, post_right = _wall_positions(post, y, center_x)
        values: List[float] = []
        if pre_left is not None and post_left is not None:
            values.append(float(post_left) - float(pre_left))
        if pre_right is not None and post_right is not None:
            values.append(float(pre_right) - float(post_right))
        thickness = _finite_median(values)
        if thickness is None:
            continue
        depth_fraction = _clamp_float(abs(lip_y - y) / span, 0.0, 1.0)
        out.append((float(depth_fraction), float(y), float(thickness)))
    out.sort(key=lambda item: item[0])
    return out


def _estimate_inhibition_from_sidewall(
    samples: List[Tuple[float, float, float]],
    *,
    top_thickness: float,
    source_distance_decay_pct: float,
    depth: float,
    fallback_lambda_a: float,
) -> Tuple[float, float]:
    if top_thickness <= _EPS or not samples:
        return 0.0, max(1.0, float(fallback_lambda_a))

    min_factor = 1.0 - (_clamp_float(source_distance_decay_pct, 0.0, 100.0) / 100.0)
    residuals: List[Tuple[float, float]] = []
    for depth_fraction, _y, thickness in samples:
        if depth_fraction > 0.45:
            continue
        observed = _clamp_float(float(thickness) / max(top_thickness, _EPS), 0.0, 1.5)
        predicted = _clamp_float(math.pow(max(min_factor, 1e-6), max(0.0, depth_fraction)), 0.0, 1.0)
        residual = max(0.0, predicted - observed)
        if residual > 0.0:
            residuals.append((float(depth_fraction), float(residual)))

    i_max = max((residual for _depth_fraction, residual in residuals), default=0.0)
    if i_max < 0.05:
        return 0.0, max(1.0, float(fallback_lambda_a))

    lambda_candidates: List[float] = []
    for depth_fraction, residual in residuals:
        if residual <= _EPS or residual >= i_max - _EPS:
            continue
        d = max(1.0, float(depth_fraction) * max(1.0, float(depth)))
        try:
            lambda_candidates.append(-d / math.log(max(1e-6, residual / max(i_max, _EPS))))
        except ValueError:
            continue
    lambda_a = _finite_median(lambda_candidates)
    if lambda_a is None:
        lambda_a = max(10.0, float(depth) * 0.25)
    return _clamp_float(i_max, 0.0, 0.95), _clamp_float(lambda_a, 1.0, 1_000_000.0)


def estimate_fast_prediction_params(
    pre_points: List[Point],
    post_points: List[Point],
    anchor_spec: Dict[str, Any],
    base_params: Dict[str, float],
) -> Optional[Dict[str, Any]]:
    pre = _as_points(pre_points)
    post = _as_points(post_points)
    if len(pre) < 2 or len(post) < 2:
        return None

    anchor = sanitize_anchor_spec(pre, post, anchor_spec)
    cycles = max(1, int(round(float(base_params.get("n_steps", base_params.get("cycles", 200.0)) or 200.0))))
    bounds = _profile_bounds(pre + post)
    depth = max(1.0, float(bounds["top_y"]) - float(anchor["bottom"]["y"]))
    opening = max(1.0, float(anchor["right_lip"]["x"]) - float(anchor["left_lip"]["x"]))

    top_xs = [float(anchor["top"]["left_x"]), float(anchor["top"]["right_x"])]
    top_deltas = [delta for x in top_xs if (delta := _vertical_delta_at_x(pre, post, x)) is not None]
    top_thickness = _finite_median(top_deltas)
    if top_thickness is None or top_thickness <= _EPS:
        return None

    base_rate = float(top_thickness) / float(cycles)
    lip_xs = [float(anchor["left_lip"]["x"]), float(anchor["right_lip"]["x"])]
    lip_deltas = [delta for x in lip_xs if (delta := _vertical_delta_at_x(pre, post, x)) is not None]
    lip_thickness = _finite_median(lip_deltas)
    if lip_thickness is None:
        lip_thickness = float(top_thickness)

    edge_deficit = max(0.0, float(top_thickness) - float(lip_thickness))
    if edge_deficit < max(1e-6, float(top_thickness) * 0.02):
        edge_deficit = 0.0

    # The engine applies sputter as strength * local deposition * angular/visibility terms,
    # with a 3x response gain in mixed deposition/sputter mode.
    aspect = _clamp_float(opening / max(depth, 1.0), 0.0, 1.0)
    sputter_geometry_factor = _clamp_float(0.35 + (0.65 * aspect), 0.15, 1.0)
    sputter_strength_pct = 0.0
    if edge_deficit > 0.0:
        sputter_strength_pct = _clamp_float(
            (edge_deficit / max(float(top_thickness), _EPS)) * (100.0 / (3.0 * sputter_geometry_factor)),
            0.0,
            10_000.0,
        )

    side_samples = _sidewall_thickness_samples(pre, post, anchor)
    side_values = [max(0.0, thickness) for _t, _y, thickness in side_samples]
    lower_side_values = [max(0.0, thickness) for t, _y, thickness in side_samples if t >= 0.55]
    lower_side = _finite_median(lower_side_values)
    if lower_side is None:
        lower_side = _finite_median(side_values)
    if lower_side is None:
        lower_side = float(top_thickness)
    lower_ratio = _clamp_float(float(lower_side) / max(float(top_thickness), _EPS), 0.0, 1.25)
    source_distance_decay_pct = _clamp_float((1.0 - min(1.0, lower_ratio)) * 100.0, 0.0, 100.0)
    if source_distance_decay_pct < 1.0:
        source_distance_decay_pct = 0.0

    i_max, lambda_a = _estimate_inhibition_from_sidewall(
        side_samples,
        top_thickness=float(top_thickness),
        source_distance_decay_pct=source_distance_decay_pct,
        depth=depth,
        fallback_lambda_a=float(base_params.get("lambda_a", 500.0) or 500.0),
    )

    entries = build_feature_entries(pre, post, anchor)
    bottom_rise = _entry_float(entries, "bottom_rise") or 0.0
    bottom_fill = _entry_float(entries, "bottom_fill") or 0.0
    expected_bottom = max(0.0, min(float(top_thickness), float(lower_side)))
    bottom_excess = max(
        0.0,
        float(bottom_rise) - expected_bottom,
        (float(bottom_fill) * 0.5) - expected_bottom,
    )
    redepo_efficiency_pct = 0.0
    if edge_deficit > 0.0 and bottom_excess > max(1e-6, float(top_thickness) * 0.02):
        redepo_efficiency_pct = _clamp_float((bottom_excess / max(edge_deficit, _EPS)) * 100.0, 0.0, 100.0)

    params = {
        "base_rate": float(base_rate),
        "n_steps": float(cycles),
        "source_onset_width_a": 0.0,
        "source_decay_pct": 0.0,
        "source_distance_decay_pct": float(source_distance_decay_pct),
        "sputter_strength_pct": float(sputter_strength_pct),
        "redepo_efficiency_pct": float(redepo_efficiency_pct),
        "redepo_lobe_sigma_deg": _clamp_float(float(base_params.get("redepo_lobe_sigma_deg", 20.0) or 20.0), 1.0, 60.0),
        "i_max": float(i_max),
        "lambda_a": float(lambda_a),
    }
    diagnostics = {
        "cycles": int(cycles),
        "top_thickness": float(top_thickness),
        "lip_thickness": float(lip_thickness),
        "edge_deficit": float(edge_deficit),
        "bottom_excess": float(bottom_excess),
        "lower_sidewall_ratio": float(lower_ratio),
        "sidewall_sample_count": int(len(side_samples)),
        "sputter_geometry_factor": float(sputter_geometry_factor),
    }
    return {"params": params, "diagnostics": diagnostics}


def deep_copy_switch_state(state: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    defaults = default_switch_state()
    out = copy.deepcopy(defaults)
    if not isinstance(state, dict):
        return out
    for sid, payload in state.items():
        if sid not in out or not isinstance(payload, dict):
            continue
        out[sid]["enabled"] = bool(payload.get("enabled", out[sid]["enabled"]))
        params = payload.get("params")
        if isinstance(params, dict):
            out[sid]["params"].update(copy.deepcopy(params))
    return out


def build_switch_state_from_prediction(
    base_state: Dict[str, Dict[str, Any]],
    params: Dict[str, float],
) -> Dict[str, Dict[str, Any]]:
    state = deep_copy_switch_state(base_state)
    conformal = state["conformal"]
    conformal["enabled"] = True
    conformal_params = conformal["params"]
    conformal_params["base_rate"] = float(params["base_rate"])
    conformal_params["n_steps"] = max(1, int(round(float(params["n_steps"]))))

    attenuation = state["attenuation"]
    attenuation_params = attenuation["params"]
    attenuation_params["source_onset_width_a"] = float(params["source_onset_width_a"])
    attenuation_params["source_decay_pct"] = float(params["source_decay_pct"])
    attenuation_params["source_distance_decay_pct"] = float(params["source_distance_decay_pct"])
    attenuation["enabled"] = any(
        abs(float(attenuation_params[key])) > 1e-6
        for key in (
            "source_onset_width_a",
            "source_decay_pct",
            "source_distance_decay_pct",
        )
    )

    inhibition = state["inhibition"]
    inhibition_params = inhibition["params"]
    inhibition_params["i_max"] = float(params["i_max"])
    inhibition_params["lambda_a"] = float(params["lambda_a"])
    inhibition["enabled"] = float(params["i_max"]) > 1e-6 and float(params["lambda_a"]) > 1e-6

    sputter = state.get("sputter")
    if isinstance(sputter, dict):
        sputter_params = sputter.get("params")
        if isinstance(sputter_params, dict) and "sputter_strength_pct" in params and "strength_pct" in sputter_params:
            sputter_params["strength_pct"] = float(params["sputter_strength_pct"])
        sputter["enabled"] = bool(sputter.get("enabled", False)) or float(params.get("sputter_strength_pct", 0.0)) > 1e-6

    redepo = state.get("redepo")
    if isinstance(redepo, dict):
        redepo_params = redepo.get("params")
        if isinstance(redepo_params, dict):
            if "redepo_efficiency_pct" in params and "efficiency_pct" in redepo_params:
                redepo_params["efficiency_pct"] = float(params["redepo_efficiency_pct"])
            if "redepo_lobe_sigma_deg" in params and "lobe_sigma_deg" in redepo_params:
                redepo_params["lobe_sigma_deg"] = float(params["redepo_lobe_sigma_deg"])
        redepo["enabled"] = bool(redepo.get("enabled", False)) or float(params.get("redepo_efficiency_pct", 0.0)) > 1e-6

    return state


def recipe_with_switch_state(
    base_recipe: Dict[str, Any],
    switch_state: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    recipe = copy.deepcopy(base_recipe)
    recipe["phase1_switches"] = deep_copy_switch_state(switch_state)

    run_cfg = recipe.get("run")
    if not isinstance(run_cfg, dict):
        run_cfg = {}
        recipe["run"] = run_cfg
    model_base = recipe.get("model_base")
    if not isinstance(model_base, dict):
        model_base = {}
        recipe["model_base"] = model_base

    conformal = switch_state.get("conformal", {})
    conformal_params = conformal.get("params", {}) if isinstance(conformal, dict) else {}
    attenuation = switch_state.get("attenuation", {})
    attenuation_params = attenuation.get("params", {}) if isinstance(attenuation, dict) else {}
    inhibition = switch_state.get("inhibition", {})
    inhibition_params = inhibition.get("params", {}) if isinstance(inhibition, dict) else {}
    sputter = switch_state.get("sputter", {})
    sputter_params = sputter.get("params", {}) if isinstance(sputter, dict) else {}
    redepo = switch_state.get("redepo", {})
    redepo_params = redepo.get("params", {}) if isinstance(redepo, dict) else {}

    run_cfg["cycles"] = max(1, int(round(float(conformal_params.get("n_steps", run_cfg.get("cycles", 200))))))
    model_base["base_rate"] = float(conformal_params.get("base_rate", model_base.get("base_rate", 1.0)))
    model_base["conformal_enabled"] = bool(conformal.get("enabled", True))
    model_base["source_onset_width_a"] = float(
        attenuation_params.get("source_onset_width_a", model_base.get("source_onset_width_a", 0.0))
    )
    model_base["source_decay_pct"] = float(
        attenuation_params.get("source_decay_pct", model_base.get("source_decay_pct", 0.0))
    )
    model_base["source_distance_decay_pct"] = float(
        attenuation_params.get("source_distance_decay_pct", model_base.get("source_distance_decay_pct", 0.0))
    )
    model_base["inhibition_enabled"] = bool(inhibition.get("enabled", False))
    model_base["inhibition_i_max"] = float(
        inhibition_params.get("i_max", model_base.get("inhibition_i_max", 0.0))
    )
    model_base["inhibition_lambda_a"] = float(
        inhibition_params.get("lambda_a", model_base.get("inhibition_lambda_a", 0.0))
    )
    model_base["sputter_enabled"] = bool(sputter.get("enabled", False))
    model_base["sputter_only"] = bool(sputter_params.get("sputter_only", model_base.get("sputter_only", False)))
    model_base["sputter_strength_pct"] = float(
        sputter_params.get("strength_pct", model_base.get("sputter_strength_pct", 0.0))
    )
    model_base["sputter_peak_angle_deg"] = float(
        sputter_params.get("peak_angle_deg", model_base.get("sputter_peak_angle_deg", 55.0))
    )
    model_base["sputter_angle_sigma_deg"] = float(
        sputter_params.get("angle_sigma_deg", model_base.get("sputter_angle_sigma_deg", 15.0))
    )
    model_base["sputter_depth_decay_length_a"] = float(
        sputter_params.get("depth_decay_length_a", model_base.get("sputter_depth_decay_length_a", 1000.0))
    )
    model_base["sputter_sky_vis_exponent"] = float(
        sputter_params.get("vis_exponent", model_base.get("sputter_sky_vis_exponent", model_base.get("sputter_vis_exponent", 1.0)))
    )
    model_base["redepo_enabled"] = bool(redepo.get("enabled", False))
    model_base["redepo_efficiency_pct"] = float(
        redepo_params.get("efficiency_pct", model_base.get("redepo_efficiency_pct", 0.0))
    )
    model_base["redepo_lobe_sigma_deg"] = float(
        redepo_params.get("lobe_sigma_deg", model_base.get("redepo_lobe_sigma_deg", 20.0))
    )
    return recipe
